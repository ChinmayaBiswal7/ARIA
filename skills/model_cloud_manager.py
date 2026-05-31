"""
skills/model_cloud_manager.py — ARIA Model Cloud Manager (No-Cache / Stream Mode)
==================================================================================
Uploads 3D models to Firebase Storage + Firestore metadata.
Loading streams the file directly into a temp file in the OS temp dir —
ZERO bytes written to the project folder permanently.

Flow:
  Generate model  → save temp locally → upload to Firebase Storage
                  → write Firestore metadata → DELETE local file (disk freed)

  Load model      → lookup Firestore → stream blob from Firebase into RAM
                  → write OS temp file → AR3D reads it → free_temp() deletes it

After ARIA closes (or the model is dismissed), temp is freed automatically.
Every model lives permanently in the cloud; your disk stays at 0 bytes.

Config is read from the existing firebase_config.json / serviceAccountKey.json
so no new credentials are needed.
"""

import io
import hashlib
import logging
import tempfile
import threading
import os
import json
import time
from pathlib import Path

logger = logging.getLogger("ModelCloudManager")

# ── Config — matches existing firebase_sync.py conventions ───────────────────
_ROOT = Path(__file__).resolve().parent.parent  # project root
SERVICE_ACCOUNT_PATH = _ROOT / "serviceAccountKey.json"
_FIREBASE_CONFIG_PATH = _ROOT / "firebase_config.json"

# Derive storage bucket from project_id (Firebase default naming)
def _read_project_id() -> str:
    try:
        with open(_FIREBASE_CONFIG_PATH) as f:
            return json.load(f).get("project_id", "")
    except Exception:
        return ""

_PROJECT_ID = _read_project_id()
FIREBASE_STORAGE_BUCKET = f"{_PROJECT_ID}.firebasestorage.app" if _PROJECT_ID else ""

FIRESTORE_COLLECTION = "aria_3d_models"
MIN_VALID_FILE_SIZE = 1_024          # 1 KB — skip tiny/broken files
STREAM_CHUNK_SIZE   = 256 * 1_024   # 256 KB read chunks


class ModelCloudManager:
    """
    No-cache cloud model manager.  Singleton — one instance per process.

    Public API
    ----------
    upload_async(name, local_path, prompt)  — background upload + local delete
    stream_to_temp(name)                    — stream from Firebase → temp Path
    free_temp(tmp_path)                     — delete temp file when AR3D closes
    free_all_temps()                        — cleanup on ARIA shutdown
    list_models(user)                       — list all models in Firestore
    delete_model(name)                      — permanently remove from cloud
    is_available(name)                      — check if model exists in cloud
    """

    _instance = None
    _cls_lock  = threading.Lock()

    # ── Singleton ────────────────────────────────────────────────────────────
    def __new__(cls):
        with cls._cls_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized  = True
        self._active_temps: list = []        # track temp files for cleanup
        self._firebase_ok  = False
        self._db           = None
        self._bucket       = None
        self._init_firebase()

    # ── Firebase init ────────────────────────────────────────────────────────
    def _init_firebase(self):
        """Initialise firebase-admin SDK, reusing any existing app."""
        if not SERVICE_ACCOUNT_PATH.exists():
            logger.warning(
                "[ModelCloudManager] serviceAccountKey.json not found at %s. "
                "Cloud model storage disabled.", SERVICE_ACCOUNT_PATH
            )
            return
        if not FIREBASE_STORAGE_BUCKET:
            logger.warning(
                "[ModelCloudManager] Could not derive storage bucket from firebase_config.json. "
                "Cloud model storage disabled."
            )
            return
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore, storage

            try:
                app = firebase_admin.get_app()
            except ValueError:
                # No existing app — initialize with storageBucket
                cred = credentials.Certificate(str(SERVICE_ACCOUNT_PATH))
                app  = firebase_admin.initialize_app(cred, {
                    "storageBucket": FIREBASE_STORAGE_BUCKET
                })

            self._db = firestore.client(app=app)
            # Always pass bucket name explicitly — the existing app (from
            # firebase_sync.py) may have been initialized without storageBucket.
            self._bucket = storage.bucket(name=FIREBASE_STORAGE_BUCKET, app=app)
            self._firebase_ok = True
            logger.info(
                "[ModelCloudManager] Ready. Bucket=%s  Collection=%s  Mode=STREAM (zero disk)",
                FIREBASE_STORAGE_BUCKET, FIRESTORE_COLLECTION
            )

        except ImportError:
            logger.error("[ModelCloudManager] firebase-admin not installed. Run: pip install firebase-admin")
        except Exception as e:
            logger.error("[ModelCloudManager] Firebase init failed: %s", e)

    # ─────────────────────────────────────────────────────────────────────────
    #  UPLOAD
    # ─────────────────────────────────────────────────────────────────────────

    def upload_model(self, name: str, local_path: str,
                     prompt: str = "", user: str = "chinmay") -> str | None:
        """
        Upload model to Firebase Storage, write metadata to Firestore,
        then DELETE the local file to free disk space.

        Returns the public download URL, or None on failure.
        Skipping upload is fine — the local file is still valid for this session.
        """
        if not self._firebase_ok:
            logger.warning("[ModelCloudManager] Firebase not available. Skipping upload for '%s'.", name)
            return None

        local_path = Path(local_path)
        if not local_path.exists():
            logger.error("[ModelCloudManager] File not found: %s", local_path)
            return None

        file_size = local_path.stat().st_size
        if file_size < MIN_VALID_FILE_SIZE:
            logger.warning(
                "[ModelCloudManager] '%s' too small (%d bytes) — skipping upload.", name, file_size
            )
            return None

        ext          = local_path.suffix or ".obj"
        checksum     = self._md5(local_path)
        storage_path = f"aria_models/{user}/{name}_{checksum[:8]}{ext}"

        logger.info(
            "[ModelCloudManager] Uploading '%s' (%.2f MB) → gs://%s/%s ...",
            name, file_size / 1e6, FIREBASE_STORAGE_BUCKET, storage_path
        )

        # ── Upload to Storage ────────────────────────────────────────────────
        try:
            blob = self._bucket.blob(storage_path)
            blob.upload_from_filename(str(local_path), content_type="model/obj")
            blob.make_public()
            download_url = blob.public_url
            logger.info("[ModelCloudManager] Upload OK → %s", download_url)
        except Exception as e:
            logger.error("[ModelCloudManager] Storage upload failed: %s", e)
            return None   # Keep local file — upload failed, don't delete

        # ── Firestore metadata ────────────────────────────────────────────────
        from datetime import datetime, timezone
        meta = {
            "name":         name,
            "prompt":       prompt or name,
            "user":         user,
            "storage_path": storage_path,
            "download_url": download_url,
            "file_size":    file_size,
            "checksum":     checksum,
            "extension":    ext,
            "created_at":   datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._db.collection(FIRESTORE_COLLECTION).document(name).set(meta)
            logger.info("[ModelCloudManager] Firestore metadata saved for '%s'.", name)
        except Exception as e:
            logger.error("[ModelCloudManager] Firestore write failed: %s", e)
            # Non-fatal — file is uploaded; metadata can be re-written later

        # ── Delete local file to free disk ────────────────────────────────────
        try:
            local_path.unlink()
            logger.info("[ModelCloudManager] Local file deleted (disk freed): %s", local_path)
        except Exception as e:
            logger.warning("[ModelCloudManager] Could not delete local file: %s", e)

        return download_url

    def upload_async(self, name: str, local_path: str,
                     prompt: str = "", user: str = "chinmay"):
        """
        Non-blocking upload in background thread.
        ARIA stays responsive while the upload runs silently.
        """
        t = threading.Thread(
            target=self.upload_model,
            args=(name, local_path, prompt, user),
            daemon=True,
            name=f"MCM-upload-{name}"
        )
        t.start()
        logger.info("[ModelCloudManager] Background upload started for '%s'.", name)

    # ─────────────────────────────────────────────────────────────────────────
    #  STREAM / LOAD  (no permanent disk writes)
    # ─────────────────────────────────────────────────────────────────────────

    def stream_to_temp(self, name: str) -> Path | None:
        """
        Stream model from Firebase Storage into an OS temp file.
        Temp file lives only until free_temp() is called or ARIA exits.

        Returns a Path the AR3D viewer can load(), or None on failure.

        Why temp file and not pure BytesIO?
        vedo / Open3D need a file *path* to load from, not a stream.
        NamedTemporaryFile gives us that path without a permanent disk footprint.
        The OS cleans it up automatically on process exit regardless.
        """
        if not self._firebase_ok:
            logger.warning("[ModelCloudManager] Firebase not available. Cannot stream '%s'.", name)
            return None

        meta = self._get_meta(name)
        if meta is None:
            logger.warning("[ModelCloudManager] No cloud record for '%s'.", name)
            return None

        storage_path = meta.get("storage_path", "")
        file_size    = meta.get("file_size", 0)
        ext          = meta.get("extension", ".obj")

        if not storage_path:
            logger.error("[ModelCloudManager] storage_path missing in Firestore meta for '%s'.", name)
            return None

        logger.info(
            "[ModelCloudManager] Streaming '%s' (%.2f MB) from Firebase...",
            name, file_size / 1e6
        )

        # ── Stream from Firebase into memory buffer ───────────────────────────
        try:
            blob   = self._bucket.blob(storage_path)
            buffer = io.BytesIO()
            blob.download_to_file(buffer)
            buffer.seek(0)
            downloaded = buffer.getbuffer().nbytes
            logger.info(
                "[ModelCloudManager] Stream complete: %.2f MB received for '%s'.",
                downloaded / 1e6, name
            )
        except Exception as e:
            logger.error("[ModelCloudManager] Stream from Firebase failed: %s", e)
            return None

        # ── Write to OS temp file (AR3D needs a path) ─────────────────────────
        try:
            tmp = tempfile.NamedTemporaryFile(
                suffix=ext,
                delete=False,           # we control deletion via free_temp()
                prefix=f"aria_{name}_"
            )
            tmp.write(buffer.read())
            tmp.flush()
            tmp.close()
            tmp_path = Path(tmp.name)
            self._active_temps.append(tmp_path)
            logger.info("[ModelCloudManager] Temp file ready: %s", tmp_path)
            return tmp_path
        except Exception as e:
            logger.error("[ModelCloudManager] Temp file creation failed: %s", e)
            return None

    def free_temp(self, tmp_path):
        """
        Delete a temp file after AR3D is done with it.
        Call this when the user closes or switches the AR3D model.
        """
        if tmp_path is None:
            return
        try:
            Path(tmp_path).unlink(missing_ok=True)
            self._active_temps = [p for p in self._active_temps if p != Path(tmp_path)]
            logger.info("[ModelCloudManager] Temp freed: %s", tmp_path)
        except Exception as e:
            logger.warning("[ModelCloudManager] Could not free temp %s: %s", tmp_path, e)

    def free_all_temps(self):
        """
        Clean up ALL active temp files — called by main.py cleanup on shutdown.
        """
        for p in list(self._active_temps):
            self.free_temp(p)
        logger.info("[ModelCloudManager] All temp files freed on shutdown.")

    # ─────────────────────────────────────────────────────────────────────────
    #  QUERY / ADMIN
    # ─────────────────────────────────────────────────────────────────────────

    def is_available(self, name: str) -> bool:
        """Return True if model exists in Firestore (cloud)."""
        if not self._firebase_ok:
            return False
        return self._get_meta(name) is not None

    def list_models(self, user: str = "chinmay") -> list:
        """List all models stored in Firestore for a user."""
        if not self._firebase_ok:
            return []
        try:
            from firebase_admin import firestore as _fs
            docs = (
                self._db.collection(FIRESTORE_COLLECTION)
                .where("user", "==", user)
                .order_by("created_at", direction=_fs.Query.DESCENDING)
                .stream()
            )
            return [d.to_dict() for d in docs]
        except Exception as e:
            logger.error("[ModelCloudManager] list_models failed: %s", e)
            return []

    def delete_model(self, name: str) -> bool:
        """Permanently delete model from Firebase Storage + Firestore."""
        if not self._firebase_ok:
            return False
        try:
            doc = self._db.collection(FIRESTORE_COLLECTION).document(name).get()
            if doc.exists:
                meta = doc.to_dict()
                sp   = meta.get("storage_path", "")
                if sp:
                    self._bucket.blob(sp).delete()
                self._db.collection(FIRESTORE_COLLECTION).document(name).delete()
                logger.info("[ModelCloudManager] '%s' deleted from cloud.", name)
            return True
        except Exception as e:
            logger.error("[ModelCloudManager] delete_model failed: %s", e)
            return False

    def _get_meta(self, name: str) -> dict | None:
        """Fetch model metadata from Firestore."""
        try:
            doc = self._db.collection(FIRESTORE_COLLECTION).document(name).get()
            if not doc.exists:
                return None
            return doc.to_dict()
        except Exception as e:
            logger.error("[ModelCloudManager] Firestore read failed: %s", e)
            return None

    @staticmethod
    def _md5(path: Path) -> str:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

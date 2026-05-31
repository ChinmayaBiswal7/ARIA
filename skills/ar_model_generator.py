"""
ar_model_generator.py — ARIA Advanced AR Suite
AI-powered text-to-3D model generation

Backends (in priority order):
  1. Shap-E (OpenAI, local CPU/GPU) — best quality, free
  2. TripoSR (Stability AI, local)  — fast
  3. Meshy API (cloud, needs key)   — best quality but paid
  4. Procedural fallback            — always works, no deps

Install:
  pip install shap-e          # OpenAI Shap-E
  pip install trimesh          # for .obj export

Usage:
  gen = ModelGenerator(output_dir="skills/assets/3d")
  path = gen.generate("a dragon with wings")
  # returns path to .obj file
"""

import sys
import types
import os
import socket
import threading
import time
import math
import struct

_current_generator = [None]

class PatchedTqdm:
    def __init__(self, iterable=None, *args, **kwargs):
        self.iterable = iterable
        if iterable is not None:
            self.iterator = iter(iterable)
            self.total = len(iterable) if hasattr(iterable, '__len__') else 64
        else:
            self.iterator = None
            self.total = kwargs.get('total', 64)
        self.n = 0

    def __iter__(self):
        if self.iterator is None and self.iterable is not None:
            self.iterator = iter(self.iterable)
        return self

    def __next__(self):
        if self.iterator is None:
            raise StopIteration
        try:
            val = next(self.iterator)
            self.update(1)
            return val
        except StopIteration:
            raise StopIteration

    def update(self, n=1):
        self.n += n
        pct = int(20 + (self.n / self.total) * 65)
        if _current_generator[0]:
            _current_generator[0].progress = min(85, pct)
            _current_generator[0].progress_msg = f"Generating... step {self.n}/{self.total}"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

# ── Output directory ──────────────────────────────────────────────────────────
_DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "3d")


class ModelGenerator:

    def __init__(self, output_dir=_DEFAULT_OUT, meshy_api_key=None):
        self.output_dir    = output_dir
        self.meshy_key     = meshy_api_key
        self._shap_e_ready = False
        self._generating   = False
        self.progress      = 0
        self.progress_msg  = ""
        self.generation_timed_out = False
        self.generation_completed_late = False
        self._lock         = threading.Lock()
        os.makedirs(output_dir, exist_ok=True)

        # Try importing Shap-E in background
        threading.Thread(target=self._init_shap_e, daemon=True).start()

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(self, prompt, callback=None):
        """
        Generate a 3D model from text prompt.
        Returns path to .obj file, or None on failure.
        callback(path) called when done (for async use).

        Cloud-first: if the model is already in Firebase, stream it directly
        instead of re-generating.  Zero disk after first session.
        """
        safe_name = prompt.lower().replace(" ", "_")[:40]
        out_path  = os.path.join(self.output_dir, f"{safe_name}.obj")

        # ── Cloud-first check ────────────────────────────────────────────────
        try:
            from skills.model_cloud_manager import ModelCloudManager
            mcm = ModelCloudManager()
            if mcm.is_available(safe_name):
                print(f"[ModelGen] Cloud hit for '{safe_name}' — streaming from Firebase.")
                tmp_path = mcm.stream_to_temp(safe_name)
                if tmp_path:
                    if callback:
                        callback(str(tmp_path))
                    return str(tmp_path)
                else:
                    print(f"[ModelGen] Stream failed; falling through to local generation.")
        except Exception as _e:
            print(f"[ModelGen] Cloud check skipped: {_e}")

        # ── Local cache check (only if large enough to be real) ───────────────
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
            print(f"[ModelGen] Local cache hit: {out_path}")
            if callback:
                callback(out_path)
            return out_path
        elif os.path.exists(out_path):
            print(f"[ModelGen] Cached file too small (corrupted/empty), regenerating...")
            try:
                os.remove(out_path)
            except Exception:
                pass

        def _run_with_timeout():
            self.generation_timed_out = False
            self.generation_completed_late = False
            res_holder = []
            start_t = time.time()
            
            def target():
                res = self._run_internal(prompt, out_path)
                res_holder.append(res)
                
            t = threading.Thread(target=target, name=f"ShapE-Worker-{safe_name}", daemon=True)
            t.start()
            t.join(timeout=180.0) # 3-minute timeout
            
            if t.is_alive():
                print(f"[ModelGen] TIMEOUT: Shap-E generation for '{safe_name}' took longer than 180s on CPU. Falling back to procedural.")
                self.generation_timed_out = True
                
                # Generate procedural geometry
                path = self._generate_procedural(prompt, out_path)
                if callback:
                    try:
                        callback(path, is_completed_late=False)
                    except TypeError:
                        callback(path)
                
                # Let the background thread continue running to complete and upload the model
                t.join()
                duration = time.time() - start_t
                path = res_holder[0] if res_holder else None
                if path:
                    print(f"[ModelGen] Shap-E generation actually completed for '{prompt}' in {duration:.1f}s. Saved to: {path}")
                    self.generation_completed_late = True
                    # Sync to Firebase Storage
                    try:
                        from skills.model_cloud_manager import ModelCloudManager
                        ModelCloudManager().upload_async(safe_name, path, prompt=prompt)
                    except Exception as upload_err:
                        print(f"[ModelGen] Cloud upload skipped: {upload_err}")
                    if callback:
                        try:
                            callback(path, is_completed_late=True)
                        except TypeError:
                            callback(path)
                return path
            else:
                duration = time.time() - start_t
                path = res_holder[0] if res_holder else None
                if path:
                    print(f"[ModelGen] Shap-E generation actually completed for '{prompt}' in {duration:.1f}s. Saved to: {path}")
                    # Sync to Firebase Storage
                    try:
                        from skills.model_cloud_manager import ModelCloudManager
                        ModelCloudManager().upload_async(safe_name, path, prompt=prompt)
                    except Exception as upload_err:
                        print(f"[ModelGen] Cloud upload skipped: {upload_err}")
                if callback and path:
                    try:
                        callback(path, is_completed_late=False)
                    except TypeError:
                        callback(path)
                return path

        if callback:
            threading.Thread(target=_run_with_timeout, daemon=True).start()
            return None
        else:
            return _run_with_timeout()


    def _run_internal(self, prompt, out_path):
        self._generating = True
        self.progress = 0
        self.progress_msg = "Starting..."
        try:
            # Wait up to 30s for Shap-E to be ready if it hasn't initialized yet
            if not self._shap_e_ready:
                print("[ModelGen] Waiting for Shap-E to initialize...")
                for _ in range(30):
                    time.sleep(1)
                    if self._shap_e_ready:
                        break

            path = None
            if self._shap_e_ready:
                print("[ModelGen] Selecting Shap-E backend...")
                path = self._generate_shap_e(prompt, out_path)
            
            if not path:
                print("[ModelGen] Selecting Free Models Downloader backend...")
                path = self._download_free_model(
                    prompt.lower().split()[-1], out_path)
            
            if not path:
                print("[ModelGen] Selecting Procedural Fallback backend...")
                self.progress = 50
                self.progress_msg = "Creating procedural geometry..."
                time.sleep(0.5)
                path = self._generate_procedural(prompt, out_path)
                self.progress = 100
                self.progress_msg = "Complete!"
            return path
        finally:
            self._generating = False

    # ── Shap-E Backend ────────────────────────────────────────────────────────

    def _init_shap_e(self):
        try:
            import torch
            from shap_e.diffusion.sample import sample_latents
            from shap_e.diffusion.gaussian_diffusion import diffusion_from_config
            from shap_e.models.download import load_model, load_config
            self._shap_e_ready = True
            print("[ModelGen] Shap-E ready.")
        except ImportError:
            print("[ModelGen] Shap-E not installed. "
                  "Run: pip install shap-e torch trimesh")

    def _generate_shap_e(self, prompt, out_path):
        try:
            import torch
            from shap_e.diffusion.sample import sample_latents
            from shap_e.diffusion.gaussian_diffusion import diffusion_from_config
            from shap_e.models.download import load_model, load_config
            from shap_e.util.notebooks import decode_latent_mesh

            # Increase network timeout to 5 minutes for large model downloads
            socket.setdefaulttimeout(300)

            # BEFORE SHAP-E STARTS
            self.progress = 5
            self.progress_msg = "Initializing Shap-E..."

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            print(f"[ModelGen] Generating '{prompt}' with Shap-E on {device}...")

            xm      = load_model("transmitter",    device=device)
            model   = load_model("text300M",       device=device)
            diffusion = diffusion_from_config(load_config("diffusion"))

            # AFTER MODEL LOADS
            self.progress = 15
            self.progress_msg = "Models loaded. Starting diffusion..."

            # Patch tqdm
            mock_tqdm = types.ModuleType("tqdm")
            mock_tqdm.tqdm = PatchedTqdm
            mock_tqdm_auto = types.ModuleType("tqdm.auto")
            mock_tqdm_auto.tqdm = PatchedTqdm

            old_tqdm = sys.modules.get("tqdm")
            old_tqdm_auto = sys.modules.get("tqdm.auto")

            sys.modules["tqdm"] = mock_tqdm
            sys.modules["tqdm.auto"] = mock_tqdm_auto

            # Also patch in loaded shap_e modules
            patched_modules = {}
            for name, mod in list(sys.modules.items()):
                if name.startswith("shap_e"):
                    if hasattr(mod, "tqdm") and mod.tqdm is not PatchedTqdm:
                        patched_modules[name] = mod.tqdm
                        mod.tqdm = PatchedTqdm

            _current_generator[0] = self
            self.progress = 20
            self.progress_msg = "Diffusion step 0/64..."

            try:
                latents = sample_latents(
                    batch_size=1,
                    model=model,
                    diffusion=diffusion,
                    guidance_scale=15.0,
                    model_kwargs=dict(texts=[prompt]),
                    progress=True,
                    clip_denoised=True,
                    use_fp16=True,
                    use_karras=True,
                    karras_steps=64,
                    sigma_min=1e-3,
                    sigma_max=160,
                    s_churn=0,
                )
            finally:
                # Unpatch
                if old_tqdm is not None:
                    sys.modules["tqdm"] = old_tqdm
                else:
                    sys.modules.pop("tqdm", None)

                if old_tqdm_auto is not None:
                    sys.modules["tqdm.auto"] = old_tqdm_auto
                else:
                    sys.modules.pop("tqdm.auto", None)

                for name, old_val in patched_modules.items():
                    mod = sys.modules.get(name)
                    if mod:
                        mod.tqdm = old_val
                
                _current_generator[0] = None

            # AFTER LATENTS DONE
            self.progress = 85
            self.progress_msg = "Decoding mesh..."

            mesh = decode_latent_mesh(xm, latents[0]).tri_mesh()

            # AFTER DECODING / BEFORE EXPORT
            self.progress = 95
            self.progress_msg = "Saving model..."

            import trimesh
            tm = trimesh.Trimesh(
                vertices=mesh.verts,
                faces=mesh.faces
            )
            tm.export(out_path)
            
            self.progress = 100
            self.progress_msg = "Complete!"
            print(f"[ModelGen] Shap-E saved: {out_path}")
            return out_path

        except Exception as e:
            print(f"[ModelGen] Shap-E failed: {e}")
            return None

    # ── Free Models Backend ───────────────────────────────────────────────────

    def _download_free_model(self, keyword, out_path):
        """Download free CC0 models from GitHub model pack."""
        FREE_MODELS = {
            "dragon":   "https://raw.githubusercontent.com/alecjacobson/common-3d-test-models/master/data/xyzrgb_dragon.obj",
            "bunny":    "https://raw.githubusercontent.com/alecjacobson/common-3d-test-models/master/data/stanford-bunny.obj",
            "armadillo":"https://raw.githubusercontent.com/alecjacobson/common-3d-test-models/master/data/armadillo.obj",
            "cow":      "https://raw.githubusercontent.com/alecjacobson/common-3d-test-models/master/data/cow.obj",
            "teapot":   "https://raw.githubusercontent.com/alecjacobson/common-3d-test-models/master/data/teapot.obj",
        }
        url = FREE_MODELS.get(keyword)
        if not url:
            return None
        try:
            import urllib.request
            print(f"[ModelGen] Downloading {keyword} model...")
            self.progress = 5
            self.progress_msg = "Connecting to download server..."

            def reporthook(count, block_size, total_size):
                if total_size > 0:
                    downloaded = count * block_size
                    pct = int((downloaded / total_size) * 90)
                    self.progress = min(90, pct)
                    self.progress_msg = f"Downloading {keyword}... {self.progress}%"
                else:
                    self.progress_msg = f"Downloading {keyword}... {count * block_size // 1024} KB"

            urllib.request.urlretrieve(url, out_path, reporthook=reporthook)
            self.progress = 95
            self.progress_msg = "Saving downloaded model..."
            time.sleep(0.1)
            self.progress = 100
            self.progress_msg = "Complete!"
            print(f"[ModelGen] Downloaded: {out_path}")
            return out_path
        except Exception as e:
            print(f"[ModelGen] Download failed: {e}")
            return None

    # ── Procedural Fallback ───────────────────────────────────────────────────
    # Generates simple OBJ geometry for common objects

    def _generate_procedural(self, prompt, out_path):
        prompt_lower = prompt.lower()

        if "dragon" in prompt_lower:
            data = _proc_dragon()
        elif "heart" in prompt_lower:
            data = _proc_heart()
        elif "earth" in prompt_lower or "planet" in prompt_lower:
            data = _proc_sphere(32, 32)
        elif "helmet" in prompt_lower or "iron man" in prompt_lower:
            data = _proc_helmet()
        elif "crystal" in prompt_lower or "diamond" in prompt_lower:
            data = _proc_diamond()
        elif "torus" in prompt_lower:
            data = _proc_torus(1.0, 0.35, 32, 16)
        elif "dna" in prompt_lower:
            data = _proc_dna()
        elif "solar" in prompt_lower:
            data = _proc_solar_system()
        else:
            data = _proc_sphere(16, 16)

        with open(out_path, "w") as f:
            f.write(data)

        print(f"[ModelGen] Procedural '{prompt}' saved: {out_path}")
        return out_path


# ── Procedural OBJ generators ─────────────────────────────────────────────────

def _proc_sphere(lat_steps=16, lon_steps=16, radius=1.0):
    verts, faces = [], []
    for i in range(lat_steps + 1):
        theta = math.pi * i / lat_steps
        for j in range(lon_steps + 1):
            phi = 2 * math.pi * j / lon_steps
            x = radius * math.sin(theta) * math.cos(phi)
            y = radius * math.cos(theta)
            z = radius * math.sin(theta) * math.sin(phi)
            verts.append((x, y, z))

    for i in range(lat_steps):
        for j in range(lon_steps):
            a = i * (lon_steps + 1) + j
            b = a + 1
            c = (i + 1) * (lon_steps + 1) + j
            d = c + 1
            faces.append((a+1, b+1, d+1))
            faces.append((a+1, d+1, c+1))

    return _to_obj(verts, faces)


def _proc_torus(R=1.0, r=0.35, seg_major=32, seg_minor=16):
    verts, faces = [], []
    for i in range(seg_major):
        for j in range(seg_minor):
            u = 2 * math.pi * i / seg_major
            v = 2 * math.pi * j / seg_minor
            x = (R + r * math.cos(v)) * math.cos(u)
            y = r * math.sin(v)
            z = (R + r * math.cos(v)) * math.sin(u)
            verts.append((x, y, z))

    for i in range(seg_major):
        for j in range(seg_minor):
            a = i * seg_minor + j
            b = i * seg_minor + (j + 1) % seg_minor
            c = ((i + 1) % seg_major) * seg_minor + j
            d = ((i + 1) % seg_major) * seg_minor + (j + 1) % seg_minor
            faces.append((a+1, b+1, d+1))
            faces.append((a+1, d+1, c+1))

    return _to_obj(verts, faces)


def _proc_diamond():
    verts = [
        (0, 1, 0),
        (0.6, 0.2, 0), (-0.6, 0.2, 0),
        (0, 0.2, 0.6), (0, 0.2, -0.6),
        (0.4, -0.4, 0.4), (-0.4, -0.4, 0.4),
        (0.4, -0.4, -0.4), (-0.4, -0.4, -0.4),
        (0, -1, 0),
    ]
    faces = [
        (1,2,4),(1,4,3),(1,3,5),(1,5,2),
        (2,6,4),(4,6,7),(4,7,3),(3,7,8),(3,8,5),(5,8,9),(5,9,2),(2,9,6),
        (6,10,7),(7,10,8),(8,10,9),(9,10,6),
    ]
    return _to_obj(verts, faces)


def _proc_heart():
    """Approximate heart shape using parametric surface."""
    verts, faces = [], []
    steps = 24
    for i in range(steps):
        for j in range(steps):
            u = math.pi * (2 * i / steps - 1)
            v = math.pi * (2 * j / steps - 1)
            x = math.sin(u) ** 3 * 0.8
            y = (13 * math.cos(u) - 5 * math.cos(2*u) -
                 2 * math.cos(3*u) - math.cos(4*u)) / 16 * 0.8
            z = math.sin(v) * math.sin(u) ** 2 * 0.4
            verts.append((x, y, z))

    for i in range(steps - 1):
        for j in range(steps - 1):
            a = i * steps + j
            b = a + 1
            c = (i + 1) * steps + j
            d = c + 1
            faces.append((a+1, b+1, d+1))
            faces.append((a+1, d+1, c+1))

    return _to_obj(verts, faces)


def _proc_dna():
    """Double helix DNA strand."""
    verts, faces = [], []
    steps = 60
    r = 0.8
    pitch = 0.2

    for i in range(steps):
        t = i / steps * 4 * math.pi
        # Strand A
        x1 = r * math.cos(t)
        y1 = pitch * t - 4
        z1 = r * math.sin(t)
        verts.append((x1, y1, z1))
        # Strand B (offset by π)
        x2 = r * math.cos(t + math.pi)
        y2 = pitch * t - 4
        z2 = r * math.sin(t + math.pi)
        verts.append((x2, y2, z2))

    # Connect rungs
    for i in range(steps - 1):
        a = i * 2
        b = a + 1
        c = a + 2
        d = a + 3
        faces.append((a+1, c+1, b+1))
        faces.append((b+1, c+1, d+1))

    return _to_obj(verts, faces)


def _proc_helmet():
    """Simplified Iron Man helmet shape."""
    verts = []
    steps = 20
    for i in range(steps + 1):
        theta = math.pi * i / steps
        r = 0.6 + 0.2 * math.sin(theta * 2)
        for j in range(steps + 1):
            phi = 2 * math.pi * j / steps
            x = r * math.sin(theta) * math.cos(phi)
            y = r * math.cos(theta) * 1.2
            z = r * math.sin(theta) * math.sin(phi) * 0.8
            verts.append((x, y, z))

    faces = []
    for i in range(steps):
        for j in range(steps):
            a = i * (steps+1) + j
            b = a + 1
            c = (i+1) * (steps+1) + j
            d = c + 1
            faces.append((a+1, b+1, d+1))
            faces.append((a+1, d+1, c+1))

    return _to_obj(verts, faces)


def _proc_dragon():
    """Very simplified dragon — body + wings using sphere + flat planes."""
    # Body (elongated sphere)
    verts, faces = [], []
    steps = 16
    for i in range(steps + 1):
        theta = math.pi * i / steps
        for j in range(steps + 1):
            phi = 2 * math.pi * j / steps
            x = 0.5 * math.sin(theta) * math.cos(phi)
            y = 0.5 * math.cos(theta)
            z = 1.2 * math.sin(theta) * math.sin(phi)
            verts.append((x, y, z))

    for i in range(steps):
        for j in range(steps):
            a = i*(steps+1)+j
            b = a+1
            c = (i+1)*(steps+1)+j
            d = c+1
            faces.append((a+1, b+1, d+1))
            faces.append((a+1, d+1, c+1))

    # Wing planes (simple quads)
    n = len(verts)
    verts += [(-0.5, 0.2, 0), (-1.5, 0.8, -0.3),
              (-1.5, 0.0, -0.3), (-0.5, -0.2, 0)]
    faces.append((n+1, n+2, n+3))
    faces.append((n+1, n+3, n+4))

    n = len(verts)
    verts += [(0.5, 0.2, 0), (1.5, 0.8, -0.3),
              (1.5, 0.0, -0.3), (0.5, -0.2, 0)]
    faces.append((n+1, n+2, n+3))
    faces.append((n+1, n+3, n+4))

    return _to_obj(verts, faces)


def _proc_solar_system():
    """Multiple spheres representing planets."""
    result = "# Solar system\n"
    offset = 0
    planet_data = [
        (0.4, 0, 0, 0),     # Sun (large)
        (0.08, 1.2, 0, 0),  # Mercury
        (0.12, 2.0, 0, 0),  # Venus
        (0.13, 2.8, 0, 0),  # Earth
        (0.1,  3.6, 0, 0),  # Mars
        (0.3,  5.0, 0, 0),  # Jupiter
    ]

    for r, ox, oy, oz in planet_data:
        sphere_obj = _proc_sphere(12, 12, r)
        lines = sphere_obj.strip().split("\n")
        for line in lines:
            if line.startswith("v "):
                parts = line.split()
                x = float(parts[1]) + ox
                y = float(parts[2]) + oy
                z = float(parts[3]) + oz
                result += f"v {x:.4f} {y:.4f} {z:.4f}\n"
        for line in lines:
            if line.startswith("f "):
                parts = line.split()
                a = int(parts[1]) + offset
                b = int(parts[2]) + offset
                c = int(parts[3]) + offset
                result += f"f {a} {b} {c}\n"
        vert_count = sum(1 for l in lines if l.startswith("v "))
        offset += vert_count

    return result


def _to_obj(verts, faces):
    lines = ["# Generated by ARIA ModelGenerator"]
    for v in verts:
        lines.append(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}")
    for f in faces:
        lines.append(f"f {' '.join(str(i) for i in f)}")
    return "\n".join(lines) + "\n"

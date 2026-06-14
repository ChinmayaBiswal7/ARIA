import asyncio
import fractions
import time
import threading
import numpy as np
import cv2
from av import VideoFrame
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription, RTCIceServer, RTCConfiguration

class MSSVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, fps=30, width=1920, height=1080):
        super().__init__()
        self.fps = fps
        self.width = width
        self.height = height
        self.delay = 1.0 / fps
        self._start_time = None
        print(f"[WebRTC/Track] MSSVideoTrack initialized: {self.width}x{self.height} @ {self.fps} FPS")

    def _resize_frame(self, img_np):
        h, w = img_np.shape[:2]
        aspect = w / h
        
        target_w = self.width
        target_h = self.height
        
        # Preserve native aspect ratio within bounding box
        if aspect >= (self.width / self.height):
            w_new = target_w
            h_new = int(target_w / aspect)
        else:
            h_new = target_h
            w_new = int(target_h * aspect)
            
        return cv2.resize(img_np, (w_new, h_new), interpolation=cv2.INTER_LINEAR)

    def _grab_raw_frame(self):
        # Method 1: mss
        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                sct_img = sct.grab(monitor)
                img_np = np.frombuffer(sct_img.raw, dtype=np.uint8)
                img_np = img_np.reshape((sct_img.height, sct_img.width, 4))
                img_resized = self._resize_frame(img_np)
                return cv2.cvtColor(img_resized, cv2.COLOR_BGRA2RGB)
        except Exception:
            pass

        # Method 2: PIL ImageGrab
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            if img:
                img_np = np.array(img)
                if len(img_np.shape) == 3 and img_np.shape[2] == 4:
                    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
                elif len(img_np.shape) == 3 and img_np.shape[2] == 3:
                    pass
                else:
                    raise ValueError("Unexpected shape")
                img_resized = self._resize_frame(img_np)
                return img_resized
        except Exception:
            pass

        # Method 3: PyAutoGUI
        try:
            import pyautogui
            img = pyautogui.screenshot()
            if img:
                img_np = np.array(img)
                img_resized = self._resize_frame(img_np)
                return img_resized
        except Exception:
            pass

        # Method 4: PyQt5
        try:
            from PyQt5.QtWidgets import QApplication
            import io
            from PIL import Image
            app = QApplication.instance()
            if app:
                screen = app.primaryScreen()
                if screen:
                    qpixmap = screen.grabWindow(0)
                    buf = io.BytesIO()
                    qpixmap.save(buf, "PNG")
                    buf.seek(0)
                    img = Image.open(buf)
                    img.load()
                    img_np = np.array(img)
                    if len(img_np.shape) == 3 and img_np.shape[2] == 4:
                        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
                    img_resized = self._resize_frame(img_np)
                    return img_resized
        except Exception:
            pass

        # Method 5: Text Fallback
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        cv2.putText(frame, "Screen Unavailable (Locked/Headless)", (150, 360),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3, cv2.LINE_AA)
        return frame

    async def recv(self):
        if self._start_time is None:
            self._start_time = time.time()
        
        time_base = fractions.Fraction(1, 90000)
        elapsed = time.time() - self._start_time
        pts = int(elapsed * 90000)

        # Capture with fallbacks
        img_rgb = self._grab_raw_frame()
        
        # Convert to PyAV frame
        frame = VideoFrame.from_ndarray(img_rgb, format="rgb24")
        frame.pts = pts
        frame.time_base = time_base

        # Yield control and rate-limit to target FPS
        await asyncio.sleep(self.delay)
        return frame


class AriaWebRtcStreamServer:
    def __init__(self, firestore_client):
        self.db = firestore_client
        self.running = False
        self.loop = None
        self.thread = None
        self.pc = None
        self.track = None
        self.listener = None
        self.printed_client_logs_count = 0
        print("[WebRTCStream] Server initialized.")

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        # Listen to webrtc_sessions/latest document changes in Firestore
        try:
            doc_ref = self.db.collection("webrtc_sessions").document("latest")
            self.listener = doc_ref.on_snapshot(self._on_snapshot)
            print("[WebRTCStream] Server started and listening to Firestore webrtc_sessions.")
        except Exception as e:
            print(f"[WebRTCStream] Failed to start Firestore listener: {e}")

    def stop(self):
        self.running = False
        if self.listener:
            try:
                self.listener.unsubscribe()
            except Exception:
                pass
            self.listener = None

        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._close_session(), self.loop)
            
        print("[WebRTCStream] Server stopped.")

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        except Exception as e:
            print(f"[WebRTCStream] Event loop error: {e}")
        finally:
            self.loop.close()

    def _on_snapshot(self, doc_snapshot, changes, read_time):
        for doc in doc_snapshot:
            if not doc.exists:
                continue
            data = doc.to_dict()
            status = data.get("status")
            timestamp = data.get("timestamp", 0)

            # Print client logs if they changed or were cleared
            client_logs = data.get("client_logs", [])
            if len(client_logs) < self.printed_client_logs_count:
                self.printed_client_logs_count = 0
            if len(client_logs) > self.printed_client_logs_count:
                new_logs = client_logs[self.printed_client_logs_count:]
                for log in new_logs:
                    print(f"[WebRTC/Phone] {log}")
                self.printed_client_logs_count = len(client_logs)

            # Safeguard: only process fresh updates
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._handle_status_change(status, data),
                    self.loop
                )

    async def _handle_status_change(self, status, data):
        if status == "requesting":
            print("[WebRTCStream] Received connection request from phone.")
            await self._start_session()
        elif status == "answered":
            if self.pc and self.pc.signalingState == "have-local-offer":
                print("[WebRTCStream] Received Answer SDP. Completing handshake...")
                await self._accept_answer(data.get("answer_sdp"))
        elif status == "closed":
            print("[WebRTCStream] Phone closed session. Tearing down connection.")
            await self._close_session(write_status=False)

    async def _start_session(self):
        self.printed_client_logs_count = 0
        await self._close_session(write_status=False)  # clean up any dead connections

        ice_servers = [
            RTCIceServer(urls="stun:stun.l.google.com:19302"),
            RTCIceServer(urls="stun:stun1.l.google.com:19302"),
            # TURN relay — required for campus NAT + cellular NAT traversal
            RTCIceServer(
                urls=[
                    "turn:openrelay.metered.ca:80",
                    "turn:openrelay.metered.ca:443",
                    "turns:openrelay.metered.ca:443",
                ],
                username="openrelayproject",
                credential="openrelayproject",
            ),
        ]
        config = RTCConfiguration(iceServers=ice_servers)

        self.pc = RTCPeerConnection(configuration=config)
        self.track = MSSVideoTrack()
        self.pc.addTrack(self.track)

        doc_ref = self.db.collection("webrtc_sessions").document("latest")
        pc_cands_ref = doc_ref.collection("candidates").document("pc_candidates")

        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            state = self.pc.connectionState
            print(f"[WebRTCStream] PeerConnection state changed: {state}")
            if state == "connected":
                print("[WebRTCStream] Media channel CONNECTED. Video is streaming!")
            elif state in ["failed", "closed", "disconnected"]:
                asyncio.create_task(self._close_session(write_status=True))

        @self.pc.on("icegatheringstatechange")
        def on_icegathering():
            print(f"[WebRTCStream] ICE gathering state: {self.pc.iceGatheringState}")

        @self.pc.on("iceconnectionstatechange")
        def on_iceconnection():
            print(f"[WebRTCStream] ICE connection state: {self.pc.iceConnectionState}")

        # Generate local Offer
        try:
            offer = await self.pc.createOffer()
            await self.pc.setLocalDescription(offer)

            # Gather for up to 10 seconds
            for _ in range(200):
                if self.pc.iceGatheringState == "complete":
                    break
                await asyncio.sleep(0.05)

            # --- Extract candidates directly from the SDP (aiortc embeds them there) ---
            # Filter out IPv6 — Android WebView often can't route them
            sdp_lines = self.pc.localDescription.sdp.splitlines()
            pc_candidates_from_sdp = []
            sdp_mid = None
            sdp_line_idx = -1
            mid_counter = -1
            for line in sdp_lines:
                if line.startswith("m="):
                    mid_counter += 1
                    sdp_line_idx = mid_counter
                if line.startswith("a=mid:"):
                    sdp_mid = line[6:].strip()
                if line.startswith("a=candidate:"):
                    # Skip IPv6 candidates (contain ":" in the IP field)
                    parts = line.split()
                    ip = parts[4] if len(parts) > 4 else ""
                    if ":" in ip:  # IPv6
                        continue
                    pc_candidates_from_sdp.append({
                        "candidate": line[2:],  # strip leading "a="
                        "sdpMid": sdp_mid,
                        "sdpMLineIndex": sdp_line_idx,
                    })
                    ctype = parts[7] if len(parts) > 7 else "?"
                    print(f"[WebRTCStream] ICE candidate (SDP): {ctype} {ip}:{parts[5] if len(parts)>5 else '?'}")

            print(f"[WebRTCStream] Total IPv4 candidates in SDP: {len(pc_candidates_from_sdp)}")
            if not pc_candidates_from_sdp:
                print("[WebRTCStream] WARNING: Zero IPv4 ICE candidates — check network adapter/firewall.")

            # Upload Offer SDP and PC candidates to Firestore
            doc_ref.set({
                "status": "offered",
                "offer_sdp": self.pc.localDescription.sdp,
                "timestamp": time.time()
            })
            pc_cands_ref.set({"candidates": pc_candidates_from_sdp})
            print(f"[WebRTCStream] Offer + {len(pc_candidates_from_sdp)} candidates uploaded to Firestore.")

            # Background task: apply phone's candidates when they arrive
            asyncio.create_task(self._trickle_ice_monitor(doc_ref))

        except Exception as e:
            print(f"[WebRTCStream] Offer generation failed: {e}")
            await self._close_session(write_status=True)

    async def _trickle_ice_monitor(self, doc_ref):
        """Reads phone ICE candidates from Firestore and applies them to the PC."""
        phone_cands_ref = doc_ref.collection("candidates").document("phone_candidates")
        applied_phone_count = 0
        deadline = time.time() + 15  # monitor for up to 15 seconds

        while self.pc and self.pc.connectionState not in ["connected", "failed", "closed"] and time.time() < deadline:
            await asyncio.sleep(0.5)

            # Read phone's ICE candidates and apply them
            if self.pc and self.pc.remoteDescription:
                try:
                    phone_doc = phone_cands_ref.get()
                    if phone_doc.exists:
                        phone_cands = phone_doc.to_dict().get("candidates", [])
                        new_cands = phone_cands[applied_phone_count:]
                        for cand in new_cands:
                            try:
                                from aiortc import RTCIceCandidate
                                cand_str = cand.get("candidate", "")
                                if not cand_str:
                                    continue
                                parts = cand_str.replace("candidate:", "").split()
                                ice_cand = RTCIceCandidate(
                                    foundation=parts[0],
                                    component=int(parts[1]),
                                    protocol=parts[2],
                                    priority=int(parts[3]),
                                    ip=parts[4],
                                    port=int(parts[5]),
                                    type=parts[7],
                                    sdpMid=cand.get("sdpMid"),
                                    sdpMLineIndex=cand.get("sdpMLineIndex"),
                                )
                                await self.pc.addIceCandidate(ice_cand)
                                print(f"[WebRTCStream] Applied phone ICE candidate: {parts[7]} {parts[4]}:{parts[5]}")
                                applied_phone_count += 1
                            except Exception as ce:
                                print(f"[WebRTCStream] Failed to apply phone candidate: {ce}")
                except Exception as e:
                    print(f"[WebRTCStream] Failed to read phone candidates: {e}")

        if self.pc and self.pc.connectionState == "connected":
            print("[WebRTCStream] Trickle ICE monitor exiting — connection is LIVE.")
        else:
            print(f"[WebRTCStream] Trickle ICE monitor ended. Final state: {self.pc.connectionState if self.pc else 'N/A'}")

    async def _accept_answer(self, answer_sdp):
        if not self.pc or not answer_sdp:
            return
        try:
            answer = RTCSessionDescription(sdp=answer_sdp, type="answer")
            await self.pc.setRemoteDescription(answer)
            print("[WebRTCStream] Handshake complete. Remote description set.")
        except Exception as e:
            print(f"[WebRTCStream] Failed to set remote description: {e}")
            await self._close_session(write_status=True)

    async def _close_session(self, write_status=False):
        if self.track:
            try:
                self.track.stop()
            except Exception:
                pass
            self.track = None

        if self.pc:
            try:
                await self.pc.close()
            except Exception:
                pass
            self.pc = None

        if write_status:
            try:
                doc_ref = self.db.collection("webrtc_sessions").document("latest")
                doc = doc_ref.get()
                if doc.exists and doc.to_dict().get("status") != "closed":
                    doc_ref.update({
                        "status": "closed",
                        "timestamp": time.time()
                    })
            except Exception as e:
                print(f"[WebRTCStream] Failed to write closed status: {e}")
        
        print("[WebRTCStream] Active WebRTC session terminated.")

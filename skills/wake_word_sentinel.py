import os
import time
import logging
import threading
import numpy as np
import pyaudio

logger = logging.getLogger("AriaWakeSentinel")

class AriaWakeSentinel:
    def __init__(self, model_path=r"C:\D FOLDER\Projects\AI\models\aria.onnx", system_state_provider=None, wakeword_name="aria"):
        self.model_path = model_path
        self.system_state_provider = system_state_provider
        self.wakeword_name = wakeword_name
        self.stop_event = threading.Event()
        self.last_wake_time = 0.0
        self.model = None
        self.stream = None
        self.audio_handler = None
        
        # Audio capturing constants (16kHz, Mono, 16-bit PCM required by openWakeWord)
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 16000
        self.CHUNK_SIZE = 1280  # 80ms window size

        # Safe loading: Check if model exists
        if not os.path.exists(self.model_path):
            logger.warning(f"[AriaWakeSentinel] WARNING: Wake word model '{self.model_path}' not found at startup. Running in standby warning mode.")
            return

        try:
            from openwakeword.model import Model
            self.model = Model(wakeword_models=[self.model_path], inference_framework="onnx")
            print(f"[AriaWakeSentinel] Loaded custom wake word model: {self.model_path}")
        except Exception as e:
            print(f"[AriaWakeSentinel] ERROR loading wake word model: {e}")

    def start_background_listening(self, wake_callback):
        if self.model is None:
            logger.warning("[AriaWakeSentinel] Wake sentinel loop not started because model is missing.")
            return

        self.audio_handler = pyaudio.PyAudio()
        try:
            self.stream = self.audio_handler.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                frames_per_buffer=self.CHUNK_SIZE
            )
        except Exception as e:
            print(f"[AriaWakeSentinel] Could not open audio stream: {e}")
            self.audio_handler.terminate()
            return

        print("[AriaWakeSentinel] Sentinel background listening loop started.")
        try:
            while not self.stop_event.is_set():
                # State coordination check:
                # If system is busy (speaking, thinking, transcribing, listening), skip processing
                if self.system_state_provider and self.system_state_provider():
                    time.sleep(0.1)
                    continue

                try:
                    raw_pcm = self.stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                    if not raw_pcm:
                        continue
                    audio_frame = np.frombuffer(raw_pcm, dtype=np.int16)
                    
                    # Pass directly to local ONNX matrix evaluation
                    prediction = self.model.predict(audio_frame)
                    
                    score = prediction.get(self.wakeword_name, 0.0)
                    if score is None or self.wakeword_name not in prediction:
                        # Fallback keys check
                        for k, val in prediction.items():
                            if self.wakeword_name in k:
                                score = val
                                break
                    score = score or 0.0

                    if score >= 0.60:
                        # Cooldown check
                        now = time.time()
                        if now - self.last_wake_time > 3.0:
                            print(f"[AriaWakeSentinel] Wake word detected! Score: {score:.2f}")
                            self.last_wake_time = now
                            self.model.reset()  # Clear internal sliding windows
                            wake_callback()
                except IOError:
                    # Ignore overflow or read exceptions temporarily
                    time.sleep(0.01)
                except Exception as loop_err:
                    print(f"[AriaWakeSentinel] Error in run loop step: {loop_err}")
                    time.sleep(0.1)

        except Exception as e:
            print(f"[AriaWakeSentinel] Thread exception: {e}")
        finally:
            self.cleanup()

    def stop(self):
        print("[AriaWakeSentinel] Stopping sentinel background thread...")
        self.stop_event.set()

    def cleanup(self):
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if self.audio_handler:
            try:
                self.audio_handler.terminate()
            except Exception:
                pass
            self.audio_handler = None
        print("[AriaWakeSentinel] Sentinel resources released.")

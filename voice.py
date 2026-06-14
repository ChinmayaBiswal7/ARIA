# -*- coding: utf-8 -*-
import speech_recognition as sr
import threading
import time
import os
import re
import asyncio
import edge_tts
import pygame
import requests
from skills.voice_filter import is_valid_speech_text

# --- Runtime Monkeypatch for torchaudio.backend (DeepFilterNet compatibility) ---
import sys
import types
try:
    import torchaudio.backend.common
except ModuleNotFoundError:
    try:
        import torchaudio
        if not hasattr(torchaudio, 'backend'):
            torchaudio.backend = types.ModuleType('torchaudio.backend')
            sys.modules['torchaudio.backend'] = torchaudio.backend
        
        backend_common = types.ModuleType('torchaudio.backend.common')
        from collections import namedtuple
        backend_common.AudioMetaData = namedtuple('AudioMetaData', ['sample_rate', 'num_frames', 'num_channels', 'bits_per_sample', 'encoding'])
        sys.modules['torchaudio.backend.common'] = backend_common
        torchaudio.backend.common = backend_common
    except Exception as patch_err:
        print(f"[Voice/Patch] Failed to patch torchaudio: {patch_err}")

# --- Runtime Monkeypatch for os.symlink and pathlib.Path.symlink_to on Windows to copy files if privileges are missing ---
import os
import shutil
import pathlib
if os.name == 'nt':
    try:
        original_symlink = os.symlink
        def safe_symlink(src, dst, target_is_directory=False):
            try:
                original_symlink(src, dst, target_is_directory=target_is_directory)
            except OSError as e:
                if getattr(e, 'winerror', None) == 1314:
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
                else:
                    raise
        os.symlink = safe_symlink

        original_symlink_to = pathlib.Path.symlink_to
        def safe_symlink_to(self, target, target_is_directory=False):
            try:
                original_symlink_to(self, target, target_is_directory=target_is_directory)
            except OSError as e:
                if getattr(e, 'winerror', None) == 1314:
                    if os.path.isdir(target):
                        shutil.copytree(target, self, dirs_exist_ok=True)
                    else:
                        shutil.copy2(target, self)
                else:
                    raise
        pathlib.Path.symlink_to = safe_symlink_to

        print("[Voice/Patch] Patched os.symlink and pathlib.Path.symlink_to for Windows.")
    except Exception as patch_err:
        print(f"[Voice/Patch] Failed to patch symlinks: {patch_err}")

# --- Helper Classes for Sprint A: Clean Audio Pipeline ---

class NoiseSuppressor:
    def __init__(self):
        self.model = None
        self.df_state = None
        self.rnnoise = None
        self.mode = None # "deepfilternet", "rnnoise", None
        self.bypass_realtime = False
        
        # 1. Try initializing DeepFilterNet
        try:
            from df.enhance import init_df
            self.model, self.df_state, _ = init_df()
            self.mode = "deepfilternet"
            print("[NoiseSuppressor] DeepFilterNet3 initialized successfully.")
        except Exception as e:
            print(f"[NoiseSuppressor] DeepFilterNet init failed: {e}. Trying RNNoise fallback...")
            # 2. Try initializing RNNoise
            try:
                from pyrnnoise import RNNoise
                self.rnnoise = RNNoise(sample_rate=48000)
                self.mode = "rnnoise"
                print("[NoiseSuppressor] RNNoise fallback initialized successfully.")
            except Exception as e2:
                print(f"[NoiseSuppressor] RNNoise init failed: {e2}. Noise suppression disabled.")
                self.mode = None

    def suppress(self, audio_bytes, sample_rate, is_realtime=False):
        if not self.mode or not audio_bytes:
            return audio_bytes
        if is_realtime and self.bypass_realtime:
            return audio_bytes
        try:
            import time
            import numpy as np
            
            t_start = time.perf_counter()
            enhanced_bytes = audio_bytes
            
            if self.mode == "deepfilternet":
                import torch
                from scipy.signal import resample
                from df.enhance import enhance
 
                audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                orig_len = len(audio_np)
                
                if sample_rate != 48000:
                    target_len = int(orig_len * 48000 / sample_rate)
                    audio_48k = resample(audio_np, target_len)
                else:
                    audio_48k = audio_np
                
                tensor_in = torch.from_numpy(audio_48k).unsqueeze(0)
                with torch.no_grad():
                    tensor_out = enhance(self.model, self.df_state, tensor_in)
                enhanced_48k = tensor_out.squeeze(0).cpu().numpy()
                
                if sample_rate != 48000:
                    enhanced_orig = resample(enhanced_48k, orig_len)
                else:
                    enhanced_orig = enhanced_48k
                    
                enhanced_pcm = np.clip(enhanced_orig * 32768.0, -32768, 32767).astype(np.int16)
                enhanced_bytes = enhanced_pcm.tobytes()
                latency_ms = (time.perf_counter() - t_start) * 1000
                print(f"[NoiseSuppressor] DF3 latency: {latency_ms:.1f}ms")
                if is_realtime and latency_ms > 45.0:
                    print(f"[NoiseSuppressor] Warning: Latency {latency_ms:.1f}ms exceeds real-time threshold. Auto-bypassing real-time suppression.")
                    self.bypass_realtime = True
                
            elif self.mode == "rnnoise":
                from scipy.signal import resample
                
                audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
                orig_len = len(audio_np)
                
                if sample_rate != 48000:
                    target_len = int(orig_len * 48000 / sample_rate)
                    audio_48k = resample(audio_np.astype(np.float32), target_len).astype(np.int16)
                else:
                    audio_48k = audio_np
                
                denoised_frames = []
                for _, frame in self.rnnoise.denoise_chunk(audio_48k):
                    denoised_frames.append(frame)
                
                if denoised_frames:
                    enhanced_48k = np.concatenate(denoised_frames).flatten()
                    if sample_rate != 48000:
                        enhanced_orig = resample(enhanced_48k.astype(np.float32), orig_len)
                    else:
                        enhanced_orig = enhanced_48k
                    enhanced_pcm = np.clip(enhanced_orig, -32768, 32767).astype(np.int16)
                    enhanced_bytes = enhanced_pcm.tobytes()
                
                latency_ms = (time.perf_counter() - t_start) * 1000
                print(f"[NoiseSuppressor] RNNoise latency: {latency_ms:.1f}ms")
                if is_realtime and latency_ms > 45.0:
                    print(f"[NoiseSuppressor] Warning: Latency {latency_ms:.1f}ms exceeds real-time threshold. Auto-bypassing real-time suppression.")
                    self.bypass_realtime = True
                
            return enhanced_bytes
        except Exception as e:
            print(f"[NoiseSuppressor] Error during enhancement ({self.mode}): {e}")
            return audio_bytes

class SileroVAD:
    def __init__(self, model_path="models/silero_vad.onnx"):
        self.enabled = False
        self.session = None
        self.state = None
        self.context = None
        self.sr = None
        self.buffer = None
        try:
            import onnxruntime as ort
            import numpy as np
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            self.session = ort.InferenceSession(model_path, sess_options=opts, providers=['CPUExecutionProvider'])
            self.state = np.zeros((2, 1, 128), dtype=np.float32)
            self.context = np.zeros((1, 64), dtype=np.float32)
            self.sr = np.array(16000, dtype=np.int64)
            self.buffer = np.array([], dtype=np.float32)
            self.enabled = True
            print(f"[SileroVAD] Loaded Silero VAD model from {model_path} successfully.")
        except Exception as e:
            print(f"[SileroVAD] Failed to initialize Silero VAD: {e}")

    def reset(self):
        if self.enabled:
            import numpy as np
            self.state = np.zeros((2, 1, 128), dtype=np.float32)
            self.context = np.zeros((1, 64), dtype=np.float32)
            self.buffer = np.array([], dtype=np.float32)

    def process_chunk(self, audio_np):
        if not self.enabled:
            return 0.0
        try:
            import numpy as np
            self.buffer = np.concatenate((self.buffer, audio_np.astype(np.float32)))
            max_prob = 0.0
            
            while len(self.buffer) >= 512:
                subframe = self.buffer[:512]
                self.buffer = self.buffer[512:]
                
                subframe_in = subframe[np.newaxis, :].astype(np.float32)
                # Prepend context buffer
                x = np.concatenate([self.context, subframe_in], axis=1)
                
                out, new_state = self.session.run(None, {
                    'input': x,
                    'state': self.state,
                    'sr': self.sr
                })
                self.state = new_state
                self.context = x[:, -64:]
                
                prob = out[0][0]
                if prob > max_prob:
                    max_prob = prob
            return max_prob
        except Exception as e:
            print(f"[SileroVAD] Error during inference: {e}")
            return 0.0

class SpeakerRecognizer:
    def __init__(self, model_dir="models/speechbrain_spkrec"):
        self.enabled = False
        self.classifier = None
        self.owner_voiceprint = None
        self.voiceprint_path = "models/owner_voiceprint.npy"
        
        try:
            import os
            os.makedirs(model_dir, exist_ok=True)
            from speechbrain.inference.speaker import EncoderClassifier
            self.classifier = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir=model_dir,
                run_opts={"device": "cpu"}
            )
            self.enabled = True
            print("[SpeakerRecognizer] Loaded SpeechBrain ECAPA-TDNN successfully.")
            
            if os.path.exists(self.voiceprint_path):
                import numpy as np
                self.owner_voiceprint = np.load(self.voiceprint_path)
                print("[SpeakerRecognizer] Loaded owner voiceprint successfully.")
        except Exception as e:
            print(f"[SpeakerRecognizer] Initialization failed/skipped: {e}")

    def extract_embedding(self, audio_np, sample_rate=16000):
        if not self.enabled or self.classifier is None:
            return None
        try:
            import torch
            import numpy as np
            
            audio_fp32 = audio_np.astype(np.float32)
            if np.max(np.abs(audio_fp32)) > 1.0:
                audio_fp32 = audio_fp32 / 32768.0
            
            audio_tensor = torch.from_numpy(audio_fp32).unsqueeze(0)
            
            if sample_rate != 16000:
                from scipy.signal import resample
                orig_len = len(audio_fp32)
                target_len = int(orig_len * 16000 / sample_rate)
                audio_resampled = resample(audio_fp32, target_len)
                audio_tensor = torch.from_numpy(audio_resampled).unsqueeze(0)
            
            with torch.no_grad():
                emb = self.classifier.encode_batch(audio_tensor)
                emb_np = emb.squeeze().cpu().numpy()
            return emb_np
        except Exception as e:
            print(f"[SpeakerRecognizer] Failed to extract embedding: {e}")
            return None

    def register_owner(self, audio_np, sample_rate=16000):
        emb = self.extract_embedding(audio_np, sample_rate)
        if emb is not None:
            import numpy as np
            import os
            self.owner_voiceprint = emb
            os.makedirs(os.path.dirname(self.voiceprint_path), exist_ok=True)
            np.save(self.voiceprint_path, self.owner_voiceprint)
            print("[SpeakerRecognizer] Registered owner voiceprint successfully.")
            return True
        return False

    def verify_speaker(self, audio_np, sample_rate=16000, threshold=0.70):
        if not self.enabled:
            return True, 1.0, "Owner (unverified)"
            
        if self.owner_voiceprint is None:
            return True, 1.0, "Owner (not enrolled)"
        
        emb = self.extract_embedding(audio_np, sample_rate)
        if emb is None:
            return False, 0.0, "Unknown"
        
        import numpy as np
        dot_prod = np.dot(self.owner_voiceprint, emb)
        norm_owner = np.linalg.norm(self.owner_voiceprint)
        norm_emb = np.linalg.norm(emb)
        if norm_owner == 0 or norm_emb == 0:
            return False, 0.0, "Unknown"
        
        similarity = dot_prod / (norm_owner * norm_emb)
        is_owner = similarity >= threshold
        label = "Owner" if is_owner else "Guest"
        
        print(f"[SpeakerRecognizer] Speaker verification: label={label}, similarity={similarity:.3f} (threshold={threshold})")
        return is_owner, similarity, label

# VAD Speech Ratio thresholds (0.0 to 1.0)
WAKE_VAD_THRESHOLD = 0.30
CONVERSATION_VAD_THRESHOLD = 0.25

class Voice:
    def __init__(self):
        self.aria = None
        self._init_tts()
        self._cleanup_temp_files()
        self._is_speaking_lock = False
        self.noise_suppressor = NoiseSuppressor()
        try:
            import numpy as np
            dummy_bytes = np.zeros(1024, dtype=np.int16).tobytes()
            self.noise_suppressor.suppress(dummy_bytes, 16000)
            print("[Voice] NoiseSuppressor warmed up successfully.")
        except Exception as warmup_err:
            print(f"[Voice] Warmup failed: {warmup_err}")
        self.silero_vad = SileroVAD()
        self.speaker_recognizer = SpeakerRecognizer()
        self.listening_active = threading.Event()
        self.last_speaker_verified = True
        self.last_speaker_similarity = 1.0
        self.last_speaker_label = "Owner (unverified)"
        self.local_whisper = None
        try:
            from faster_whisper import WhisperModel
            self.local_whisper = WhisperModel("base", device="cpu", compute_type="int8")
            print("[Voice] Local faster-whisper (base) model loaded successfully.")
        except Exception as e:
            print(f"[Voice] Failed to load local faster-whisper model: {e}")
        self.recording_active = False
        self.vad_detecting_speech = False
        self.speech_start_time = 0.0
        self.on_speech_detected = None
        self._shutting_down = False
        self.interrupted_transcription = None
        self.barge_in_ducking_enabled = True
        self.barge_in_ducking_ratio = 0.70
        self.barge_in_consecutive_frames_threshold = 6

        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 1.2        # Snappy silence timeout
        self.recognizer.energy_threshold = 200       # Lower base threshold
        self.recognizer.dynamic_energy_threshold = False # Disable dynamic (prevents hanging)
        self.energy_rms_threshold = 300              # Lower initial base RMS threshold
        self.mic_lock = threading.Lock()
        self.microphone = None
        self._init_mic()
        self.noise_profile = None
        self.noise_floor = None
        self.last_validated_text = ""
        threading.Thread(target=self.calibrate_noise_profile, args=(1.0,), daemon=True).start()

        
        # Multi-language support properties
        self.current_language = "en"
        self.english_turns_count = 0
        self.available_voices = []
        self._load_available_voices()
        from wake_word import WakeWordDetector
        self.wake_word_detector = WakeWordDetector()
        self.wake_word_detector.set_transcriber(self.whisper_transcribe)
        self.wake_detector = self.wake_word_detector
        from skills.voice_emotion_analyzer import VoiceEmotionAnalyzer
        self.voice_analyzer = VoiceEmotionAnalyzer()
        self.last_voice_emotion = None
        self.last_voice_emotion_time = 0.0
        
        # Audio & STT quality/confidence tracking
        self.last_speech_ratio = 0.0
        self.last_avg_logprob = None
        self.last_no_speech_prob = None

    @property
    def is_speaking(self):
        return self._is_speaking_lock or bool(pygame.mixer.get_init() and pygame.mixer.music.get_busy())

    @property
    def is_user_actively_speaking(self):
        if not self.vad_detecting_speech:
            return False
        import time as pytime
        duration = pytime.time() - getattr(self, "speech_start_time", 0.0)
        return duration >= 0.3

    def stop_playback(self):
        try:
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
                try:
                    pygame.mixer.music.unload()
                except Exception:
                    pass
        except Exception as e:
            print(f"[Voice] Error stopping playback: {e}")
        self._is_speaking_lock = False

    def is_valid_speech(self, text, active_conversation=False):
        # Apply mid-sentence corrections first
        text = self.handle_mid_sentence_corrections(text)
        
        txt_clean = (text or "").strip().lower().replace(".", "").replace("!", "").replace("?", "")
        words = txt_clean.split()
        
        avg_logprob = getattr(self, 'last_avg_logprob', None)
        no_speech_prob = getattr(self, 'last_no_speech_prob', None)

        avg_token_confidence = 1.0
        if avg_logprob is not None:
            import math
            try:
                avg_token_confidence = math.exp(avg_logprob)
            except Exception:
                avg_token_confidence = 1.0
        if no_speech_prob is not None:
            avg_token_confidence *= (1.0 - no_speech_prob)

        avg_logprob_str = f"{avg_logprob:.3f}" if avg_logprob is not None else "None"
        no_speech_prob_str = f"{no_speech_prob:.3f}" if no_speech_prob is not None else "None"
        print(f"[Voice/ConfidenceRouting] Confidence: {avg_token_confidence:.2f} (avg_logprob: {avg_logprob_str}, no_speech_prob: {no_speech_prob_str})")

        # 1. Confidence Routing & Target Confirmation
        critical_words = {"delete", "shutdown", "close", "clear", "stop", "exit"}
        is_critical = any(w in txt_clean for w in critical_words)

        # Dynamic confidence threshold based on utterance length:
        # Require stricter confidence (0.60) for short phrases (1-2 words) to filter out ambient noise.
        # Allow lower confidence (0.45) for longer sentences (3+ words) to prevent rejecting valid speech.
        confidence_threshold = 0.60 if len(words) < 3 else 0.45

        if avg_token_confidence < 0.35:
            print(f"[Voice/ConfidenceRouting] Confidence {avg_token_confidence:.2f} < 0.35. Rejecting silently (likely noise/ambient).")
            return False
        elif 0.35 <= avg_token_confidence < confidence_threshold:
            print(f"[Voice/ConfidenceRouting] Borderline confidence {avg_token_confidence:.2f} (0.35-{confidence_threshold}). Asking for repeat.")
            self.speak("I didn't quite catch that. Could you please repeat?")
            return False
        
        elif confidence_threshold <= avg_token_confidence < 0.80:
            if is_critical:
                print(f"[Voice/ConfidenceRouting] Critical command detected with confidence {avg_token_confidence:.2f}. Triggering confirmation flow.")
                self.speak(f"Did you say: {text}?")
                confirm_response = self.listen(timeout=4, phrase_time_limit=4, active_conversation=True)
                if confirm_response:
                    confirm_clean = confirm_response.strip().lower().replace(".", "").replace("!", "").replace("?", "")
                    yes_words = {"yes", "yeah", "yup", "sure", "correct", "confirm", "yep", "right"}
                    if any(w in confirm_clean for w in yes_words):
                        print(f"[Voice/ConfidenceRouting] Confirmation YES received: '{confirm_response}'. Proceeding with '{text}'")
                    else:
                        print(f"[Voice/ConfidenceRouting] Confirmation NO/invalid received: '{confirm_response}'. Rejecting '{text}'")
                        self.speak("Okay, let's try again.")
                        return False
                else:
                    print("[Voice/ConfidenceRouting] Confirmation timeout. Rejecting.")
                    return False
            else:
                print(f"[Voice/ConfidenceRouting] Non-critical command '{text}' accepted directly in 0.6-0.8 range.")

        # Let the standard checks evaluate the final accepted text
        valid, reason = is_valid_speech_text(text, active_conversation=active_conversation)
        self.last_validated_text = text
        if valid:
            print(f"[STT Verification] ACCEPTED: '{text}' (reason: {reason})")
            return True
            
        print(f"[STT Verification] REJECTED: '{text}' (reason: {reason})")
        return False

    def handle_mid_sentence_corrections(self, text):
        if not text:
            return text
        text_lower = text.lower()
        correction_triggers = ["actually no", "actually", "no wait", "scratch that", "correction"]
        for trigger in correction_triggers:
            if trigger in text_lower:
                idx = text_lower.rfind(trigger)
                corrected_text = text[idx + len(trigger):].strip()
                corrected_text = re.sub(r'^[,\.\s\?\!]+', '', corrected_text).strip()
                if corrected_text:
                    print(f"[Voice/Correction] Corrected mid-sentence: '{text}' -> '{corrected_text}'")
                    return corrected_text
        return text

            
    def denoise_audio(self, audio_data):
        try:
            import time
            import noisereduce as nr
            import numpy as np
            
            t0 = time.time()
            raw_bytes = audio_data.get_raw_data()
            audio_np = np.frombuffer(raw_bytes, dtype=np.int16)
            
            if hasattr(self, 'noise_profile') and self.noise_profile is not None:
                denoised_np = nr.reduce_noise(y=audio_np.astype(np.float32), sr=audio_data.sample_rate, y_noise=self.noise_profile)
            else:
                denoised_np = nr.reduce_noise(y=audio_np.astype(np.float32), sr=audio_data.sample_rate)
            denoised_np = np.clip(denoised_np, -32768, 32767).astype(np.int16)
            
            print(f'[Voice/Denoise] Spectral noise reduction completed in {(time.time() - t0)*1000:.1f}ms')
            return sr.AudioData(denoised_np.tobytes(), audio_data.sample_rate, audio_data.sample_width)
        except Exception:
            return audio_data

    def is_loud_enough(self, audio_data, threshold=None):
        if threshold is None:
            threshold = self.energy_rms_threshold
            
        try:
            import numpy as np
            raw_bytes = audio_data.get_raw_data()
            audio_np = np.frombuffer(raw_bytes, dtype=np.int16)
            if len(audio_np) == 0:
                self.last_audio_rms = 0
                return False
            rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2))
            self.last_audio_rms = rms
            print(f'[Voice/EnergyGate] Captured audio RMS: {rms:.1f} (Threshold: {threshold})')
            return rms > threshold
        except Exception as e:
            self.last_audio_rms = None
            print(f'[Voice/EnergyGate] Error calculating audio energy: {e}')
            return True
            
    def is_human_speech(self, audio_data, mode=None, min_ratio=None, active_conversation=False):
        if mode is None:
            mode = 2 if active_conversation else 3
        if min_ratio is None:
            min_ratio = CONVERSATION_VAD_THRESHOLD if active_conversation else WAKE_VAD_THRESHOLD

        try:
            import webrtcvad
            import numpy as np

            raw_bytes = audio_data.get_raw_data()
            sample_rate = audio_data.sample_rate
            VAD_RATE = 16000

            audio_np = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)

            if sample_rate != VAD_RATE:
                orig_len = len(audio_np)
                target_len = int(orig_len * VAD_RATE / sample_rate)
                if target_len < 1:
                    return False
                indices = np.linspace(0, orig_len - 1, target_len)
                audio_np = np.interp(indices, np.arange(orig_len), audio_np)

            audio_np = np.clip(audio_np, -32768, 32767).astype(np.int16)
            resampled_bytes = audio_np.tobytes()

            vad = webrtcvad.Vad()
            vad.set_mode(mode)

            frame_ms = 30
            samples_per_frame = int(VAD_RATE * frame_ms / 1000)
            frame_size = samples_per_frame * 2

            speech_frames = 0
            total_frames = 0

            for i in range(0, len(resampled_bytes) - frame_size + 1, frame_size):
                frame = resampled_bytes[i : i + frame_size]
                if len(frame) != frame_size:
                    continue
                total_frames += 1
                try:
                    if vad.is_speech(frame, VAD_RATE):
                        speech_frames += 1
                except Exception:
                    pass

            speech_ratio = speech_frames / total_frames if total_frames > 0 else 0.0

            silero_prob = 0.0
            if self.silero_vad.enabled:
                try:
                    self.silero_vad.reset()
                    audio_fp32 = audio_np.astype(np.float32) / 32768.0
                    probs = []
                    for offset in range(0, len(audio_fp32), 512):
                        chunk = audio_fp32[offset : offset + 512]
                        if len(chunk) < 512:
                            chunk = np.pad(chunk, (0, 512 - len(chunk)))
                        prob = self.silero_vad.process_chunk(chunk)
                        probs.append(prob)
                    silero_prob = max(probs) if probs else 0.0
                except Exception as silero_err:
                    print(f"[Voice/VAD] Silero post-rec error: {silero_err}")

            if total_frames == 0:
                self.last_speech_frames = 0
                self.last_total_frames = 0
                return False

            self.last_speech_frames = speech_frames
            self.last_total_frames = total_frames
            self.last_speech_ratio = speech_ratio

            print(f'[Voice/VAD] Post-rec WebRTC ratio: {speech_ratio*100:.1f}% (Threshold: {min_ratio*100:.1f}%), Silero max prob: {silero_prob:.3f}')

            is_speech_detected = (speech_ratio >= min_ratio and speech_frames >= 5) or silero_prob > 0.85
            if is_speech_detected and hasattr(self, 'on_speech_detected') and self.on_speech_detected:
                self.on_speech_detected()
            return is_speech_detected

        except Exception as e:
            self.last_speech_frames = None
            self.last_total_frames = None
            print(f'[Voice/VAD] Post-rec VAD error: {e}')
            return True

    def _load_groq_key(self):
        if os.environ.get('GROQ_API_KEY'):
            return os.environ.get('GROQ_API_KEY').strip()
        path = 'groq_api_key.txt'
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception:
                pass
        return None

    def _load_elevenlabs_key(self):
        if os.environ.get('ELEVENLABS_API_KEY'):
            return os.environ.get('ELEVENLABS_API_KEY').strip()
        path = 'elevenlabs_api_key.txt'
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception:
                pass
        return None

    def _cleanup_temp_files(self):
        for f in os.listdir('.'):
            if f.startswith('speech_') and f.endswith('.mp3'):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def _init_tts(self):
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
            self.voice_model = 'en-US-AriaNeural'
            print('[Voice] Pygame audio mixer initialized successfully.')
        except Exception as e:
            print(f'[Voice] Audio Mixer Init Error: {e}')

    def _load_available_voices(self):
        def _load():
            try:
                voices = asyncio.run(edge_tts.list_voices())
                self.available_voices = [v['ShortName'] for v in voices]
                print(f"[Voice] Loaded {len(self.available_voices)} available Edge-TTS voices (async).")
            except Exception as e:
                print(f"[Voice] Error loading available Edge-TTS voices: {e}")
                self.available_voices = []
        threading.Thread(target=_load, daemon=True).start()


    def _get_windows_volume(self):
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            return int(volume.GetMasterVolumeLevelScalar() * 100)
        except Exception:
            return None

    def _init_mic(self):
        try:
            self.microphone = sr.Microphone()
            print('[Voice] Microphone ready.')
        except Exception as e:
            print(f'[Voice] Microphone init error: {e}')
            self.microphone = None

    def calibrate_noise_profile(self, duration_seconds=1.0):
        if not self.microphone:
            return
        import numpy as np
        print('[Voice] Calibrating noise profile — please stay silent...')
        try:
            with self.mic_lock, self.microphone as source:
                sample_rate = source.SAMPLE_RATE
                frame_ms = 30
                source_samples = int(sample_rate * frame_ms / 1000)
                frames = []
                num_frames = int(duration_seconds * 1000 / frame_ms)
                for _ in range(num_frames):
                    try:
                        chunk = source.stream.read(source_samples)
                        if chunk:
                            frames.append(np.frombuffer(chunk, dtype=np.int16))
                    except IOError:
                        pass
                if frames:
                    all_frames = np.concatenate(frames).astype(np.float32)
                    self.noise_profile = all_frames
                    noise_rms = np.sqrt(np.mean(all_frames ** 2))
                    # Multiply noise RMS by 1.8, but clamp it between 35 and 800 to prevent extreme settings
                    self.energy_rms_threshold = max(35, min(800, int(noise_rms * 1.8)))
                    print(f'[Voice] Noise profile calibrated successfully ({len(self.noise_profile)} samples).')
                    print(f'[Voice] Dynamic energy threshold set to: {self.energy_rms_threshold} (Noise RMS: {noise_rms:.1f})')
                else:
                    print('[Voice] Calibration warning: No frames captured. Using default energy threshold of 300.')
                    self.energy_rms_threshold = 300
        except Exception as e:
            print(f'[Voice] Noise calibration skipped: {e}')

    def speak(self, text, block=True, allow_barge_in=True):
        if not text:
            return
        self._is_speaking_lock = True
        try:
            # Clean up old temporary speech files to prevent storage accumulation
            try:
                import os
                for f in os.listdir('.'):
                    if (f.startswith('speech_') and (f.endswith('.mp3') or f.endswith('.wav'))) or f == 'speech.wav':
                        try:
                            os.remove(f)
                        except OSError:
                            pass
            except Exception as clean_err:
                print(f"[Voice] Error cleaning up old speech files: {clean_err}")

            clean = text
            for char in ['*', '#', '_', '', '~', '•', '—', '|']:
                clean = clean.replace(char, '')
            import re
            clean = re.sub(r'\[(?:OPEN|CLOSE|TYPE|SEARCH|SCREENSHOT|VOLUME|SHUTDOWN|RESTART):[^\]]*\]', '', clean)
            clean = re.sub(r'\[(?:SCREENSHOT|SHUTDOWN|RESTART)\]', '', clean)
            clean = clean.strip()
            if not clean:
                return

            # Log TTS configuration parameters
            tts_engine = "Edge-TTS"
            eleven_key = self._load_elevenlabs_key()
            if eleven_key:
                tts_engine = "ElevenLabs"
            
            try:
                current_vol = int(pygame.mixer.music.get_volume() * 100)
            except Exception:
                current_vol = 100
                
            print(f"[TTS Engine] {tts_engine}")
            print(f"[Voice Name] {self.voice_model if tts_engine == 'Edge-TTS' else 'ElevenLabs/21m00Tcm4TlvDq8ikWAM'}")
            print(f"[Rate] +0%")
            print(f"[Pitch] +0Hz")
            print(f"[Volume] {current_vol}")
            print(f"[Output Device] Default Speaker")
            win_vol = self._get_windows_volume()
            win_vol_str = f"{win_vol}%" if win_vol is not None else "N/A (pycaw error or not supported)"
            print(f"[Windows Master Volume] {win_vol_str}")
            print(f"[pygame Mixer Volume] {current_vol}%")
            print(f"[TTS Text Length] {len(clean)} chars")

            try:
                print(f'[ARIA]: {clean}')
            except UnicodeEncodeError:
                print(f'[ARIA]: {clean.encode("ascii", "backslashreplace").decode("ascii")}')
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
                try:
                    pygame.mixer.music.unload()
                except AttributeError:
                    pass
            output_file = 'speech.mp3'
            try:
                if os.path.exists(output_file):
                    os.remove(output_file)
            except OSError:
                output_file = f'speech_{int(time.time())}.mp3'
            generated = False
            eleven_key = self._load_elevenlabs_key()
            if eleven_key:
                try:
                    print('[Voice] Synthesizing speech via ElevenLabs...')
                    url = 'https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM'
                    headers = {
                        'Accept': 'audio/mpeg',
                        'Content-Type': 'application/json',
                        'xi-api-key': eleven_key
                    }
                    payload = {
                        'text': clean,
                        'model_id': 'eleven_monolingual_v1',
                        'voice_settings': {
                            'stability': 0.5,
                            'similarity_boost': 0.75
                        }
                    }
                    res = requests.post(url, json=payload, headers=headers, timeout=12)
                    if res.status_code == 200:
                        with open(output_file, 'wb') as f:
                            f.write(res.content)
                        generated = True
                    else:
                        print(f'[Voice/ElevenLabs] Error {res.status_code}: {res.text}. Falling back to Edge-TTS.')
                except Exception as e:
                    print(f'[Voice/ElevenLabs] Failed: {e}. Falling back to Edge-TTS.')
            if not generated:
                try:
                    # Switch the voice model dynamically based on self.current_language
                    # Switch the voice model dynamically based on text script rather than just self.current_language
                    is_clean_ascii = False
                    if clean:
                        try:
                            clean.encode('ascii')
                            is_clean_ascii = True
                        except UnicodeEncodeError:
                            is_clean_ascii = False
                            
                    current_lang = getattr(self, "current_language", "en")
                    if is_clean_ascii:
                        current_lang = "en"
                    else:
                        if re.search(r"[\u0900-\u097F]", clean):
                            current_lang = "hi"
                        elif re.search(r"[\u0B00-\u0B7F]", clean):
                            current_lang = "or"

                    if current_lang == "hi":
                        if "hi-IN-MadhuramNeural" in self.available_voices:
                            self.voice_model = "hi-IN-MadhuramNeural"
                        elif "hi-IN-SwaraNeural" in self.available_voices:
                            self.voice_model = "hi-IN-SwaraNeural"
                        else:
                            hi_voices = [v for v in self.available_voices if "hi-IN" in v]
                            self.voice_model = hi_voices[0] if hi_voices else "hi-IN-MadhuramNeural"
                    elif current_lang == "or":
                        if "or-IN-OdiaNeural" in self.available_voices:
                            self.voice_model = "or-IN-OdiaNeural"
                        elif "or-IN-SukanyaNeural" in self.available_voices:
                            self.voice_model = "or-IN-SukanyaNeural"
                        else:
                            print("[Voice/LanguageFallback] Odia voice not available in Edge-TTS. Falling back to Hindi.")
                            if "hi-IN-MadhuramNeural" in self.available_voices:
                                self.voice_model = "hi-IN-MadhuramNeural"
                            elif "hi-IN-SwaraNeural" in self.available_voices:
                                self.voice_model = "hi-IN-SwaraNeural"
                            else:
                                self.voice_model = "hi-IN-MadhuramNeural"
                    else:
                        self.voice_model = "en-US-AriaNeural"
                        
                    communicate = edge_tts.Communicate(clean, self.voice_model)
                    # Add a 3.0 second timeout for downloading Edge-TTS audio to avoid hanging on slow network
                    asyncio.run(asyncio.wait_for(communicate.save(output_file), timeout=3.0))
                    generated = True
                except Exception as e:
                    print(f'[Voice] Edge-TTS generation error: {repr(e)}. Falling back to offline local TTS (pyttsx3)...')
                    try:
                        if os.path.exists(output_file):
                            os.remove(output_file)
                    except OSError:
                        pass
                    try:
                        import pyttsx3
                        engine = pyttsx3.init()
                        
                        # Attempt to set a local female voice for the offline fallback (e.g. Microsoft Zira)
                        try:
                            voices = engine.getProperty('voices')
                            female_voice = None
                            for v in voices:
                                name_lower = v.name.lower()
                                if any(x in name_lower for x in ["zira", "female", "hazel", "heera", "haruka", "elsa", "susan"]):
                                    female_voice = v.id
                                    break
                            if female_voice:
                                engine.setProperty('voice', female_voice)
                        except Exception as voice_select_err:
                            print(f"[Voice] Error setting female fallback voice: {voice_select_err}")

                        try:
                            pytts_voice_id = engine.getProperty('voice')
                            pytts_voice = pytts_voice_id
                            voices = engine.getProperty('voices')
                            for v in voices:
                                if v.id == pytts_voice_id:
                                    pytts_voice = v.name
                                    break
                            pytts_rate = engine.getProperty('rate')
                            pytts_vol = int(engine.getProperty('volume') * 100)
                        except Exception:
                            pytts_voice = "default"
                            pytts_rate = "default"
                            pytts_vol = 100
                            
                        print(f"[TTS Engine] pyttsx3 (Fallback)")
                        print(f"[Voice Name] {pytts_voice}")
                        print(f"[Rate] {pytts_rate}")
                        print(f"[Pitch] Default")
                        print(f"[Volume] {pytts_vol}")
                        print(f"[Output Device] Default Speaker")

                        # Save local voice output to the audio file so we can run it through pygame and support barge-in
                        # Use a .wav file extension as pyttsx3 is most reliable with WAV on Windows
                        if output_file.endswith('.mp3'):
                            output_file = output_file.replace('.mp3', '.wav')
                        
                        engine.save_to_file(clean, output_file)
                        engine.runAndWait()
                        try:
                            del engine
                        except Exception:
                            pass
                        generated = True
                        print(f"[Voice] Local pyttsx3 saved fallback audio to: {output_file}")
                    except Exception as pytts_err:
                        print(f'[Voice] Local pyttsx3 fallback file save failed: {pytts_err}. Trying direct speak...')
                        try:
                            engine.say(clean)
                            if block:
                                engine.runAndWait()
                            else:
                                def run_tts():
                                    try:
                                        engine.runAndWait()
                                    except Exception:
                                        pass
                                threading.Thread(target=run_tts, daemon=True).start()
                            try:
                                del engine
                            except Exception:
                                pass
                            self._is_speaking_lock = False
                            return
                        except Exception as direct_err:
                            print(f"[Voice] Local pyttsx3 direct speak failed: {direct_err}")
                            try:
                                del engine
                            except Exception:
                                pass
                            self._is_speaking_lock = False
                            return
            interrupted = False
            try:
                # Log generated speech file size
                try:
                    speech_size = os.path.getsize(output_file)
                    speech_size_kb = f"{speech_size / 1024:.1f} KB"
                except Exception:
                    speech_size_kb = "N/A"
                print(f"[Generated Speech Size] {speech_size_kb}")
                
                if self.is_user_actively_speaking:
                    print("[Voice] User is actively speaking. Discarding response before playback starts.")
                    self.stop_playback()
                    return True

                print(f"[TTS] Audio playback starting: {output_file}")
                pygame.mixer.music.load(output_file)
                
                print("[TTS Telemetry] Mixer Init before play:", pygame.mixer.get_init())
                print("[TTS Telemetry] Mixer Busy before play:", pygame.mixer.music.get_busy())
                
                pygame.mixer.music.play()
                print("[TTS] Audio playback triggered successfully")
                
                print("[TTS Telemetry] Mixer Busy immediately after play:", pygame.mixer.music.get_busy())
                time.sleep(0.1)  # Allow audio hardware buffer initialization
                print("[TTS Telemetry] Mixer Busy 100ms after play:", pygame.mixer.music.get_busy())
                if block:
                    if allow_barge_in:
                        interrupted = self._monitor_mic_during_speech(clean)
                    else:
                        # Wait for playback to finish naturally without VAD monitoring or ducking
                        while pygame.mixer.music.get_busy():
                            time.sleep(0.05)
                        print("[TTS] Audio playback finished naturally")
                        interrupted = False
            except Exception as e:
                print(f'[Voice] Audio playback Error: {e}')
            return interrupted
        finally:
            self._is_speaking_lock = False

    def _monitor_mic_during_speech(self, spoken_text):
        if not self.microphone:
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            return False

        t_start = time.time()
        # Wait a short moment (e.g. 0.3s) for the audio playback to actually start and stabilize
        while pygame.mixer.music.get_busy() and (time.time() - t_start) < 0.3:
            time.sleep(0.05)

        if not pygame.mixer.music.get_busy():
            return False

        import numpy as np
        try:
            import webrtcvad
            vad = webrtcvad.Vad(3)
        except ImportError:
            vad = None

        interrupted = False
        recorded_audio = None
        original_volume = None
        
        try:
            with self.mic_lock, self.microphone as source:
                sample_rate = source.SAMPLE_RATE
                sample_width = source.SAMPLE_WIDTH
                vad_rate = 16000
                vad_frame_ms = 30
                vad_samples = int(vad_rate * vad_frame_ms / 1000)
                source_samples = int(sample_rate * vad_frame_ms / 1000)
                
                # Duck volume slightly to avoid echo/feedback bleed if enabled
                original_volume = pygame.mixer.music.get_volume()
                print(f"[Voice/Interrupt] [Telemetry] Volume before ducking: {original_volume:.2f}")
                if getattr(self, "barge_in_ducking_enabled", True):
                    duck_ratio = getattr(self, "barge_in_ducking_ratio", 0.70)
                    ducked_volume = original_volume * duck_ratio
                    print(f"[Voice/Interrupt] Ducking volume from {original_volume:.2f} to {ducked_volume:.2f} (ratio: {duck_ratio:.2f})")
                    pygame.mixer.music.set_volume(ducked_volume)
                    print(f"[Voice/Interrupt] [Telemetry] Volume after ducking: {pygame.mixer.music.get_volume():.2f}")
                else:
                    print(f"[Voice/Interrupt] Volume ducking disabled. Keeping volume at {original_volume:.2f}")
                
                # Energy threshold for interruption is slightly higher than baseline
                interrupt_threshold = max(self.energy_rms_threshold * 1.3, 350)
                
                frames = []
                consecutive_speech = 0
                required_speech_frames = getattr(self, "barge_in_consecutive_frames_threshold", 6)  # Default 6 frames (~180ms) to ignore quick transient noise
                
                speech_detected = False
                silence_frames_after_speech = 0
                max_silence_frames = int(1.0 / (vad_frame_ms / 1000.0))  # 1.0s of silence to stop recording
                max_recording_time = 6.0  # Max 6 seconds of recording for barge-in
                
                record_start_time = None
                
                while True:
                    music_playing = pygame.mixer.music.get_busy()
                    
                    # If music stopped naturally and we haven't detected speech, we are done
                    if not music_playing and not speech_detected:
                        break
                        
                    # If we have been recording for too long, break
                    if record_start_time and (time.time() - record_start_time) > max_recording_time:
                        break
                        
                    try:
                        raw_bytes = source.stream.read(source_samples)
                        if not raw_bytes:
                            time.sleep(0.01)
                            continue
                            
                        audio_np = np.frombuffer(raw_bytes, dtype=np.int16)
                        if len(audio_np) == 0:
                            continue
                            
                        rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2))
                        
                        # Run VAD check
                        is_speech_webrtc = False
                        if vad:
                            if sample_rate != vad_rate:
                                orig_len = len(audio_np)
                                target_len = int(orig_len * vad_rate / sample_rate)
                                if target_len > 0:
                                    indices = np.linspace(0, orig_len - 1, target_len)
                                    resampled_np = np.interp(indices, np.arange(orig_len), audio_np.astype(np.float32))
                                    resampled_np = np.clip(resampled_np, -32768, 32767).astype(np.int16)
                                    vad_bytes = resampled_np.tobytes()
                                else:
                                    vad_bytes = b''
                            else:
                                vad_bytes = raw_bytes
                                
                            if len(vad_bytes) >= vad_samples * 2:
                                try:
                                    is_speech_webrtc = vad.is_speech(vad_bytes[:vad_samples * 2], vad_rate)
                                except Exception:
                                    pass
                        else:
                            is_speech_webrtc = rms > interrupt_threshold

                        # Run Silero VAD Check
                        silero_prob = 0.0
                        if self.silero_vad.enabled:
                            try:
                                clean_np_32 = audio_np.astype(np.float32) / 32768.0
                                if sample_rate != 16000:
                                    orig_len = len(clean_np_32)
                                    target_len = int(orig_len * 16000 / sample_rate)
                                    indices = np.linspace(0, orig_len - 1, target_len)
                                    clean_16k_32 = np.interp(indices, np.arange(orig_len), clean_np_32)
                                else:
                                    clean_16k_32 = clean_np_32
                                silero_prob = self.silero_vad.process_chunk(clean_16k_32)
                            except Exception:
                                pass

                        is_speech = is_speech_webrtc or silero_prob > 0.4

                        if is_speech:
                            if not speech_detected:
                                consecutive_speech += 1
                                current_speech_duration = consecutive_speech * 0.030
                                
                                # Check if interruption is allowed (stricter rules to block echo self-triggers)
                                if self.silero_vad.enabled:
                                    interrupt_allowed = (silero_prob > 0.90 and current_speech_duration > 0.25) or (rms > interrupt_threshold * 2.0)
                                else:
                                    interrupt_allowed = (current_speech_duration > 0.25) or (rms > interrupt_threshold * 2.0)

                                if interrupt_allowed:
                                    # Interrupt triggered! Stop the music immediately
                                    print(f"[Voice/Interrupt] Voice activity interruption verified (RMS: {rms:.1f}, Silero: {silero_prob:.3f}, Duration: {current_speech_duration:.2f}s). Stopping TTS.")
                                    pygame.mixer.music.stop()
                                    try:
                                        pygame.mixer.music.unload()
                                    except Exception:
                                        pass
                                    speech_detected = True
                                    record_start_time = time.time()
                            else:
                                # We are in recording phase, reset silence count
                                silence_frames_after_speech = 0
                            
                            # Keep the frames
                            frames.append(raw_bytes)
                        else:
                            if not speech_detected:
                                consecutive_speech = max(0, consecutive_speech - 1)
                            else:
                                # In recording phase, count silence frames
                                silence_frames_after_speech += 1
                                frames.append(raw_bytes)
                                if silence_frames_after_speech >= max_silence_frames:
                                    print("[Voice/Interrupt] User finished speaking (silence timeout).")
                                    break
                                    
                    except IOError:
                        time.sleep(0.01)
                        
                if speech_detected and frames:
                    all_bytes = b"".join(frames)
                    recorded_audio = sr.AudioData(all_bytes, sample_rate, sample_width)
                    
        except Exception as e:
            print(f"[Voice/Interrupt] Monitoring error: {e}")
        finally:
            if original_volume is not None and getattr(self, "barge_in_ducking_enabled", True):
                try:
                    pygame.mixer.music.set_volume(original_volume)
                    print(f"[Voice/Interrupt] Restored volume to {original_volume:.2f}")
                    print(f"[Voice/Interrupt] [Telemetry] Volume after restoration: {pygame.mixer.music.get_volume():.2f}")
                except Exception as vol_err:
                    print(f"[Voice/Interrupt] Could not restore volume: {vol_err}")
            
        # Process the recorded interrupt audio
        if recorded_audio:
            # 1. Denoise
            denoised = self.denoise_audio(recorded_audio)
            
            # 2. Check duration
            duration = len(denoised.get_raw_data()) / (denoised.sample_rate * denoised.sample_width)
            if duration >= 0.4:
                # 3. Transcribe
                transcript = self.whisper_transcribe(denoised)
                if transcript and transcript.strip():
                    txt = transcript.strip()
                    
                    # 4. Filter speaker bleed / empty
                    clean_transcript = txt.lower().replace(".", "").replace("!", "").replace("?", "").strip()
                    clean_spoken = spoken_text.lower().replace(".", "").replace("!", "").replace("?", "").strip()
                    
                    # Stop words always trigger
                    stop_words = {"stop", "wait", "hold on", "hold", "listen", "aria", "cancel", "no"}
                    words = set(clean_transcript.split())
                    has_stop_word = any(w in stop_words for w in words)
                    
                    # 5. Smart Barge-In Interruption Check (ignore low-confidence noise & prioritize keywords)
                    avg_logprob = getattr(self, "last_avg_logprob", None)
                    no_speech_prob = getattr(self, "last_no_speech_prob", None)
                    
                    is_confident = True
                    if avg_logprob is not None and avg_logprob < -0.80:
                        is_confident = False
                    if no_speech_prob is not None and no_speech_prob > 0.45:
                        is_confident = False
                        
                    # If it's low confidence, reject it unless it contains a clear stop word
                    if not is_confident and not (has_stop_word and avg_logprob is not None and avg_logprob >= -1.1):
                        print(f"[Voice/Interrupt] Rejected low-confidence interrupt transcript: '{txt}' (avg_logprob: {avg_logprob}, no_speech_prob: {no_speech_prob})")
                        interrupted = False
                    else:
                        if has_stop_word or (clean_transcript not in clean_spoken and len(clean_transcript) > 0):
                            print(f"[Voice/Interrupt] Interrupted with text: '{txt}' (avg_logprob: {avg_logprob}, no_speech_prob: {no_speech_prob})")
                            self.interrupted_transcription = txt
                            interrupted = True
                        else:
                            print(f"[Voice/Interrupt] Ignored potential speaker bleed transcript: '{txt}' (avg_logprob: {avg_logprob}, no_speech_prob: {no_speech_prob})")
                        
        if interrupted:
            return True
        return False

    def whisper_transcribe(self, audio_data):
        import numpy as np
        if isinstance(audio_data, np.ndarray):
            audio_data = sr.AudioData(audio_data.tobytes(), 16000, 2)

        # Reset last confidence metrics
        self.last_avg_logprob = None
        self.last_no_speech_prob = None

        # Whisper debug logging
        duration = len(audio_data.get_raw_data()) / (audio_data.sample_rate * audio_data.sample_width)
        print("Sending audio to Whisper...")
        print(f"Duration: {duration:.2f}s")
        if hasattr(self, 'last_audio_rms') and self.last_audio_rms is not None:
            print(f"Audio RMS: {self.last_audio_rms:.1f}")
        if hasattr(self, 'last_speech_ratio') and self.last_speech_ratio is not None:
            print(f"Speech frames: {getattr(self, 'last_speech_frames', 0)}/{getattr(self, 'last_total_frames', 0)}")

        # 1. Try Groq API first
        groq_key = self._load_groq_key()
        if groq_key:
            try:
                wav_data = audio_data.get_wav_data()
                temp_wav = 'temp_voice.wav'
                with open(temp_wav, 'wb') as f:
                    f.write(wav_data)
                url = 'https://api.groq.com/openai/v1/audio/transcriptions'
                headers = {'Authorization': f'Bearer {groq_key}'}
                with open(temp_wav, 'rb') as f:
                    files = {
                        'file': (os.path.basename(temp_wav), f, 'audio/wav'),
                        'model': (None, 'whisper-large-v3'),
                        'response_format': (None, 'verbose_json')
                    }
                    if getattr(self, 'stt_language', None):
                        files['language'] = (None, self.stt_language)
                    res = requests.post(url, headers=headers, files=files, timeout=12)
                try:
                    os.remove(temp_wav)
                except Exception:
                    pass
                if res.status_code == 200:
                    res_data = res.json()
                    text = res_data.get('text', '').strip()
                    segments = res_data.get('segments', [])
                    avg_logprob = 0.0
                    no_speech_prob = 0.0
                    if segments:
                        avg_logprob = segments[0].get('avg_logprob', 0.0)
                        no_speech_prob = segments[0].get('no_speech_prob', 0.0)
                    
                    self.last_avg_logprob = avg_logprob
                    self.last_no_speech_prob = no_speech_prob
                    
                    # Language detection normalization
                    detected_lang_raw = str(res_data.get('language', 'en')).lower().strip()
                    detected_lang = 'en'
                    if detected_lang_raw in ('hi', 'hindi'):
                        detected_lang = 'hi'
                    elif detected_lang_raw in ('or', 'or-in', 'odia', 'oriya'):
                        detected_lang = 'or'
                    
                    # Regex fallback script checking
                    if text:
                        if re.search(r"[\u0900-\u097F]", text):
                            detected_lang = 'hi'
                        elif re.search(r"[\u0B00-\u0B7F]", text):
                            detected_lang = 'or'
                    
                    # Convert avg_logprob to probability (exp(avg_logprob))
                    lang_conf = 1.0
                    if 'language_probability' in res_data:
                        lang_conf = float(res_data['language_probability'])
                    elif avg_logprob is not None:
                        import math
                        try:
                            lang_conf = math.exp(avg_logprob)
                        except Exception:
                            lang_conf = 1.0

                    # Force English if transcribed text is purely ASCII (English script) or if language confidence is low
                    is_ascii = False
                    if text:
                        try:
                            text.encode('ascii')
                            is_ascii = True
                        except UnicodeEncodeError:
                            is_ascii = False
                            
                    if is_ascii or lang_conf < 0.80:
                        detected_lang = 'en'
                    
                    # "2 consecutive English turns" lock reset strategy
                    if detected_lang != 'en':
                        self.current_language = detected_lang
                        self.english_turns_count = 0
                    else:
                        self.english_turns_count += 1
                        if self.english_turns_count >= 2:
                            self.current_language = 'en'
                    
                    print(f"[LANG] detected={detected_lang_raw} active={self.current_language} (confidence={lang_conf:.2f}, ascii={is_ascii})")
                    print(f"[Voice/Whisper] avg_logprob: {avg_logprob:.3f}, no_speech_prob: {no_speech_prob:.3f}")
                    if text:
                        try:
                            print(f'[STT Whisper]: {text}')
                        except UnicodeEncodeError:
                            print(f'[STT Whisper]: {text.encode("ascii", "backslashreplace").decode("ascii")}')
                        return text
                else:
                    print(f'[Voice/Whisper] Whisper failed {res.status_code}. Falling back to local/Google.')
            except Exception as e:
                print(f'[Voice/Whisper] Transcription error: {e}. Falling back to local/Google.')

        # 2. Try Local faster-whisper Model
        if self.local_whisper:
            print("[Voice/Whisper] Utilizing local faster-whisper model.")
            local_text = self.whisper_transcribe_local_only(audio_data)
            if local_text:
                return local_text

        # 3. Fallback to Google STT API
        try:
            text = self.recognizer.recognize_google(audio_data)
            try:
                print(f'[STT RAW]: {text}')
            except UnicodeEncodeError:
                print(f'[STT RAW]: {text.encode("ascii", "backslashreplace").decode("ascii")}')
            
            # Apply same language detection/reset logic on fallback text
            detected_lang = 'en'
            if text:
                if re.search(r"[\u0900-\u097F]", text):
                    detected_lang = 'hi'
                elif re.search(r"[\u0B00-\u0B7F]", text):
                    detected_lang = 'or'
            
            is_ascii = False
            if text:
                try:
                    text.encode('ascii')
                    is_ascii = True
                except UnicodeEncodeError:
                    is_ascii = False
            if is_ascii:
                detected_lang = 'en'
            
            if detected_lang != 'en':
                self.current_language = detected_lang
                self.english_turns_count = 0
            else:
                self.english_turns_count += 1
                if self.english_turns_count >= 2:
                    self.current_language = 'en'
            
            print(f"[LANG] fallback_detected={detected_lang} active={self.current_language}")
            return text
        except sr.UnknownValueError:
            return ''
        except sr.RequestError as e:
            print(f'[Voice] Google STT API error: {e}')
            try:
                text = self.recognizer.recognize_sphinx(audio_data)
                try:
                    print(f'[STT Offline]: {text}')
                except UnicodeEncodeError:
                    print(f'[STT Offline]: {text.encode("ascii", "backslashreplace").decode("ascii")}')
                return text
            except:
                return ''

    def whisper_transcribe_local_only(self, audio_data, update_global_state=True):
        if not self.local_whisper:
            return ""
        try:
            import numpy as np
            import io
            import soundfile as sf
            
            wav_bytes = audio_data.get_wav_data()
            wav_stream = io.BytesIO(wav_bytes)
            audio_np, sample_rate = sf.read(wav_stream)
            audio_fp32 = audio_np.astype(np.float32)
            
            # Run transcription using local model
            segments, info = self.local_whisper.transcribe(audio_fp32, beam_size=1)
            segments = list(segments)
            text = " ".join([segment.text for segment in segments]).strip()
            
            avg_logprob = 0.0
            no_speech_prob = 0.0
            if segments:
                avg_logprob = sum(s.avg_logprob for s in segments) / len(segments)
                no_speech_prob = sum(s.no_speech_prob for s in segments) / len(segments)
            
            if update_global_state:
                self.last_avg_logprob = avg_logprob
                self.last_no_speech_prob = no_speech_prob
            
            # Language normalization logic for local model
            detected_lang = 'en'
            if info and info.language:
                detected_lang_raw = str(info.language).lower().strip()
                if detected_lang_raw in ('hi', 'hindi'):
                    detected_lang = 'hi'
                elif detected_lang_raw in ('or', 'or-in', 'odia', 'oriya'):
                    detected_lang = 'or'
            
            if text:
                if re.search(r"[\u0900-\u097F]", text):
                    detected_lang = 'hi'
                elif re.search(r"[\u0B00-\u0B7F]", text):
                    detected_lang = 'or'
                    
            is_ascii = False
            if text:
                try:
                    text.encode('ascii')
                    is_ascii = True
                except UnicodeEncodeError:
                    is_ascii = False
            
            # Convert logprob to confidence score
            import math
            lang_conf = 1.0
            if avg_logprob is not None:
                try:
                    lang_conf = math.exp(avg_logprob)
                except Exception:
                    lang_conf = 1.0
                    
            if is_ascii or lang_conf < 0.80:
                detected_lang = 'en'
                
            if detected_lang != 'en':
                self.current_language = detected_lang
                self.english_turns_count = 0
            else:
                self.english_turns_count += 1
                if self.english_turns_count >= 2:
                    self.current_language = 'en'
            
            print(f"[LANG] local_detected={info.language} active={self.current_language} (confidence={lang_conf:.2f}, ascii={is_ascii})")
            print(f"[Voice/LocalWhisper] avg_logprob: {avg_logprob:.3f}, no_speech_prob: {no_speech_prob:.3f}")
            if text:
                try:
                    print(f'[STT LocalWhisper]: {text}')
                except UnicodeEncodeError:
                    print(f'[STT LocalWhisper]: {text.encode("ascii", "backslashreplace").decode("ascii")}')
            return text
        except Exception as e:
            print(f"[Voice/LocalWhisper] Local transcription error: {e}")
            return ""

    def _record_audio_chunked(self, source, timeout=3, phrase_time_limit=5, active_conversation=False):
        print(f"[DEBUG] Entering _record_audio_chunked (timeout={timeout}, phrase_time_limit={phrase_time_limit}, active_conversation={active_conversation})")
        print(f"[DEBUG] _record_audio_chunked checks: shutting_down={getattr(self, '_shutting_down', False)}, is_speaking={self.is_speaking}")
        if getattr(self, '_shutting_down', False):
            return None
        import time as pytime
        import numpy as np
        from collections import deque
        import threading

        self.recording_active = True
        self.vad_detecting_speech = False
        self._last_record_started_speech = False
        self._last_record_live_speech_chunks = 0
        self._last_record_live_speech_subframes = 0
        self._end_of_utterance_detected = False
        self._last_streaming_text = ""

        # Yield CPU listening lock set
        if hasattr(self, 'listening_active'):
            self.listening_active.set()

        sample_rate = source.SAMPLE_RATE
        sample_width = source.SAMPLE_WIDTH

        chunk_ms = 100
        chunk_samples = int(sample_rate * chunk_ms / 1000)

        frames = []
        pre_speech_frames = deque(maxlen=max(1, int(600 / chunk_ms)))
        t_start = pytime.time()
        rms_threshold = self.energy_rms_threshold * 0.5

        started_speech = False
        speech_candidate_chunks = 0
        speech_start_time = None
        silence_start_time = None

        # VAD instance for live chunk checking
        # Two separate VAD modes:
        #   raw_vad  = Mode 3 (aggressive) on raw mic audio before DeepFilterNet
        #   clean_vad = Mode 2 (less aggressive) on DeepFilter-cleaned audio
        #   Mode 3 on cleaned audio is too restrictive — DeepFilterNet removes some
        #   lower-energy speech harmonics that WebRTC uses as speech markers.
        raw_vad = None
        clean_vad = None
        try:
            import webrtcvad
            raw_vad = webrtcvad.Vad(3)   # aggressive on raw
            clean_vad = webrtcvad.Vad(2) # relaxed on cleaned
            print(f"[Voice/ChunkedRecord] WebRTC Vad initialized. Mode: raw=3, clean=2")
        except Exception as vad_init_err:
            print(f"[Voice/ChunkedRecord] Could not initialize WebRTC Vad: {vad_init_err}")

        # Streaming STT state
        last_streaming_stt_time = 0.0
        streaming_stt_thread = None

        def run_streaming_stt_worker(audio_snapshot):
            try:
                text = self.whisper_transcribe_local_only(audio_snapshot, update_global_state=False)
                if text:
                    self._last_streaming_text = text
                    print(f"[Streaming STT] {text}")
                    
                    # Update GUI
                    try:
                        import sys
                        main_module = sys.modules.get('__main__')
                        if main_module and hasattr(main_module, 'set_text'):
                            main_module.set_text(f"Listening: \"{text}\"")
                    except Exception:
                        pass
                    
                    # End of utterance punctuation check
                    clean_txt = text.strip()
                    if clean_txt.endswith('.') or clean_txt.endswith('?') or clean_txt.endswith('!'):
                        self._end_of_utterance_detected = True
                        print("[Voice/ChunkedRecord] End-of-utterance punctuation detected.")
            except Exception as e:
                print(f"[Voice/StreamingSTT] Worker error: {e}")

        try:
            while True:
                if getattr(self, '_shutting_down', False):
                    return None
                if self.is_speaking:
                    if started_speech:
                        print("[Voice/ChunkedRecord] ARIA started speaking while user was already speaking. Stopping ARIA to prioritize user.")
                        self.stop_playback()
                    else:
                        print("[Voice/ChunkedRecord] Aborted recording because ARIA started speaking.")
                        return None

                now = pytime.time()
                if not started_speech:
                    if timeout and (now - t_start) > timeout:
                        if active_conversation:
                            print(f"[Voice/ChunkedRecord] Timeout reached ({timeout}s) before speech started. Returning None.")
                        return None
                else:
                    max_duration = 5.0 if active_conversation else 3.5
                    if (now - speech_start_time) > max_duration:
                        print(f"[Voice/ChunkedRecord] Hard-cap reached ({max_duration}s) after speech started. Breaking loop.")
                        break
                    if phrase_time_limit and (now - speech_start_time) > phrase_time_limit:
                        print(f"[Voice/ChunkedRecord] Phrase time limit reached ({phrase_time_limit}s). Breaking loop.")
                        break
                    
                    # End of utterance check: punctuation detected + >= 0.4s silence
                    if self._end_of_utterance_detected and silence_start_time is not None and (now - silence_start_time) >= 0.4:
                        print(f"[Voice/ChunkedRecord] Snappy End-of-Utterance break (silence={now - silence_start_time:.2f}s).")
                        break

                try:
                    raw_bytes = source.stream.read(chunk_samples)
                    if not raw_bytes:
                        pytime.sleep(0.01)
                        continue

                    # Denoise chunk using DeepFilterNet or RNNoise (marked as is_realtime=True)
                    denoised_bytes = self.noise_suppressor.suppress(raw_bytes, sample_rate, is_realtime=True)
                    
                    raw_audio_np = np.frombuffer(raw_bytes, dtype=np.int16)
                    audio_np = np.frombuffer(denoised_bytes, dtype=np.int16)
                    is_speech_chunk = False
                    
                    if len(audio_np) > 0:
                        # 1. RMS Energy check — use RAW audio, not DF3-cleaned audio.
                        # DF3 amplitude-suppresses silence to 0.0 which is correct,
                        # but we want the true microphone signal level for gating.
                        raw_demeaned = raw_audio_np - np.mean(raw_audio_np)
                        rms = np.sqrt(np.mean(raw_demeaned.astype(np.float32) ** 2))
                        rms_gate = rms > rms_threshold
                        
                        # 2. VAD Checks (WebRTC VAD and Silero VAD)
                        raw_webrtc = False
                        clean_webrtc = False
                        speech_subframes = 0
                        
                        if raw_vad is not None or clean_vad is not None:
                            try:
                                def run_webrtc_with(vad_inst, audio_16k_int16):
                                    res_bytes = audio_16k_int16.tobytes()
                                    frame_size = int(16000 * 0.030) * 2  # 30ms @ 16kHz = 480 samples = 960 bytes
                                    speech_frames_count = 0
                                    total_frames_count = 0
                                    for idx in range(0, len(res_bytes) - frame_size + 1, frame_size):
                                        frame = res_bytes[idx : idx + frame_size]
                                        total_frames_count += 1
                                        if vad_inst.is_speech(frame, 16000):
                                            speech_frames_count += 1
                                    return speech_frames_count > 0, speech_frames_count
                                
                                def resample_to_16k(audio_int16_np):
                                    f = audio_int16_np.astype(np.float32)
                                    if sample_rate != 16000:
                                        orig_len = len(f)
                                        target_len = int(orig_len * 16000 / sample_rate)
                                        indices = np.linspace(0, orig_len - 1, target_len)
                                        f = np.interp(indices, np.arange(orig_len), f)
                                    return np.clip(f, -32768, 32767).astype(np.int16)
                                
                                raw_16k = resample_to_16k(raw_audio_np)
                                clean_16k = resample_to_16k(audio_np)
                                
                                if raw_vad is not None:
                                    raw_webrtc, _ = run_webrtc_with(raw_vad, raw_16k)
                                if clean_vad is not None:
                                    clean_webrtc, speech_subframes = run_webrtc_with(clean_vad, clean_16k)
                            except Exception as vad_check_err:
                                pass
                        
                        # 3. Silero VAD Check
                        # CRITICAL: Feed Silero the RAW audio (before DF3), not cleaned.
                        # DF3 amplitude-suppresses the signal which confuses Silero.
                        # Correct pipeline:
                        #   Raw → DF3 → clean audio (for WebRTC clean gate)
                        #   Raw → Silero directly  (parallel, not in series)
                        silero_prob = 0.0
                        if self.silero_vad.enabled:
                            try:
                                raw_np_32 = raw_audio_np.astype(np.float32) / 32768.0
                                if sample_rate != 16000:
                                    orig_len = len(raw_np_32)
                                    target_len = int(orig_len * 16000 / sample_rate)
                                    indices = np.linspace(0, orig_len - 1, target_len)
                                    raw_16k_32 = np.interp(indices, np.arange(orig_len), raw_np_32)
                                else:
                                    raw_16k_32 = raw_np_32
                                silero_prob = self.silero_vad.process_chunk(raw_16k_32.astype(np.float32))
                            except Exception as silero_err:
                                pass
                        
                        # Joint Voting Decision:
                        #
                        # Priority 1: raw_webrtc=True  → speech. Raw WebRTC on
                        #             unprocessed mic is highly reliable. No Silero
                        #             gate needed — it was blocking detection when
                        #             DF3 was feeding Silero zeroed-out audio.
                        # Priority 2: clean_webrtc + silero > 0.3  → speech.
                        # Priority 3: silero alone > 0.80 (very confident) → speech.
                        # Priority 4: rms_strong (RMS > 3× threshold) → speech.
                        #             Last resort if both VADs somehow miss real audio.
                        rms_strong = rms > rms_threshold * 3.0
                        if self.silero_vad.enabled:
                            is_speech_chunk = (
                                raw_webrtc                          # raw mic → trust it
                                or (clean_webrtc and silero_prob > 0.3)
                                or silero_prob > 0.80
                                or rms_strong
                            )
                        else:
                            is_speech_chunk = raw_webrtc or clean_webrtc or rms_strong
                        
                        # Per-chunk diagnostic print
                        print(
                            f"[VAD] rms={rms:.1f} th={rms_threshold:.1f} rms_gate={rms_gate} rms_strong={rms_strong}"
                            f" raw_webrtc={raw_webrtc} clean_webrtc={clean_webrtc}"
                            f" silero={silero_prob:.3f} => speech={is_speech_chunk}"
                        )

                        if started_speech:
                            frames.append(denoised_bytes)
                        else:
                            pre_speech_frames.append(denoised_bytes)

                        # Asymmetric noise floor update on non-speech chunks
                        if not is_speech_chunk:
                            speech_candidate_chunks = 0
                            if self.noise_floor is None:
                                self.noise_floor = rms
                            else:
                                if rms < self.noise_floor:
                                    self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms
                                else:
                                    self.noise_floor = 0.999 * self.noise_floor + 0.001 * rms
                            
                            # Dynamically update the thresholds
                            self.energy_rms_threshold = max(35, min(1000, int(self.noise_floor * 1.8)))
                            rms_threshold = self.energy_rms_threshold * 0.5

                        if is_speech_chunk:
                            speech_candidate_chunks += 1
                            should_start_speech = started_speech or speech_candidate_chunks >= 2 or (rms_gate and speech_subframes >= 2)
                            if not should_start_speech:
                                continue
                            self.vad_detecting_speech = True
                            self._last_record_live_speech_chunks += 1
                            self._last_record_live_speech_subframes += speech_subframes
                            if not started_speech:
                                frames = list(pre_speech_frames)
                                print(f"[VOICE START] delay={now - t_start:.2f}s rms={rms:.1f} silero_prob={silero_prob:.3f}")
                                started_speech = True
                                self._last_record_started_speech = True
                                speech_start_time = now
                                self.speech_start_time = now
                                # Dynamically trigger GUI State Transition
                                try:
                                    import sys
                                    main_module = sys.modules.get('__main__')
                                    if main_module and hasattr(main_module, 'set_state'):
                                        main_module.set_state("LISTENING")
                                    if main_module and hasattr(main_module, 'set_text'):
                                        main_module.set_text("Listening...")
                                except Exception:
                                    pass
                            if silence_start_time is not None:
                                print(f"[Voice/ChunkedRecord] Speech resumed after {now - silence_start_time:.2f}s silence")
                            silence_start_time = None
                        else:
                            self.vad_detecting_speech = False
                            if started_speech:
                                if silence_start_time is None:
                                    print(f"[Voice/ChunkedRecord] Silence started detected at {now - t_start:.2f}s (RMS: {rms:.1f})")
                                    silence_start_time = now
                                elif (now - silence_start_time) > self.recognizer.pause_threshold:
                                    print(f"[Voice/ChunkedRecord] Silence threshold reached ({self.recognizer.pause_threshold}s). Breaking loop at {now - t_start:.2f}s")
                                    break
                                
                                # Streaming STT trigger (every 800ms)
                                if now - last_streaming_stt_time > 0.8:
                                    last_streaming_stt_time = now
                                    if streaming_stt_thread is None or not streaming_stt_thread.is_alive():
                                        audio_snapshot = sr.AudioData(b"".join(frames), sample_rate, sample_width)
                                        streaming_stt_thread = threading.Thread(
                                            target=run_streaming_stt_worker,
                                            args=(audio_snapshot,),
                                            name="AriaStreamingSTT",
                                            daemon=True
                                        )
                                        streaming_stt_thread.start()

                except (IOError, Exception) as e:
                    print(f"[Voice/ChunkedRecord] Error during read: {e}")
                    pytime.sleep(0.01)
        except Exception as e:
            import traceback
            print(f"[VOICE ERROR] Exception in _record_audio_chunked: {e}")
            traceback.print_exc()
        finally:
            self.recording_active = False
            self.vad_detecting_speech = False
            self.speech_start_time = 0.0
            
            # Yield CPU listening lock clear
            if hasattr(self, 'listening_active'):
                self.listening_active.clear()

        if not frames:
            return None

        all_bytes = b"".join(frames)
        return sr.AudioData(all_bytes, sample_rate, sample_width)

    def listen(self, timeout=6, phrase_time_limit=12, active_conversation=False):
        if getattr(self, '_shutting_down', False):
            return None
        if getattr(self, 'interrupted_transcription', None):
            txt = self.interrupted_transcription
            self.interrupted_transcription = None
            print(f"[Voice] Returning pre-transcribed interrupt text: '{txt}'")
            return txt
        if self.is_speaking:
            print('[Voice] ARIA is speaking. Pausing microphone capture...')
            while self.is_speaking:
                time.sleep(0.1)
            
            # Check for immediate barge-in interruption during wait
            if getattr(self, 'interrupted_transcription', None):
                txt = self.interrupted_transcription
                self.interrupted_transcription = None
                print(f"[Voice] Returning pre-transcribed interrupt text after speaking finished/interrupted: '{txt}'")
                return txt

            # Wait for ARIA's voice to fully decay before opening mic
            # 0.4s was too short — audio tail was triggering the abort gate
            time.sleep(1.2)
            
            if getattr(self, 'interrupted_transcription', None):
                txt = self.interrupted_transcription
                self.interrupted_transcription = None
                print(f"[Voice] Returning pre-transcribed interrupt text after delay: '{txt}'")
                return txt

        if not self.microphone:
            print('[Voice] No microphone available.')
            return None
        try:
            with self.mic_lock, self.microphone as source:
                print('[STATUS] Listening...')
                audio = self._record_audio_chunked(source, timeout=timeout, phrase_time_limit=phrase_time_limit, active_conversation=active_conversation)
                if audio is None:
                    return None
            audio = self.denoise_audio(audio)
            
            # Live SNR Monitoring
            import numpy as np
            audio_np_snr = np.frombuffer(audio.get_raw_data(), dtype=np.int16)
            signal_rms = np.sqrt(np.mean(audio_np_snr.astype(np.float32) ** 2)) if len(audio_np_snr) > 0 else 1.0
            noise_floor = getattr(self, "noise_floor", None) or 30.0
            snr_db = 20 * np.log10(signal_rms / max(1.0, noise_floor))
            snr_level = "Warning"
            if snr_db > 15.0:
                snr_level = "Excellent"
            elif snr_db >= 10.0:
                snr_level = "OK"
            print(f"[AcousticKernel] Live SNR: {snr_db:.1f}dB ({snr_level}) [Signal RMS: {signal_rms:.1f}, Noise Floor: {noise_floor:.1f}]")
            
            # Warn user if SNR < 10 dB with 60-second cooldown
            if snr_db < 10.0:
                now_t = time.time()
                if (now_t - getattr(self, "last_snr_alert_time", 0.0)) > 60.0:
                    self.last_snr_alert_time = now_t
                    print(f"[AcousticKernel] Warning: SNR {snr_db:.1f}dB is below 10dB threshold. Speaking warning.")
                    self.speak("I'm having trouble hearing you due to the background noise.")

            duration = len(audio.get_raw_data()) / (audio.sample_rate * audio.sample_width)
            min_duration = 0.40 if active_conversation else 0.80
            if duration < min_duration:
                print(f'[Voice/DurationGate] Audio too short: {duration:.2f}s (Threshold: {min_duration:.2f}s). Skipping STT.')
                return None
            if not self.is_loud_enough(audio):
                print('[Voice/EnergyGate] Ambient noise below threshold. Skipping STT.')
                return None
            if not self.is_human_speech(audio, active_conversation=active_conversation):
                print('[Voice/VAD] No human speech detected in audio. Skipping STT.')
                return None
            if getattr(self, '_shutting_down', False):
                return None
            text = self.whisper_transcribe(audio)
            if text:
                audio_np = np.frombuffer(audio.get_raw_data(), dtype=np.int16)

                # 1. DualVerification / Speaker Verification check (if owner is registered)
                if self.speaker_recognizer.owner_voiceprint is not None:
                    is_owner, similarity, label = self.speaker_recognizer.verify_speaker(audio_np, sample_rate=audio.sample_rate)
                    self.last_speaker_verified = is_owner
                    self.last_speaker_similarity = similarity
                    self.last_speaker_label = label
                    if not is_owner:
                        print(f"[DualVerification] warning: Voice mismatch. Owner expected but detected {label} (similarity={similarity:.3f}).")
                else:
                    self.last_speaker_verified = True
                    self.last_speaker_similarity = 1.0
                    self.last_speaker_label = "Owner (not enrolled)"

                # 2. Safe enrollment check
                owner_face_present = False
                if getattr(self, 'aria', None) is not None:
                    owner_face_present = (self.aria.known_user in ["chinmay", "chinmaya"] and (time.time() - getattr(self.aria, "owner_last_seen_time", 0.0) < 900.0))

                valid_cmd, _ = is_valid_speech_text(text, active_conversation=active_conversation)

                if owner_face_present and valid_cmd and duration > 2.0 and self.speaker_recognizer.owner_voiceprint is None:
                    print(f"[DualVerification] Enrolling owner voiceprint. Duration: {duration:.2f}s, Command: '{text}'")
                    self.speaker_recognizer.register_owner(audio_np, sample_rate=audio.sample_rate)

                try:
                    print(f'[User]: {text}')
                except UnicodeEncodeError:
                    print(f'[User]: {text.encode("ascii", "backslashreplace").decode("ascii")}')
                try:
                    def _run_analyzer_async():
                        try:
                            self.last_voice_emotion = self.voice_analyzer.analyze(audio)
                            self.last_voice_emotion_time = time.time()
                        except Exception as background_err:
                            print(f'[Voice] Voice emotion analysis async error: {background_err}')
                    threading.Thread(target=_run_analyzer_async, daemon=True).start()
                except Exception as analyzer_err:
                    print(f'[Voice] Voice emotion analysis setup failed: {analyzer_err}')
                return text
            return None
        except OSError as e:
            print(f'[Voice] Microphone OS error: {e}')
            self._init_mic()
            return None
        except Exception as e:
            print(f'[Voice] Listen error: {e}')
            return None

    def listen_for_wake_word(self, wake_words=None, timeout=None):
        if getattr(self, '_shutting_down', False):
            return None
        if self.is_speaking:
            return None
        if hasattr(self, 'wake_word_detector') and self.wake_word_detector.is_active():
            import numpy as np
            import time as pytime
            print(f'[Voice/WakeWord] Monitoring continuously via local OpenWakeWord ONNX model ({self.wake_word_detector.model_name})...')
            if not self.microphone:
                return None
            try:
                with self.mic_lock, self.microphone as source:
                    sample_rate = source.SAMPLE_RATE
                    chunk_ms = 80
                    chunk_samples = int(sample_rate * chunk_ms / 1000)
                    t_start = pytime.time()
                    while True:
                        if timeout and (pytime.time() - t_start) > timeout:
                            return None
                        if self.is_speaking:
                            return None
                        try:
                            raw_bytes = source.stream.read(chunk_samples)
                            if not raw_bytes:
                                continue
                            audio_np = np.frombuffer(raw_bytes, dtype=np.int16)
                            if len(audio_np) == 0:
                                continue
                            if sample_rate != 16000:
                                orig_len = len(audio_np)
                                target_len = int(orig_len * 16000 / sample_rate)
                                if target_len > 0:
                                    indices = np.linspace(0, orig_len - 1, target_len)
                                    resampled_np = np.interp(indices, np.arange(orig_len), audio_np.astype(np.float32))
                                    audio_np = np.clip(resampled_np, -32768, 32767).astype(np.int16)
                                else:
                                    continue
                            if len(audio_np) < 1280:
                                audio_np = np.pad(audio_np, (0, 1280 - len(audio_np)))
                            elif len(audio_np) > 1280:
                                audio_np = audio_np[:1280]
                            detected, confidence = self.wake_word_detector.detect(audio_np)
                            if detected:
                                print(f'[Voice/WakeWord] Wake word detected locally! Confidence: {confidence:.2f}')
                                if hasattr(self, 'on_speech_detected') and self.on_speech_detected:
                                    self.on_speech_detected()
                                return 'aria'
                        except IOError:
                            pass
            except Exception as e:
                print(f'[Voice/WakeWord] Local detection failed, falling back to STT: {e}')
        try:
            from wake_word import ARIA_VARIANTS
            if wake_words is None:
                wake_words = ARIA_VARIANTS
            else:
                wake_words = list(set(list(wake_words) + ARIA_VARIANTS))
        except ImportError:
            if wake_words is None:
                wake_words = ['aria', 'hey aria', 'ok aria', 'hello aria']
        if not self.microphone:
            return None
        try:
            with self.mic_lock, self.microphone as source:
                audio = self._record_audio_chunked(source, timeout=timeout, phrase_time_limit=5, active_conversation=False)
                if audio is None:
                    return None
            audio = self.denoise_audio(audio)
            if not self.is_loud_enough(audio):
                return None
            if not self.is_human_speech(audio, mode=3, min_ratio=WAKE_VAD_THRESHOLD, active_conversation=False):
                return None
            try:
                text = self.recognizer.recognize_google(audio).lower()
                print(f'[Wake Check]: \'{text}\'')
                for word in wake_words:
                    if word.lower() in text:
                        return text
                return None
            except:
                return None
        except Exception as e:
            return None

    def play_audio_file(self, file_path):
        if not os.path.exists(file_path):
            print(f"[Voice] Audio file not found: {file_path}")
            return
        try:
            if pygame.mixer.get_init():
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                    try:
                        pygame.mixer.music.unload()
                    except Exception:
                        pass
                pygame.mixer.music.load(file_path)
                pygame.mixer.music.play()
                # Wait for playback to finish
                while pygame.mixer.music.get_busy():
                    time.sleep(0.05)
        except Exception as e:
            print(f"[Voice] Error playing audio file: {e}")

    def cleanup(self):
        self._shutting_down = True
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
                pygame.mixer.quit()
                print('[Voice] Pygame mixer released successfully.')
        except Exception as e:
            print(f'[Voice Cleanup] Error releasing mixer: {e}')
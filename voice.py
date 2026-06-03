# -*- coding: utf-8 -*-
import speech_recognition as sr
import threading
import time
import os
import asyncio
import edge_tts
import pygame
import requests
from skills.voice_filter import is_valid_speech_text

# VAD Speech Ratio thresholds (0.0 to 1.0)
WAKE_VAD_THRESHOLD = 0.08
CONVERSATION_VAD_THRESHOLD = 0.08

class Voice:
    def __init__(self):
        self._init_tts()
        self._cleanup_temp_files()
        self._is_speaking_lock = False
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
        self.recognizer.pause_threshold = 1.0        # Give user time to breathe
        self.recognizer.energy_threshold = 200       # Lower base threshold
        self.recognizer.dynamic_energy_threshold = False # Disable dynamic (prevents hanging)
        self.energy_rms_threshold = 300              # Lower initial base RMS threshold
        self.microphone = None
        self._init_mic()
        self.noise_profile = None
        self.calibrate_noise_profile(1.0)
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
        txt_clean = (text or "").strip().lower().replace(".", "").replace("!", "").replace("?", "")
        words = txt_clean.split()
        
        avg_logprob = getattr(self, 'last_avg_logprob', None)
        no_speech_prob = getattr(self, 'last_no_speech_prob', None)

        # 1. Global Whisper Confidence Triage
        # Reject highly uncertain segments that are likely static, AC hum or breath noises
        if avg_logprob is not None and avg_logprob < -1.00:
            print(f"[VoiceFilter] Filtered out transcript '{text}' due to low confidence (avg_logprob: {avg_logprob:.3f} < -1.00)")
            return False
            
        if no_speech_prob is not None and no_speech_prob > 0.45:
            print(f"[VoiceFilter] Filtered out transcript '{text}' due to high no-speech probability (no_speech_prob: {no_speech_prob:.3f} > 0.45)")
            return False

        # 1b. Strict common/suspicious Whisper hallucination filter
        COMMON_HALLUCINATIONS = {
            "thank you", "thanks", "terima kasih", "okay", "yeah", "hmm", "bye", "goodbye", "yes", "no"
        }
        clean_phrase = txt_clean.strip()
        if clean_phrase in COMMON_HALLUCINATIONS:
            if avg_logprob is not None and avg_logprob < -0.55:
                print(f"[VoiceFilter] Filtered out suspicious common hallucination '{text}' due to low avg_logprob ({avg_logprob:.3f} < -0.55)")
                return False
            if no_speech_prob is not None and no_speech_prob > 0.15:
                print(f"[VoiceFilter] Filtered out suspicious common hallucination '{text}' due to high no_speech_prob ({no_speech_prob:.3f} > 0.15)")
                return False

        SHORT_PHRASE_GUARD = {
            "thank you",
            "thanks",
            "okay",
            "yes",
            "no",
            "hello",
            "hey"
        }
        
        if len(words) < 3 and txt_clean in SHORT_PHRASE_GUARD:
            vad_ratio = getattr(self, 'last_speech_ratio', 0.0)
            
            # Check wake word presence
            main_mod = __import__('__main__')
            aria = getattr(main_mod, 'instance', None) or getattr(main_mod, 'aria_instance', None)
            wake_words = ["hey aria", "ok aria", "okay aria", "aria"]
            if aria and hasattr(aria, 'WAKE_WORDS'):
                wake_words = aria.WAKE_WORDS
            has_wake = any(w in txt_clean for w in wake_words)
            
            is_valid = True
            reasons = []
            
            if vad_ratio < 0.10:
                is_valid = False
                reasons.append(f"VAD speech ratio too low ({vad_ratio*100:.1f}% < 10.0%)")
            
            if avg_logprob is not None and avg_logprob < -0.80:
                is_valid = False
                reasons.append(f"Whisper avg_logprob too low ({avg_logprob:.3f} < -0.80)")
                
            if no_speech_prob is not None and no_speech_prob > 0.40:
                is_valid = False
                reasons.append(f"Whisper no_speech_prob too high ({no_speech_prob:.3f} > 0.40)")
                
            if not (active_conversation or has_wake):
                is_valid = False
                reasons.append("No active conversation or wake word")
                
            if not is_valid:
                print(f"[VoiceFilter] Filtered out short phrase '{text}' due to: {', '.join(reasons)}")
                return False

        valid, reason = is_valid_speech_text(text, active_conversation=active_conversation)
        if valid:
            return True
        if reason == 'static_silence_hallucination':
            print(f'[VoiceFilter] Filtered out static/silence hallucination: \'{text}\'')
        elif reason == 'ultra_short_noise':
            print(f'[VoiceFilter] Filtered out ultra-short noise: \'{text}\'')
        elif reason == 'single_word_ambient_noise':
            print(f'[VoiceFilter] Filtered out single-word ambient noise: \'{text}\'')
        return False
            
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

            if total_frames == 0:
                self.last_speech_frames = 0
                self.last_total_frames = 0
                return False

            self.last_speech_frames = speech_frames
            self.last_total_frames = total_frames

            speech_ratio = speech_frames / total_frames
            self.last_speech_ratio = speech_ratio
            print(f'[Voice/VAD] Speech ratio: {speech_ratio*100:.1f}% (Threshold: {min_ratio*100:.1f}%), Speech frames: {speech_frames}/{total_frames}')

            is_speech_detected = speech_ratio >= min_ratio and speech_frames >= 5
            if is_speech_detected and hasattr(self, 'on_speech_detected') and self.on_speech_detected:
                self.on_speech_detected()
            return is_speech_detected

        except Exception as e:
            self.last_speech_frames = None
            self.last_total_frames = None
            print(f'[Voice/VAD] WebRTC VAD error: {e}')
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
            with self.microphone as source:
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

            print(f'[ARIA]: {clean}')
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
                                    engine.runAndWait()
                                threading.Thread(target=run_tts, daemon=True).start()
                            self._is_speaking_lock = False
                            return
                        except Exception as direct_err:
                            print(f"[Voice] Local pyttsx3 direct speak failed: {direct_err}")
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
            with self.microphone as source:
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
                        is_speech = False
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
                                    is_speech = vad.is_speech(vad_bytes[:vad_samples * 2], vad_rate)
                                except Exception:
                                    pass
                        else:
                            is_speech = rms > interrupt_threshold
 
                        if is_speech and rms > interrupt_threshold:
                            if not speech_detected:
                                consecutive_speech += 1
                                if consecutive_speech >= required_speech_frames:
                                    # Interrupt triggered! Stop the music immediately
                                    print(f"[Voice/Interrupt] Voice activity detected (RMS: {rms:.1f}). Stopping TTS.")
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
                    
                    print(f"[Voice/Whisper] avg_logprob: {avg_logprob:.3f}, no_speech_prob: {no_speech_prob:.3f}")
                    if text:
                        print(f'[STT Whisper]: {text}')
                        return text
                else:
                    print(f'[Voice/Whisper] Whisper failed {res.status_code}. Falling back to Google STT.')
            except Exception as e:
                print(f'[Voice/Whisper] Transcription error: {e}. Falling back to Google STT.')
        try:
            text = self.recognizer.recognize_google(audio_data)
            print(f'[STT RAW]: {text}')
            return text
        except sr.UnknownValueError:
            return ''
        except sr.RequestError as e:
            print(f'[Voice] Google STT API error: {e}')
            try:
                text = self.recognizer.recognize_sphinx(audio_data)
                print(f'[STT Offline]: {text}')
                return text
            except:
                return ''

    def _record_audio_chunked(self, source, timeout=3, phrase_time_limit=5, active_conversation=False):
        if getattr(self, '_shutting_down', False):
            return None
        import time as pytime
        import numpy as np

        self.recording_active = True
        self.vad_detecting_speech = False

        sample_rate = source.SAMPLE_RATE
        sample_width = source.SAMPLE_WIDTH

        chunk_ms = 100
        chunk_samples = int(sample_rate * chunk_ms / 1000)

        frames = []
        t_start = pytime.time()
        rms_threshold = self.energy_rms_threshold * 0.8

        started_speech = False
        speech_start_time = None
        silence_start_time = None

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
                if not active_conversation:
                    main_mod = __import__('__main__')
                    aria = getattr(main_mod, 'instance', None) or getattr(main_mod, 'aria_instance', None)
                    if aria:
                        is_owner_active = (getattr(aria, 'known_user', None) in ["chinmay", "chinmaya"] and (pytime.time() - getattr(aria, "last_identity_match_time", 0.0) < 180.0))
                        if is_owner_active:
                            print("[Voice/ChunkedRecord] Aborted recording because owner became active (bypassing wake word).")
                            return None

                now = pytime.time()
                if not started_speech:
                    if timeout and (now - t_start) > timeout:
                        return None
                else:
                    if phrase_time_limit and (now - speech_start_time) > phrase_time_limit:
                        break

                try:
                    raw_bytes = source.stream.read(chunk_samples)
                    if not raw_bytes:
                        pytime.sleep(0.01)
                        continue

                    frames.append(raw_bytes)

                    # Check energy level to detect start of speech / silence
                    audio_np = np.frombuffer(raw_bytes, dtype=np.int16)
                    if len(audio_np) > 0:
                        rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2))
                        if rms > rms_threshold:
                            self.vad_detecting_speech = True
                            if not started_speech:
                                started_speech = True
                                speech_start_time = now
                                self.speech_start_time = now
                            silence_start_time = None
                        else:
                            self.vad_detecting_speech = False
                            if started_speech:
                                if silence_start_time is None:
                                    silence_start_time = now
                                elif (now - silence_start_time) > self.recognizer.pause_threshold:
                                    break
                except (IOError, Exception):
                    pytime.sleep(0.01)
        finally:
            self.recording_active = False
            self.vad_detecting_speech = False
            self.speech_start_time = 0.0

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
            with self.microphone as source:
                print('[STATUS] Listening...')
                audio = self._record_audio_chunked(source, timeout=timeout, phrase_time_limit=phrase_time_limit, active_conversation=active_conversation)
                if audio is None:
                    return None
            audio = self.denoise_audio(audio)
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
                print(f'[User]: {text}')
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
                with self.microphone as source:
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
            with self.microphone as source:
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
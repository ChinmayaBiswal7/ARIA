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
WAKE_VAD_THRESHOLD = 0.10
CONVERSATION_VAD_THRESHOLD = 0.08

class Voice:
    def __init__(self):
        self._init_tts()
        self._cleanup_temp_files()
        self._is_speaking_lock = False
        self.recording_active = False
        self.vad_detecting_speech = False
        self.on_speech_detected = None
        self._shutting_down = False

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

    @property
    def is_speaking(self):
        return self._is_speaking_lock or bool(pygame.mixer.get_init() and pygame.mixer.music.get_busy())

    def is_valid_speech(self, text, active_conversation=False):
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
                return False
            rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2))
            print(f'[Voice/EnergyGate] Captured audio RMS: {rms:.1f} (Threshold: {threshold})')
            return rms > threshold
        except Exception as e:
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
                return False

            speech_ratio = speech_frames / total_frames
            print(f'[Voice/VAD] Speech ratio: {speech_ratio*100:.1f}% (Threshold: {min_ratio*100:.1f}%), Speech frames: {speech_frames}/{total_frames}')

            is_speech_detected = speech_ratio >= min_ratio and speech_frames >= 3
            if is_speech_detected and hasattr(self, 'on_speech_detected') and self.on_speech_detected:
                self.on_speech_detected()
            return is_speech_detected

        except Exception as e:
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
        except Exception as e:
            print(f'[Voice] Audio Mixer Init Error: {e}')

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
                    # Dynamically set energy threshold based on noise level
                    # Multiply noise RMS by 1.8, but clamp it between 150 and 800 to prevent extreme settings
                    self.energy_rms_threshold = max(150, min(800, int(noise_rms * 1.8)))
                    print(f'[Voice] Noise profile calibrated successfully ({len(self.noise_profile)} samples).')
                    print(f'[Voice] Dynamic energy threshold set to: {self.energy_rms_threshold} (Noise RMS: {noise_rms:.1f})')
                else:
                    print('[Voice] Calibration warning: No frames captured. Using default energy threshold of 300.')
                    self.energy_rms_threshold = 300
        except Exception as e:
            print(f'[Voice] Noise calibration skipped: {e}')

    def speak(self, text, block=True):
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
                    asyncio.run(communicate.save(output_file))
                    generated = True
                except Exception as e:
                    print(f'[Voice] Edge-TTS generation error: {e}. Falling back to offline local TTS (pyttsx3)...')
                    try:
                        import pyttsx3
                        engine = pyttsx3.init()
                        engine.say(clean)
                        if block:
                            engine.runAndWait()
                        else:
                            def run_tts():
                                engine.runAndWait()
                            threading.Thread(target=run_tts, daemon=True).start()
                        self._is_speaking_lock = False
                        return
                    except Exception as pytts_err:
                        print(f'[Voice] Local pyttsx3 TTS failed: {pytts_err}')
                        self._is_speaking_lock = False
                        return
            interrupted = False
            try:
                pygame.mixer.music.load(output_file)
                pygame.mixer.music.play()
                if block:
                    while pygame.mixer.music.get_busy():
                        time.sleep(0.05)
            except Exception as e:
                print(f'[Voice] Audio playback Error: {e}')
            return interrupted
        finally:
            self._is_speaking_lock = False

    def _monitor_mic_during_speech(self):
        if not self.microphone or getattr(self.microphone, 'stream', None) is not None:
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            return False
        t_start = time.time()
        while pygame.mixer.music.get_busy() and (time.time() - t_start) < 0.4:
            pygame.time.Clock().tick(10)
        import numpy as np
        try:
            import webrtcvad
            vad = webrtcvad.Vad(3)
        except ImportError:
            vad = None
        interrupted = False
        try:
            with self.microphone as source:
                sample_rate = source.SAMPLE_RATE
                vad_rate = 16000
                vad_frame_ms = 30
                vad_samples = int(vad_rate * vad_frame_ms / 1000)
                source_samples = int(sample_rate * vad_frame_ms / 1000)
                interrupt_threshold = max(self.energy_rms_threshold * 2.5, 1000)
                consecutive_speech = 0
                required_speech_frames = 10
                original_volume = pygame.mixer.music.get_volume()
                pygame.mixer.music.set_volume(original_volume * 0.7)
                while pygame.mixer.music.get_busy():
                    try:
                        raw_bytes = source.stream.read(source_samples)
                        if not raw_bytes:
                            continue
                        audio_np = np.frombuffer(raw_bytes, dtype=np.int16)
                        if len(audio_np) == 0:
                            continue
                        rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2))
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
                        if rms > interrupt_threshold and is_speech:
                            consecutive_speech += 1
                            if consecutive_speech >= required_speech_frames:
                                print(f'[Voice/Interrupt] Voice interrupt triggered! RMS: {rms:.1f}, VAD: {is_speech}')
                                if hasattr(self, 'on_speech_detected') and self.on_speech_detected:
                                    self.on_speech_detected()
                                interrupted = True
                                break
                        else:
                            consecutive_speech = max(0, consecutive_speech - 1)
                    except IOError:
                        pass
                    pygame.time.Clock().tick(20)
                try:
                    pygame.mixer.music.set_volume(original_volume)
                except Exception:
                    pass
        except Exception as e:
            print(f'[Voice/Interrupt] Monitoring error: {e}')
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
        if interrupted:
            try:
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
            except Exception:
                pass
            return True
        return False

    def whisper_transcribe(self, audio_data):
        import numpy as np
        if isinstance(audio_data, np.ndarray):
            audio_data = sr.AudioData(audio_data.tobytes(), 16000, 2)
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
                        'response_format': (None, 'json')
                    }
                    if getattr(self, 'stt_language', None):
                        files['language'] = (None, self.stt_language)
                    res = requests.post(url, headers=headers, files=files, timeout=12)
                try:
                    os.remove(temp_wav)
                except Exception:
                    pass
                if res.status_code == 200:
                    text = res.json().get('text', '').strip()
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

    def _record_audio_chunked(self, source, timeout=3, phrase_time_limit=5):
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
                    print("[Voice/ChunkedRecord] Aborted recording because ARIA started speaking.")
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
                            if not started_speech:
                                started_speech = True
                                self.vad_detecting_speech = True
                                speech_start_time = now
                            silence_start_time = None
                        else:
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

        if not frames:
            return None

        all_bytes = b"".join(frames)
        return sr.AudioData(all_bytes, sample_rate, sample_width)

    def listen(self, timeout=6, phrase_time_limit=12, active_conversation=False):
        if getattr(self, '_shutting_down', False):
            return None
        if self.is_speaking:
            print('[Voice] ARIA is speaking. Pausing microphone capture...')
            while self.is_speaking:
                time.sleep(0.1)
            # Wait for ARIA's voice to fully decay before opening mic
            # 0.4s was too short — audio tail was triggering the abort gate
            time.sleep(1.2)

        if not self.microphone:
            print('[Voice] No microphone available.')
            return None
        try:
            with self.microphone as source:
                print('[STATUS] Listening...')
                audio = self._record_audio_chunked(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
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
            text = self.whisper_transcribe(audio)
            if text:
                print(f'[User]: {text}')
                try:
                    self.last_voice_emotion = self.voice_analyzer.analyze(audio)
                    self.last_voice_emotion_time = time.time()
                except Exception as analyzer_err:
                    print(f'[Voice] Voice emotion analysis failed: {analyzer_err}')
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
                audio = self._record_audio_chunked(source, timeout=timeout, phrase_time_limit=5)
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
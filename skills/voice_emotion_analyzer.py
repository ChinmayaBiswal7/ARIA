import numpy as np
import librosa

class VoiceEmotionAnalyzer:
    def __init__(self):
        print("[VoiceEmotionAnalyzer] Initialized successfully.")

    def analyze(self, audio_data) -> str:
        """
        Analyze audio_data (sr.AudioData) to determine user emotional state.
        Returns 'stressed', 'tired', or 'neutral'.
        """
        try:
            raw_bytes = audio_data.get_raw_data()
            sample_rate = audio_data.sample_rate
            sample_width = audio_data.sample_width

            if len(raw_bytes) == 0:
                return "neutral"

            # Convert PCM bytes to float32 normalized to [-1.0, 1.0]
            if sample_width == 2:
                audio_np = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            elif sample_width == 4:
                audio_np = np.frombuffer(raw_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0
            else:
                audio_np = np.frombuffer(raw_bytes, dtype=np.int8).astype(np.float32) / 128.0

            # Safeguard: if audio is too short or silent
            duration = len(audio_np) / sample_rate
            if duration < 1.2:
                return "neutral"

            # Calculate RMS energy
            rms = librosa.feature.rms(y=audio_np)
            rms_mean = float(np.mean(rms))
            rms_std = float(np.std(rms))

            # Calculate Spectral Centroid (brightness)
            centroid = librosa.feature.spectral_centroid(y=audio_np, sr=sample_rate)
            centroid_mean = float(np.mean(centroid))

            # Estimate Pitch (F0) using librosa.yin
            fmin = 75
            fmax = 400
            try:
                pitch = librosa.yin(y=audio_np, fmin=fmin, fmax=fmax, sr=sample_rate)
                pitch_mean = float(np.mean(pitch))
                pitch_std = float(np.std(pitch))
            except Exception:
                pitch_mean = 150.0
                pitch_std = 0.0

            # Categorization heuristic
            # Stressed: high spectral centroid (bright, tense voice), high pitch variance, or loud volume
            # Tired: very quiet (low RMS), dark/muffled sound (low spectral centroid), flat pitch
            emotion = "neutral"
            
            is_tired = (rms_mean < 0.015 and centroid_mean < 1300 and pitch_std < 22)
            is_stressed = (centroid_mean > 2700 or pitch_std > 60 or (pitch_mean > 220 and rms_mean > 0.06))

            if is_stressed:
                emotion = "stressed"
            elif is_tired:
                emotion = "tired"

            print(f"[VoiceEmotionAnalyzer] Pitch: {pitch_mean:.1f}Hz (std: {pitch_std:.1f}Hz) | Centroid: {centroid_mean:.1f}Hz | RMS: {rms_mean:.4f} (std: {rms_std:.4f}) | Decision: {emotion}")
            return emotion

        except Exception as e:
            print(f"[VoiceEmotionAnalyzer] Error analyzing voice emotion: {e}")
            return "neutral"

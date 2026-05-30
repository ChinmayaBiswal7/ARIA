# wake_word.py
import os
import numpy as np

# Variations of "Aria" Whisper might hear
ARIA_VARIANTS = [
    "aria", "area", "arya", "aeria", "arius", "naria"
]

class WakeWordDetector:
    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self.model = None
        self.model_name = "aria"
        self._whisper_transcribe = None  # will be set by voice.py

        # Still try to load aria.onnx if it exists
        custom_model_path = r"C:\D FOLDER\Projects\AI\models\aria.onnx"
        if os.path.exists(custom_model_path):
            try:
                from openwakeword.model import Model
                self.model = Model(
                    wakeword_models=[custom_model_path],
                    inference_framework="onnx"
                )
                print(f"[WakeWord] Loaded custom model: aria.onnx")
            except Exception as e:
                print(f"[WakeWord] Could not load aria.onnx: {e}")
                print("[WakeWord] Falling back to text matching")
        else:
            print("[WakeWord] No aria.onnx found — using text matching for 'Aria'")

    def is_active(self):
        # Active if ONNX model is loaded
        return self.model is not None

    def set_transcriber(self, fn):
        """Pass in your Whisper transcribe function from voice.py"""
        self._whisper_transcribe = fn

    def detect_from_text(self, text: str) -> tuple[bool, float]:
        """Check if transcribed text contains 'aria'"""
        text = text.lower().strip()
        for variant in ARIA_VARIANTS:
            if variant in text:
                print(f"[WakeWord] 'Aria' detected in text: '{text}'")
                return True, 0.9
        return False, 0.0

    def detect(self, audio_chunk: np.ndarray) -> tuple[bool, float]:
        """
        If aria.onnx exists → use ONNX model
        Otherwise → transcribe and text match
        """
        # Use ONNX model if loaded
        if self.model is not None:
            try:
                prediction = self.model.predict(audio_chunk)
                confidence = prediction.get(self.model_name, 0.0)
                if self.model_name not in prediction:
                    for k, val in prediction.items():
                        if self.model_name in k:
                            confidence = val
                            break
                return confidence >= self.threshold, confidence
            except Exception:
                pass

        # Fallback: text matching via Whisper
        if self._whisper_transcribe is not None:
            try:
                text = self._whisper_transcribe(audio_chunk)
                return self.detect_from_text(text)
            except Exception:
                pass

        return False, 0.0

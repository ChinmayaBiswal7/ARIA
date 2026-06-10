"""
ocr_reader.py — ARIA's OCR Perception Layer
=============================================
Extracts raw text from screenshots using available OCR engines.
Fallback chain: EasyOCR → Pytesseract → Windows native.
"""

import threading

class OCRReader:
    _instance = None
    _lock = threading.Lock()
    _engine = None  # "easyocr", "tesseract", or None

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(OCRReader, cls).__new__(cls)
                cls._instance._init_engine()
            return cls._instance

    def _init_engine(self):
        # Try EasyOCR first (pure Python, no external binary)
        try:
            import easyocr
            self._reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            self._engine = "easyocr"
            print("[OCR] EasyOCR engine initialized successfully.")
            return
        except Exception as e:
            print(f"[OCR] EasyOCR not available: {e}")

        # Try Pytesseract (needs Tesseract binary installed)
        try:
            import pytesseract
            # Test if tesseract binary is accessible
            pytesseract.get_tesseract_version()
            self._engine = "tesseract"
            print("[OCR] Pytesseract engine initialized successfully.")
            return
        except Exception as e:
            print(f"[OCR] Pytesseract not available: {e}")

        print("[OCR] WARNING: No OCR engine available. Install easyocr: pip install easyocr")
        self._engine = None

    def extract_text(self, image):
        """
        Extract text from a PIL Image or file path.
        Returns the extracted text as a string, or empty string on failure.
        """
        if self._engine is None:
            return ""

        try:
            import numpy as np
            from PIL import Image

            # Convert to PIL Image if needed
            if isinstance(image, str):
                import os
                if os.path.exists(image):
                    image = Image.open(image)
                else:
                    return ""

            if not hasattr(image, "size"):
                return ""

            if self._engine == "easyocr":
                return self._extract_easyocr(image)
            elif self._engine == "tesseract":
                return self._extract_tesseract(image)
            else:
                return ""
        except Exception as e:
            print(f"[OCR] Text extraction error: {e}")
            return ""

    def extract_text_with_confidence(self, image):
        """
        Extract text and confidence from a PIL Image or file path.
        Returns a dict: {"text": str, "confidence": float}
        """
        if self._engine is None:
            return {"text": "", "confidence": 0.0}

        try:
            from PIL import Image

            # Convert to PIL Image if needed
            if isinstance(image, str):
                import os
                if os.path.exists(image):
                    image = Image.open(image)
                else:
                    return {"text": "", "confidence": 0.0}

            if not hasattr(image, "size"):
                return {"text": "", "confidence": 0.0}

            if self._engine == "easyocr":
                return self._extract_easyocr_with_confidence(image)
            elif self._engine == "tesseract":
                return self._extract_tesseract_with_confidence(image)
            else:
                return {"text": "", "confidence": 0.0}
        except Exception as e:
            print(f"[OCR] Text extraction error: {e}")
            return {"text": "", "confidence": 0.0}

    def _extract_easyocr(self, pil_image):
        import numpy as np
        img_array = np.array(pil_image)
        results = self._reader.readtext(img_array, detail=0, paragraph=True)
        text = "\n".join(results)
        print(f"[OCR/EasyOCR] Extracted {len(text)} chars from screen.")
        return text

    def _extract_easyocr_with_confidence(self, pil_image):
        import numpy as np
        img_array = np.array(pil_image)
        results = self._reader.readtext(img_array, detail=1, paragraph=False)
        texts = []
        confidences = []
        for bbox, text, conf in results:
            texts.append(text)
            confidences.append(float(conf))
        joined_text = "\n".join(texts)
        avg_conf = float(np.mean(confidences)) if confidences else 0.0
        print(f"[OCR/EasyOCR] Extracted {len(joined_text)} chars with confidence {avg_conf:.2f}")
        return {"text": joined_text, "confidence": avg_conf}

    def _extract_tesseract(self, pil_image):
        import pytesseract
        text = pytesseract.image_to_string(pil_image)
        print(f"[OCR/Tesseract] Extracted {len(text)} chars from screen.")
        return text

    def _extract_tesseract_with_confidence(self, pil_image):
        import pytesseract
        from pytesseract import Output
        data = pytesseract.image_to_data(pil_image, output_type=Output.DICT)
        texts = []
        confidences = []
        n_boxes = len(data['text'])
        for i in range(n_boxes):
            conf_str = data['conf'][i]
            try:
                conf = float(conf_str)
            except (ValueError, TypeError):
                conf = -1
            text = data['text'][i].strip()
            if conf != -1:
                confidences.append(conf / 100.0)
                if text:
                    texts.append(text)
        joined_text = " ".join(texts)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        print(f"[OCR/Tesseract] Extracted {len(joined_text)} chars with confidence {avg_conf:.2f}")
        return {"text": joined_text, "confidence": avg_conf}

    def extract_from_screenshot(self):
        """Capture current screen and extract text."""
        try:
            from PIL import ImageGrab
            screenshot = ImageGrab.grab()
            return self.extract_text(screenshot)
        except Exception as e:
            print(f"[OCR] Screenshot capture error: {e}")
            return ""

"""
skills/id_card_detector.py — Rules-based KIIT Student ID Card Detector for ARIA
=============================================================================
Parses webcam/screen images using the OCRReader perception layer and applies regex patterns
and keyword rules to identify Student ID cards, extracting Roll Numbers and institutional details.
"""

import re
from PIL import Image
import numpy as np

from skills.ocr_reader import OCRReader


class AriaIDCardDetector:
    def __init__(self):
        self.ocr_reader = OCRReader()

    def detect_id_card(self, image_input) -> dict:
        """
        Processes an image (BGR numpy array, path, or PIL Image) and checks if it matches a KIIT Student ID card.
        """
        pil_img = None
        
        # Convert image formats to PIL Image
        if isinstance(image_input, np.ndarray):
            import cv2
            # Convert BGR array to PIL
            rgb = cv2.cvtColor(image_input, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
        elif isinstance(image_input, str):
            import os
            if os.path.exists(image_input):
                pil_img = Image.open(image_input)
        elif hasattr(image_input, "size"):
            # Already a PIL Image
            pil_img = image_input

        if pil_img is None:
            return {"is_id_card": False, "reason": "No valid input image provided."}

        # Run OCR extraction
        ocr_res = self.ocr_reader.extract_text_with_confidence(pil_img)
        text = ocr_res.get("text", "")
        confidence = ocr_res.get("confidence", 0.0)

        if not text:
            return {"is_id_card": False, "reason": "No text extracted by OCR."}

        text_lower = text.lower()

        # Institutional keywords checklist
        keywords = ["kiit", "kalinga", "technology", "university", "student", "roll", "registration", "branch"]
        matches = [kw for kw in keywords if kw in text_lower]
        
        # We require at least 2 institutional keywords to trigger a match
        keyword_match = len(matches) >= 2

        # Roll number regex patterns (usually 7-8 digits for KIIT student IDs, e.g., 2005123)
        roll_pattern = re.compile(r'\b\d{7,8}\b')
        roll_matches = roll_pattern.findall(text)
        roll_number = roll_matches[0] if roll_matches else None

        # General ID label checks
        has_id_label = "roll no" in text_lower or "regd no" in text_lower or "id card" in text_lower

        is_id_card = keyword_match and (roll_number is not None or has_id_label)

        # Attempt to extract student name (heuristic: line before or after the Roll No label)
        extracted_name = None
        if is_id_card:
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            for i, line in enumerate(lines):
                line_lower = line.lower()
                # If roll number is on this line, try to look at surrounding lines for a name
                if roll_number and roll_number in line:
                    if i > 0 and not any(kw in lines[i-1].lower() for kw in ["student", "kiit", "roll", "regd", "card"]):
                        extracted_name = lines[i-1]
                    elif i < len(lines) - 1 and not any(kw in lines[i+1].lower() for kw in ["student", "kiit", "roll", "regd", "card"]):
                        extracted_name = lines[i+1]
                    break

        return {
            "is_id_card": is_id_card,
            "text": text,
            "confidence": confidence,
            "roll_number": roll_number,
            "extracted_name": extracted_name,
            "matched_keywords": matches
        }

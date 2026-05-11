import io
import re
from typing import NamedTuple
from PIL import Image


class VisionValidationResult(NamedTuple):
    allowed: bool
    reason: str | None = None


class VisionValidator:
    def __init__(self, max_res: tuple[int, int] = (2560, 1440), max_bytes: int = 5 * 1024 * 1024):
        self.max_res = max_res
        self.max_bytes = max_bytes

    def validate_image(self, data: bytes) -> VisionValidationResult:
        if not data:
            return VisionValidationResult(False, "empty_data")

        if len(data) > self.max_bytes:
            return VisionValidationResult(False, f"oversized_payload: {len(data)}")

        try:
            with Image.open(io.BytesIO(data)) as img:
                w, h = img.size
                if w > self.max_res[0] or h > self.max_res[1]:
                    return VisionValidationResult(False, f"resolution_violation: {w}x{h}")
        except Exception as e:
            return VisionValidationResult(False, f"corrupted_image: {str(e)}")

        return VisionValidationResult(True)

    def sanitize_ocr(self, text: str) -> str:
        """Mask probable secrets in OCR text."""
        if not text:
            return ""

        # Basic mask for API keys and JWTs
        text = re.sub(r"sk-[a-zA-Z0-9]{48}", "[REDACTED_OPENAI_KEY]", text)
        text = re.sub(r"AIza[0-9A-Za-z\-_]{35}", "[REDACTED_GOOGLE_KEY]", text)
        text = re.sub(r"eyJ[a-zA-Z0-9._-]+", "[REDACTED_JWT]", text)
        
        # Normalize whitespace
        text = " ".join(text.split())
        
        return text

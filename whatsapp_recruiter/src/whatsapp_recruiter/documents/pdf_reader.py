from __future__ import annotations

from pathlib import Path

import pytesseract
from pdf2image import convert_from_path
from PIL import Image
from pypdf import PdfReader

from whatsapp_recruiter.config import Settings


class PdfTextExtractor:
    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    def extract_text(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            text = self._extract_embedded_text(file_path)
            if self._is_good_text(text):
                return text
            return self._extract_with_ocr(file_path)
        if suffix in self.IMAGE_SUFFIXES:
            return self._extract_image_with_ocr(file_path)
        if suffix == ".txt":
            return file_path.read_text(encoding="utf-8", errors="ignore").strip()
        return ""

    def _extract_embedded_text(self, pdf_path: Path) -> str:
        reader = PdfReader(str(pdf_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip()

    def _extract_with_ocr(self, pdf_path: Path) -> str:
        images = convert_from_path(
            str(pdf_path),
            dpi=300,
            poppler_path=self.settings.poppler_path,
        )
        texts = []
        for image in images:
            texts.append(pytesseract.image_to_string(image, lang="por"))
        return "\n".join(texts).strip()

    def _extract_image_with_ocr(self, image_path: Path) -> str:
        with Image.open(image_path) as image:
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            return pytesseract.image_to_string(image, lang="por").strip()

    @staticmethod
    def _is_good_text(text: str) -> bool:
        words = [chunk for chunk in text.split() if len(chunk) > 2]
        return len(words) >= 20

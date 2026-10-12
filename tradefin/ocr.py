"""Selectable readers for scanned documents."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from .errors import DocumentError

SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


@dataclass(frozen=True)
class DocumentContent:
    """A document's content in the form expected by an extractor."""

    path: Path
    text: str = ""
    images: tuple[str, ...] = ()


class OCRBackend(Protocol):
    """Interface implemented by local and vision-based document readers."""

    def read(self, paths: list[Path]) -> list[DocumentContent]: ...


def _open_pages(path: Path) -> list[Any]:
    if not path.is_file():
        raise DocumentError(f"Input document not found: {path}")
    try:
        if path.suffix.lower() == ".pdf":
            from pdf2image import convert_from_path

            return convert_from_path(str(path), dpi=200, fmt="jpeg")
        if path.suffix.lower() in SUPPORTED_IMAGES:
            from PIL import Image

            return [Image.open(path)]
    except Exception as exc:
        raise DocumentError(f"Could not read {path}: {exc}") from exc
    raise DocumentError(f"Unsupported document type: {path.suffix or '(no extension)'}")


class VisionOCR:
    """Send page images to the extraction model for visual reading."""

    def read(self, paths: list[Path]) -> list[DocumentContent]:
        documents: list[DocumentContent] = []
        for path in paths:
            images: list[str] = []
            for page in _open_pages(path):
                buffer = BytesIO()
                page.convert("RGB").save(buffer, format="JPEG", quality=90)
                images.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
            documents.append(DocumentContent(path=path, images=tuple(images)))
        return documents


class PaddleOCRBackend:
    """Run PaddleOCR locally, then pass recognized text to the extractor."""

    def __init__(self) -> None:
        try:
            from paddleocr import PaddleOCR

            self._ocr: Any = PaddleOCR(lang="en")
        except Exception as exc:
            raise DocumentError(
                "PaddleOCR is unavailable. Install the 'paddle' optional dependencies."
            ) from exc

    def read(self, paths: list[Path]) -> list[DocumentContent]:
        try:
            import numpy as np

            documents: list[DocumentContent] = []
            for path in paths:
                page_text: list[str] = []
                for page in _open_pages(path):
                    image = np.asarray(page.convert("RGB"))[:, :, ::-1].copy()
                    result = self._ocr.ocr(image)
                    page_text.append("\n".join(self._recognized_text(result)))
                documents.append(
                    DocumentContent(path=path, text="\n\n--- PAGE BREAK ---\n\n".join(page_text))
                )
            return documents
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError(f"PaddleOCR failed: {exc}") from exc

    @staticmethod
    def _recognized_text(result: Any) -> list[str]:
        """Read text from PaddleOCR 2.x line lists or 3.x structured results."""
        texts: list[str] = []
        for page in result or []:
            payload = getattr(page, "json", None)
            if callable(payload):
                payload = payload()
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, dict) and isinstance(page, dict):
                payload = page
            if isinstance(payload, dict):
                values = payload.get("res", payload).get("rec_texts", [])
                texts.extend(str(value) for value in values if value)
            else:
                texts.extend(str(line[1][0]) for line in page if line and line[1][0])
        return texts


def make_ocr_backend(name: str) -> OCRBackend:
    """Construct an OCR backend by its CLI name."""
    if name == "vision":
        return VisionOCR()
    if name == "paddle":
        return PaddleOCRBackend()
    raise ValueError(f"Unknown OCR backend: {name}")

"""Orchestration for document reading, field extraction, and invoice output."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from .extraction import LLMExtractor
from .model_catalog import DEFAULT_MODEL
from .models import InvoiceData
from .ocr import make_ocr_backend
from .render import complete_calculations, render_invoice


def _reserve_output_path(output_dir: Path, invoice_id: str) -> Path:
    """Create a unique timestamped destination without clobbering existing output."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    index = 1
    while True:
        collision_suffix = f"_{index:02d}" if index > 1 else ""
        path = output_dir / f"CI_{invoice_id}_{timestamp}{collision_suffix}.docx"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            index += 1
            continue
        os.close(descriptor)
        return path


def run_pipeline(
    *,
    lc: Path,
    bills_of_lading: list[Path],
    certificates: list[Path],
    output_dir: Path,
    template: Path,
    ocr_backend: str = "vision",
    model: str = DEFAULT_MODEL,
    client: OpenAI,
) -> tuple[InvoiceData, Path]:
    """Run one end-to-end conversion using a selected OCR backend."""
    source_paths = [lc, *bills_of_lading, *certificates]
    documents = make_ocr_backend(ocr_backend).read(source_paths)
    fields = complete_calculations(LLMExtractor(client=client, model=model).extract(documents))
    invoice_id = re.sub(r"[^\w.-]", "_", fields.documentary_credit_number).strip("_.")
    fallback_id = re.sub(r"[^\w.-]", "_", lc.stem).strip("_.") or "unknown"
    output_path = _reserve_output_path(output_dir, invoice_id or fallback_id)
    try:
        render_invoice(fields, template, output_path)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return fields, output_path

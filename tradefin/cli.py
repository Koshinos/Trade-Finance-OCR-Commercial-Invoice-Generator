"""Command-line interface for Tradefin."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from openai import OpenAI

from .errors import TradefinError
from .model_catalog import DEFAULT_MODEL, SUPPORTED_MODELS
from .pipeline import run_pipeline

LOGGER = logging.getLogger("tradefin")


def build_parser(default_backend: str = "vision") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract trade-document fields and create a Commercial Invoice."
    )
    parser.add_argument("--lc", required=True, type=Path, help="Letter of Credit PDF or image")
    parser.add_argument("--bl", nargs="+", type=Path, default=[], help="Bill of Lading files")
    parser.add_argument("--coa", nargs="+", type=Path, default=[], help="Certificate of Analysis files")
    parser.add_argument("--out", type=Path, default=Path("outputs"), help="Output directory")
    parser.add_argument(
        "--template", type=Path, default=Path("inputs/template.docx.docx"),
        help="docxtpl invoice template",
    )
    parser.add_argument(
        "--ocr-backend", choices=("vision", "paddle"), default=default_backend,
        help="Use GPT vision or local PaddleOCR before field extraction",
    )
    parser.add_argument(
        "--model",
        choices=SUPPORTED_MODELS,
        default=DEFAULT_MODEL,
        help="OpenAI model for extraction",
    )
    parser.add_argument(
        "--json-out", type=Path,
        help="Also save extracted fields as JSON (useful for labeled evaluation)",
    )
    parser.add_argument(
        "--show-fields", action="store_true",
        help="Print extracted fields (may include sensitive trade information)",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, default_backend: str = "vision") -> int:
    """Run the CLI and return a process status code."""
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser(default_backend).parse_args(argv)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        LOGGER.error("Set OPENAI_API_KEY in .env or the environment.")
        return 2
    try:
        fields, output_path = run_pipeline(
            lc=args.lc,
            bills_of_lading=args.bl,
            certificates=args.coa,
            output_dir=args.out,
            template=args.template,
            ocr_backend=args.ocr_backend,
            model=args.model,
            client=OpenAI(api_key=api_key),
        )
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(fields.model_dump_json(indent=2), encoding="utf-8")
        if args.show_fields:
            for name, value in fields.model_dump().items():
                print(f"{name}: {value}")
        LOGGER.info("Commercial Invoice saved to %s", output_path)
        return 0
    except TradefinError as exc:
        LOGGER.error("%s", exc)
        return 1
    except OSError as exc:
        LOGGER.error("Could not write output: %s", exc)
        return 1

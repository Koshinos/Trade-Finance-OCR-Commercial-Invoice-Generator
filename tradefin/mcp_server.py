"""Local MCP tools for Tradefin extraction and evaluation workflows."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from openai import OpenAI

from .evaluation import evaluate, format_report
from .model_catalog import DEFAULT_MODEL, SUPPORTED_MODELS
from .pipeline import run_pipeline

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOLD_DIR = PROJECT_ROOT / "eval" / "goldens"
DEFAULT_PREDICTION_DIR = PROJECT_ROOT / "eval" / "predictions"

server = FastMCP(
    "tradefin",
    instructions=(
        "For evaluation, check status first. To measure a code change, re-extract every labeled case "
        "with its matching sample_id, then score predictions. Extraction sends documents to the configured "
        "OpenAI API model and writes an invoice in outputs/. Never create or change gold labels from "
        "model predictions; report accuracy only when verified labels exist."
    ),
)


def _workspace_path(value: str, *, must_exist: bool = False) -> Path:
    """Resolve a user-supplied path while keeping file access inside this checkout."""
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(PROJECT_ROOT):
        raise ValueError("Paths must stay inside the Tradefin repository.")
    if must_exist and not resolved.is_file():
        raise ValueError(f"File not found in the Tradefin repository: {value}")
    return resolved


def _score_payload(gold_dir: Path, prediction_dir: Path) -> dict[str, object]:
    scores, documents = evaluate(gold_dir, prediction_dir)
    return {
        "documents": documents,
        "report": format_report(scores, documents),
        "fields": {
            name: {
                "correct": score.correct,
                "total": score.total,
                "accuracy": score.accuracy,
            }
            for name, score in scores.items()
        },
    }


def _save_prediction(prediction_dir: Path, sample_id: str, json_content: str) -> Path:
    """Atomically refresh one prediction without following an existing file symlink."""
    path = prediction_dir / f"{sample_id}.json"
    if path.is_symlink():
        raise ValueError(f"Refusing to overwrite a symbolic link: {path.relative_to(PROJECT_ROOT)}")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=prediction_dir,
            prefix=f".{sample_id}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temporary_path = Path(temp_file.name)
            temp_file.write(json_content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


@server.tool(
    title="Get evaluation status",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def get_evaluation_status() -> dict[str, object]:
    """Summarize labeled examples and predictions available in this checkout."""
    gold_dir = _workspace_path("eval/goldens")
    prediction_dir = _workspace_path("eval/predictions")
    gold_files = sorted(gold_dir.glob("*.json")) if gold_dir.is_dir() else []
    prediction_files = (
        sorted(prediction_dir.glob("*.json"))
        if prediction_dir.is_dir()
        else []
    )
    result: dict[str, object] = {
        "gold_documents": len(gold_files),
        "prediction_documents": len(prediction_files),
        "gold_dir": str(DEFAULT_GOLD_DIR.relative_to(PROJECT_ROOT)),
        "prediction_dir": str(DEFAULT_PREDICTION_DIR.relative_to(PROJECT_ROOT)),
    }
    if not gold_files:
        result["status"] = "needs_gold_labels"
        result["message"] = (
            "No verified JSON labels are present. Add manually checked files under eval/goldens; "
            "do not treat model-generated predictions as gold labels."
        )
    else:
        result["status"] = "ready_to_score"
        result["missing_prediction_documents"] = sum(
            not (prediction_dir / item.name).is_file() for item in gold_files
        )
    return result


@server.tool(
    title="Score extraction predictions",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
def score_extraction_predictions(
    gold_dir: str = "eval/goldens",
    prediction_dir: str = "eval/predictions",
) -> dict[str, object]:
    """Score same-named gold and prediction JSON files with field-level exact match."""
    safe_gold_dir = _workspace_path(gold_dir)
    safe_prediction_dir = _workspace_path(prediction_dir)
    return _score_payload(safe_gold_dir, safe_prediction_dir)


@server.tool(
    title="Extract a commercial invoice",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
def extract_invoice(
    lc: str,
    bills_of_lading: list[str] | None = None,
    certificates: list[str] | None = None,
    sample_id: str | None = None,
    model: str = DEFAULT_MODEL,
    ocr_backend: Literal["vision", "paddle"] = "vision",
) -> dict[str, object]:
    """Extract repository documents and save a new DOCX plus a stable eval prediction.

    The source files are sent to the configured OpenAI API model. The output DOCX is written under
    outputs/ with a timestamped, collision-safe filename. The JSON prediction is written to
    eval/predictions/<sample id>.json so it can be compared with a same-named golden. Repeating the
    same sample id replaces that prediction with the latest result.
    """
    if model not in SUPPORTED_MODELS:
        raise ValueError(f"Unsupported model {model!r}. Choose one of: {', '.join(SUPPORTED_MODELS)}")

    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Set OPENAI_API_KEY in the environment or the repository .env file.")

    lc_path = _workspace_path(lc, must_exist=True)
    valid_sample_id = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}"
    if sample_id is not None and not re.fullmatch(valid_sample_id, sample_id):
        raise ValueError(
            "sample_id must start with a letter or digit and contain only letters, "
            "digits, '.', '_' or '-'."
        )
    bl_paths = [_workspace_path(item, must_exist=True) for item in (bills_of_lading or [])]
    coa_paths = [_workspace_path(item, must_exist=True) for item in (certificates or [])]
    template_path = _workspace_path("inputs/template.docx.docx", must_exist=True)
    output_dir = _workspace_path("outputs")
    prediction_dir = _workspace_path("eval/predictions")
    fields, output_path = run_pipeline(
        lc=lc_path,
        bills_of_lading=bl_paths,
        certificates=coa_paths,
        output_dir=output_dir,
        template=template_path,
        ocr_backend=ocr_backend,
        model=model,
        client=OpenAI(api_key=api_key),
    )
    prediction_dir.mkdir(parents=True, exist_ok=True)
    prediction_id = (
        sample_id
        or re.sub(r"[^\w.-]", "_", lc_path.stem).strip("_.")
        or "sample"
    )
    prediction_path = _save_prediction(
        prediction_dir,
        prediction_id,
        fields.model_dump_json(indent=2),
    )
    return {
        "fields": fields.model_dump(),
        "invoice_path": str(output_path.relative_to(PROJECT_ROOT)),
        "prediction_path": str(prediction_path.relative_to(PROJECT_ROOT)),
        "model": model,
        "ocr_backend": ocr_backend,
    }


def main() -> None:
    """Run the MCP server over stdio for local Codex configuration."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

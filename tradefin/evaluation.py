"""Field-level exact-match evaluation for labeled extraction examples."""

from __future__ import annotations

import json
import re
import argparse
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FieldScore:
    correct: int
    total: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


def _normalize(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def evaluate(gold_dir: Path, prediction_dir: Path) -> tuple[dict[str, FieldScore], int]:
    """Compare same-named JSON files and score every labeled field, including blanks."""
    gold_files = sorted(gold_dir.glob("*.json"))
    if not gold_files:
        raise ValueError(f"No gold JSON files found in {gold_dir}")
    scores: dict[str, list[int]] = {}
    for gold_file in gold_files:
        expected = json.loads(gold_file.read_text(encoding="utf-8"))
        prediction_file = prediction_dir / gold_file.name
        predicted = (
            json.loads(prediction_file.read_text(encoding="utf-8"))
            if prediction_file.is_file()
            else {}
        )
        if not isinstance(expected, dict) or not isinstance(predicted, dict):
            raise ValueError(f"Expected JSON objects in {gold_file.name} and its prediction")
        for field, gold_value in expected.items():
            values = scores.setdefault(field, [0, 0])
            values[1] += 1
            values[0] += _normalize(gold_value) == _normalize(predicted.get(field, ""))
    return {name: FieldScore(*counts) for name, counts in sorted(scores.items())}, len(gold_files)


def format_report(scores: dict[str, FieldScore], documents: int) -> str:
    """Format a Markdown report suitable for pasting into project documentation."""
    matched = sum(score.correct for score in scores.values())
    compared = sum(score.total for score in scores.values())
    lines = [
        f"Documents: {documents}",
        f"Overall exact-match accuracy: {matched / compared:.1%} ({matched}/{compared} fields)" if compared else "Overall exact-match accuracy: N/A",
        "",
        "| Field | Accuracy | Correct / labeled |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| `{name}` | {score.accuracy:.1%} | {score.correct}/{score.total} |"
        for name, score in scores.items()
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Score extraction JSON against verified labels.")
    parser.add_argument("--gold", type=Path, default=Path("eval/goldens"))
    parser.add_argument("--predictions", required=True, type=Path)
    args = parser.parse_args()
    try:
        scores, documents = evaluate(args.gold, args.predictions)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(format_report(scores, documents))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

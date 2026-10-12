"""Legacy name for PaddleOCR followed by LLM extraction."""

from tradefin.cli import main

if __name__ == "__main__":
    raise SystemExit(main(default_backend="paddle"))

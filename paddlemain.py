"""Legacy entry point for the PaddleOCR pipeline."""

from tradefin.cli import main

if __name__ == "__main__":
    raise SystemExit(main(default_backend="paddle"))

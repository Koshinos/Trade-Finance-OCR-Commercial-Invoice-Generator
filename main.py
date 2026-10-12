"""Backward-compatible entry point; use ``python -m tradefin`` for new runs."""

from tradefin.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

"""Compatibility alias for the unified Tradefin CLI."""

from tradefin.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

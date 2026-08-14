"""PySide6 entry point for the Windows client.

``client/ui/main_window.py`` (imported lazily inside :func:`run`) is where
the real caption UI lives, so that this module -- and everything it
imports at module scope -- stays importable (for metadata or tooling)
without Qt installed. The CPU test suite does not import this module or
``main_window``. Both are exercised manually on Windows.

Run with:

    python -m client.ui.bootstrap
"""

from __future__ import annotations


def run() -> int:
    """Launch the real caption UI and return the Qt exit code."""
    from client.ui.main_window import run as run_main_window  # noqa: PLC0415

    return run_main_window()


if __name__ == "__main__":
    raise SystemExit(run())

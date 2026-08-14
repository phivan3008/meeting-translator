"""PyInstaller entry point for the Windows client executable.

A separate top-level script (rather than pointing PyInstaller directly at
``client/ui/bootstrap.py``) so the repository root -- not
``client/ui/``, wherever the entry script physically lives -- is what needs
to be on ``sys.path`` for ``client``/``shared`` package imports to resolve.
``scripts/build_windows_client.py`` builds from this file and passes
``--paths`` pointing at the repository root explicitly.
"""

from __future__ import annotations

from client.ui.bootstrap import run

if __name__ == "__main__":
    raise SystemExit(run())

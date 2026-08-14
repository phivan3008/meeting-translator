"""Version metadata consistency.

``shared/version.py``'s ``__version__`` and ``pyproject.toml``'s
``[project] version`` are kept in sync by convention (see
``shared/version.py``'s docstring); this test is the enforcement.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from shared.version import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_pyproject() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_version_is_semantic() -> None:
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)

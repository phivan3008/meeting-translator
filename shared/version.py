"""Single source of truth for the application version.

Semantic versioning (``MAJOR.MINOR.PATCH``). Kept in sync with
``pyproject.toml``'s ``[project] version`` field by convention (verified by
``tests/test_version.py``, which reads both and asserts they match) rather
than generated/templated at build time, per this project's preference for
simple, explicit state over build tooling. See ``docs/DEPLOYMENT.md``'s
"Version metadata and upgrade strategy" section for what a version bump
means for server/client compatibility.
"""

from __future__ import annotations

__version__ = "0.1.0"

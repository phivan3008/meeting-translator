"""Build the Windows client into a distributable executable via PyInstaller.

Usage (on Windows, with the client/windows-audio/packaging extras installed):

    python scripts/build_windows_client.py [--onefile] [--clean]

Requires ``pip install -e ".[client,windows-audio,packaging]"`` first (real
PySide6, PyAudioWPatch and PyInstaller -- none of these are part of the
default ``dev`` extra, since the CPU test suite never needs them; see
``docs/DEPLOYMENT.md``'s "Windows client packaging" section).

Produces ``dist/MeetingTranslator/`` (default, one-directory build -- faster
startup, easier to inspect for troubleshooting) or ``dist/MeetingTranslator.exe``
(with ``--onefile`` -- a single file, slower startup since it self-extracts
to a temp directory first). Both are real PyInstaller builds of
``packaging/entrypoint.py`` -> ``client/ui/bootstrap.py`` -> the real
PySide6 ``MainWindow``; this script does not fabricate a build result.

This script only *builds* the executable. It does not run or verify the
produced .exe against real audio hardware or a real server connection --
that is a separate, staged manual action (see MANUAL_ACTIONS.md) per
CLAUDE.md's "never claim hardware verification from mocks."
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Build a single .exe (self-extracting) instead of a one-directory build.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove PyInstaller's build/ and dist/ output before building.",
    )
    args = parser.parse_args(argv)

    try:
        import PyInstaller.__main__  # noqa: PLC0415
    except ImportError:
        print(
            "error: PyInstaller is required. Install with: "
            'pip install -e ".[client,windows-audio,packaging]"',
            file=sys.stderr,
        )
        return 2

    sys.path.insert(0, str(REPO_ROOT))
    from shared.version import __version__  # noqa: PLC0415, E402

    if args.clean:
        for name in ("build", "dist"):
            path = REPO_ROOT / name
            if path.exists():
                shutil.rmtree(path)

    pyinstaller_args = [
        str(REPO_ROOT / "packaging" / "entrypoint.py"),
        "--name",
        f"MeetingTranslator-{__version__}",
        "--windowed",  # no console window (this is a GUI app)
        "--paths",
        str(REPO_ROOT),
        # pyaudiowpatch is imported lazily inside functions
        # (client/audio/windows_backend.py), so PyInstaller's static
        # import scan needs an explicit hint to bundle it.
        "--hidden-import",
        "pyaudiowpatch",
        "--noconfirm",
    ]
    if args.onefile:
        pyinstaller_args.append("--onefile")

    print(
        f"Building MeetingTranslator v{__version__} ({'onefile' if args.onefile else 'onedir'})..."
    )
    PyInstaller.__main__.run(pyinstaller_args)
    print("\nBuild finished. See dist/ for the output.")
    print(
        "This build has NOT been run or tested against real audio hardware or a real "
        "server -- that verification is a separate manual step."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

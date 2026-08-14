"""Windows audio capture package.

The public interface (:mod:`client.audio.interface`) and core processing
(:mod:`client.audio.types`, :mod:`client.audio.queue`,
:mod:`client.audio.conversion`, :mod:`client.audio.capture`) are pure and
testable on Linux with the fake backend (:mod:`client.audio.fake_backend`).

The real Windows adapter (:mod:`client.audio.windows_backend`) imports
``pyaudiowpatch`` lazily and is only exercised on Windows.
"""

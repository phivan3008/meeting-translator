"""Sliding audio window for bounded-cost streaming partial decode.

Re-decoding the full utterance audio on every partial tick would make decode
cost (and latency) grow without bound as an utterance approaches
``vad_max_utterance_ms``. Once the stable-prefix tracker confirms a leading
portion of the audio is fully decoded (see ``server.asr.stable_prefix``), that
audio can be dropped from the window; a configurable ``overlap_ms`` margin of
already-covered audio is always kept before the confirmed boundary so a word
spanning the trim point is not cut acoustically, and continuity for the
dropped audio is provided by feeding the committed text back to Whisper as
``AsrRequest.previous_text`` conditioning rather than by re-decoding it.

Pure and framework-independent: no asyncio, I/O or ASR backend.
"""

from __future__ import annotations

from server.asr.types import BYTES_PER_MS


class SlidingAudioWindow:
    """Growing PCM buffer for one in-progress utterance's partial decode.

    All ms offsets passed to and returned by this class other than
    :attr:`window_start_ms` are relative to the *current* window (0 at the
    start of the bytes returned by :meth:`window`), matching the timestamps
    faster-whisper reports for a single decode call.
    """

    def __init__(self, *, overlap_ms: int) -> None:
        if overlap_ms < 0:
            raise ValueError("overlap_ms must be >= 0")
        self._overlap_ms = overlap_ms
        self._buffer = bytearray()
        self._window_start_ms = 0

    def append(self, chunk: bytes) -> None:
        """Append newly received audio to the buffer."""
        if chunk:
            self._buffer.extend(chunk)

    @property
    def window_start_ms(self) -> int:
        """Utterance-absolute start time of the currently buffered audio."""
        return self._window_start_ms

    @property
    def buffered_ms(self) -> int:
        return len(self._buffer) // BYTES_PER_MS

    def window(self) -> bytes:
        """Return the audio to decode on the next partial tick."""
        return bytes(self._buffer)

    def advance(self, stable_end_ms: int) -> bool:
        """Drop confirmed audio, keeping ``overlap_ms`` before the boundary.

        ``stable_end_ms`` is window-relative (as returned by
        :meth:`server.asr.stable_prefix.StablePrefixTracker.stable_boundary_ms`).
        Returns ``True`` if audio was actually dropped (the window shifted),
        so the caller can reset the stable-prefix agreement baseline only
        when the window really changed.
        """
        if stable_end_ms <= 0:
            return False
        # Clamp to what is actually buffered: a boundary at or beyond the
        # buffer's own length must never drop more than the buffer holds
        # (which would desynchronize window_start_ms from the real content).
        keep_from_ms = min(max(0, stable_end_ms - self._overlap_ms), self.buffered_ms)
        drop_bytes = keep_from_ms * BYTES_PER_MS
        if drop_bytes <= 0:
            return False
        del self._buffer[:drop_bytes]
        self._window_start_ms += keep_from_ms
        return True

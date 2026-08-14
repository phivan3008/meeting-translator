"""Stable-prefix (local-agreement) text merging for streaming ASR partials.

Pure text logic, independent of Whisper or any ASR backend: merges successive
decode hypotheses for the same in-progress utterance into a monotonically
growing "stable" (committed) prefix and a residual "unstable" suffix, using a
two-consecutive-hypothesis local-agreement policy. Text is committed only once
it agrees, segment-for-segment, across two consecutive decodes of the same
audio window; once committed it never shrinks or changes, even if a later
hypothesis contradicts it. Comparing whole Whisper segments (not raw
characters or whitespace-split words) works uniformly for space-delimited
text (Vietnamese) and non-space-delimited text (Japanese) and avoids
committing a word truncated mid-token.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from server.asr.types import TranscriptionSegment


def _common_prefix_len(a: Sequence[str], b: Sequence[str]) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


@dataclass(frozen=True)
class StablePrefixResult:
    """Merged committed/residual text after one hypothesis update."""

    stable_text: str
    unstable_text: str

    @property
    def display_text(self) -> str:
        return self.stable_text + self.unstable_text


class StablePrefixTracker:
    """Tracks committed (stable) text for one in-progress utterance.

    Call :meth:`update` with each new decode's segments, in order. Committed
    text is monotonic: it only grows, and a later hypothesis that contradicts
    already-committed text cannot rewrite or remove it (protects the display
    from regressing due to a noisy correction).
    """

    def __init__(self) -> None:
        self._committed_text = ""
        self._previous_texts: tuple[str, ...] = ()

    @property
    def committed_text(self) -> str:
        return self._committed_text

    def update(self, segments: Sequence[TranscriptionSegment]) -> StablePrefixResult:
        """Merge a new decode's segments and return the stable/unstable split."""
        current_texts = tuple(segment.text for segment in segments)
        agreed = _common_prefix_len(self._previous_texts, current_texts)
        candidate = "".join(current_texts[:agreed])
        if len(candidate) > len(self._committed_text):
            self._committed_text = candidate
        self._previous_texts = current_texts

        current_full_text = "".join(current_texts)
        if current_full_text.startswith(self._committed_text):
            unstable_text = current_full_text[len(self._committed_text) :]
        else:
            # The new hypothesis contradicts committed text (e.g. right after
            # the audio window shifted). Never regress what is already
            # committed; simply show nothing further until hypotheses agree
            # again on the new window.
            unstable_text = ""
        return StablePrefixResult(stable_text=self._committed_text, unstable_text=unstable_text)

    def stable_boundary_ms(self, segments: Sequence[TranscriptionSegment]) -> int:
        """Window-relative end-ms of the committed prefix within ``segments``.

        ``segments`` must be the same sequence most recently passed to
        :meth:`update`. Conservative: returns the end time of the last
        segment that is fully covered by the committed text, or 0 if none is.
        """
        offset = 0
        boundary_ms = 0
        for segment in segments:
            offset += len(segment.text)
            if offset <= len(self._committed_text):
                boundary_ms = segment.end_ms
            else:
                break
        return boundary_ms

    def reset_window(self) -> None:
        """Forget the same-window agreement baseline after the audio window shifts.

        ``committed_text`` is kept (it never regresses); only the
        previous-hypothesis baseline used to detect new agreement is cleared,
        since a new audio window's segments are not positionally comparable to
        the prior window's. Local agreement simply restarts, as at utterance
        start, for the new window.
        """
        self._previous_texts = ()

    def finalize(self, final_text: str) -> StablePrefixResult:
        """Commit the full final text (used once final ASR reconciles)."""
        self._committed_text = final_text
        self._previous_texts = (final_text,)
        return StablePrefixResult(stable_text=final_text, unstable_text="")

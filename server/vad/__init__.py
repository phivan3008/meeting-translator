"""VAD and utterance segmentation package.

Exposes the model interface, a deterministic scripted model, the Silero adapter,
the pre-roll buffer, configuration/value types, events and the per-stream
utterance state machine.
"""

from __future__ import annotations

from server.vad.events import (
    ResumedSpeech,
    SoftSilence,
    SpeechStarted,
    UtteranceFinalized,
    VadEvent,
    VadEventType,
)
from server.vad.fake import ScriptedVadModel
from server.vad.interface import VadModel
from server.vad.ring_buffer import PreRollBuffer
from server.vad.silero import SileroVadModel
from server.vad.state_machine import UtteranceSegmenter
from server.vad.types import Utterance, VadConfig, VadState

__all__ = [
    "PreRollBuffer",
    "ResumedSpeech",
    "ScriptedVadModel",
    "SileroVadModel",
    "SoftSilence",
    "SpeechStarted",
    "Utterance",
    "UtteranceFinalized",
    "UtteranceSegmenter",
    "VadConfig",
    "VadEvent",
    "VadEventType",
    "VadModel",
    "VadState",
]

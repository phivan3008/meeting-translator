"""Environment-based application settings with validation.

Settings are loaded from process environment variables and an optional local
``.env`` file. No secret values are hard-coded here. Defaults mirror
``.env.example`` and the baseline configuration documented under ``docs/``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Validated application settings.

    All fields are populated from environment variables. Field names map to
    upper-case environment keys (case-insensitive).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---------------------------------------------------------
    app_env: AppEnv = "development"
    log_level: LogLevel = "INFO"

    # --- Server transport ----------------------------------------------------
    server_host: str = "0.0.0.0"
    server_port: int = Field(default=8080, ge=1, le=65535)
    ws_max_packet_bytes: int = Field(default=65536, ge=64, le=8 * 1024 * 1024)
    ws_max_streams_per_session: int = Field(default=8, ge=1, le=255)
    ws_ack_every_packets: int = Field(default=32, ge=1)
    ws_ack_every_ms: int = Field(default=200, ge=1)
    ws_jitter_buffer_capacity: int = Field(default=64, ge=1)
    ws_idle_timeout_ms: int = Field(default=15000, ge=1)
    ws_heartbeat_interval_ms: int = Field(default=5000, ge=1)
    ws_rate_limit_packets_per_sec: float = Field(default=200.0, gt=0.0)
    ws_rate_limit_burst: int = Field(default=400, ge=1)
    # Server-wide concurrent session cap (distinct from
    # ws_max_streams_per_session, which bounds streams *within* one
    # session). Protects against unbounded memory/resource growth from
    # too many simultaneous meetings.
    ws_max_sessions: int = Field(default=500, ge=1)

    # --- Client reconnect/backoff -------------------------------------------
    reconnect_backoff_initial_ms: int = Field(default=250, ge=1)
    reconnect_backoff_max_ms: int = Field(default=10000, ge=1)
    reconnect_backoff_multiplier: float = Field(default=2.0, ge=1.0)
    client_outbound_buffer_frames: int = Field(default=512, ge=1)

    # --- Client UI -------------------------------------------------------------
    # Default server WebSocket URL the PySide6 client connects to. Any auth
    # token is entered by the user at connect time and never persisted (see
    # client/ui/settings_store.py's "no secrets" contract) or stored here.
    client_server_url: str = "ws://localhost:8080/ws/stream"

    # --- Authentication ------------------------------------------------------
    jwt_issuer: str = "meeting-translator"
    jwt_audience: str = "meeting-translator-client"
    jwt_public_key_path: str = ""
    # Signature algorithm for JWT verification. Must be an asymmetric
    # algorithm (RS*/ES*/PS*) -- never "none", and never a symmetric HS*
    # algorithm here (that would let anyone holding the *public* key, which
    # is not secret, forge tokens).
    jwt_algorithm: str = "RS256"
    # Clock-skew tolerance applied to exp/iat/nbf checks.
    jwt_leeway_seconds: int = Field(default=30, ge=0)
    # Development shared token. Empty string allows anonymous access in the
    # development environment only; production must supply a JWT authenticator.
    auth_dev_token: str = ""

    # --- Infrastructure ------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # --- Audio baseline --------------------------------------------------------
    # Fixed wire-format audio frame duration (the client always sends
    # exactly this per binary packet -- see client/audio/types.py's
    # FRAME_DURATION_MS). Drives UtteranceOrchestrator/UtteranceSegmenter's
    # internal per-stream audio-timeline clock.
    audio_frame_ms: int = Field(default=20, ge=1)

    # --- VAD baseline --------------------------------------------------------
    vad_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    vad_speech_start_ms: int = Field(default=160, ge=0)
    vad_min_speech_ms: int = Field(default=250, ge=0)
    vad_soft_silence_ms: int = Field(default=450, ge=0)
    vad_hard_silence_ms: int = Field(default=900, ge=0)
    vad_speech_pad_before_ms: int = Field(default=200, ge=0)
    vad_speech_pad_after_ms: int = Field(default=250, ge=0)
    vad_max_utterance_ms: int = Field(default=15000, ge=1)

    # --- ASR baseline --------------------------------------------------------
    whisper_model: str = "large-v3"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    whisper_final_beam_size: int = Field(default=3, ge=1)
    whisper_partial_beam_size: int = Field(default=1, ge=1)
    whisper_temperature: float = Field(default=0.0, ge=0.0)
    whisper_condition_on_previous_text: bool = True
    whisper_partial_interval_ms: int = Field(default=500, ge=1)
    whisper_audio_overlap_ms: int = Field(default=1500, ge=0)
    asr_final_timeout_ms: int = Field(default=8000, ge=1)

    # --- Translation baseline ------------------------------------------------
    vllm_base_url: str = "http://localhost:8000/v1"
    vllm_api_key: str = "EMPTY"
    vllm_model: str = "qwen3.6-27b-translate"
    translation_timeout_ms: int = Field(default=3000, ge=1)
    translation_max_concurrency: int = Field(default=8, ge=1)
    translation_max_input_tokens: int = Field(default=768, ge=1)
    translation_max_output_tokens: int = Field(default=256, ge=1)
    completeness_enabled: bool = True
    completeness_timeout_ms: int = Field(default=250, ge=1)
    completeness_skip_queue_depth: int = Field(default=4, ge=0)
    completeness_max_tokens: int = Field(default=20, ge=1)
    completeness_min_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    completeness_heuristic_min_speech_ms: int = Field(default=300, ge=0)
    completeness_heuristic_max_unstable_tail_chars: int = Field(default=12, ge=0)
    translation_queue_capacity_per_priority: int = Field(default=16, ge=1)

    # --- Reliability / observability -------------------------------------------
    # Readiness checks a lightweight, best-effort reachability probe against
    # the translation backend when enabled. Off by default so local/CPU-only
    # runs (no vLLM reachable) stay "ready" for basic liveness purposes;
    # production deployments that want readiness to reflect the backend
    # should turn this on.
    readiness_check_translation_backend: bool = False
    readiness_check_timeout_ms: int = Field(default=500, ge=1)
    # Graceful shutdown: how long to wait for active sessions to drain
    # (finish in-flight work and disconnect) before the server proceeds
    # with shutdown regardless.
    shutdown_drain_timeout_ms: int = Field(default=10000, ge=0)
    # Circuit breaker (translation and ASR backends): trips to "open" after
    # this many consecutive failures, short-circuiting further attempts
    # (returning a fast, typed failure instead of hammering an overloaded
    # backend) until reset_timeout_ms elapses, then allows one trial
    # ("half-open") call to decide whether to close again.
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1)
    circuit_breaker_reset_timeout_ms: int = Field(default=30000, ge=1)

    # --- Privacy toggles -----------------------------------------------------
    store_raw_audio: bool = False
    log_transcript_content: bool = False
    log_translation_content: bool = False

    @field_validator("vad_hard_silence_ms")
    @classmethod
    def _hard_silence_after_soft(cls, value: int, info: object) -> int:
        # Pydantic v2 passes a ValidationInfo with .data holding prior fields.
        data = getattr(info, "data", {})
        soft = data.get("vad_soft_silence_ms")
        if soft is not None and value < soft:
            raise ValueError(
                "vad_hard_silence_ms must be greater than or equal to vad_soft_silence_ms"
            )
        return value

    @property
    def is_production(self) -> bool:
        """Return True when running in the production environment."""
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached, validated settings instance."""
    return Settings()

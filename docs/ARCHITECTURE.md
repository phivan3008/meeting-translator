# System Architecture

## Components

### Windows client

- Device manager
- Microphone capture adapter
- WASAPI loopback capture adapter
- Audio normalization worker
- Frame packetizer
- WebSocket transport
- Reconnect and resend manager
- Event store
- PySide6 caption UI

### Application server

- FastAPI WebSocket gateway
- Authentication interface
- Session manager
- Stream context manager
- Jitter and ring buffers
- Silero VAD adapter
- Utterance state machine
- faster-whisper ASR adapter
- Stable-prefix processor
- Final ASR reconciler
- Translation queue
- vLLM client
- Prompt and glossary builder
- Translation validator
- Event publisher
- Metrics and health endpoints

### Model server

- Local Qwen/Qwen3.6-27B-FP8 files
- vLLM OpenAI-compatible server
- Text-only mode
- Thinking disabled
- Bounded concurrency

## Processing pipeline

```text
Microphone and loopback capture
  -> independent client queues
  -> mono 16 kHz PCM S16LE
  -> binary WebSocket packets
  -> per-stream jitter buffer
  -> per-stream Silero VAD
  -> utterance audio buffer
  -> periodic faster-whisper partial decode
  -> stable-prefix update
  -> transcription.partial event
  -> VAD/heuristic/optional completeness decision
  -> final faster-whisper reconciliation
  -> prioritized translation queue
  -> Qwen3.6-27B-FP8 through vLLM
  -> validation and optional retry
  -> utterance.final event
```

## Concurrency model

- PyAudio callbacks only enqueue raw chunks.
- Client normalization and network sending run outside callbacks.
- FastAPI event loop performs transport coordination only.
- CPU-heavy VAD and blocking model calls run in dedicated workers/executors.
- ASR requests are scheduled separately from translation requests.
- Translation and completeness share vLLM but use distinct priorities.
- All queues are bounded and expose depth and rejection metrics.

## GPU allocation

Recommended:

- GPU 0: faster-whisper large-v3.
- GPU 1: Qwen3.6-27B-FP8 through vLLM.

Do not assume Whisper large-v3 and Qwen3.6-27B-FP8 can safely coexist on one 48 GB GPU under production load.

## Translation server baseline

Use a pinned vLLM version proven compatible with the selected CUDA and GPU. A baseline launch configuration is:

```bash
vllm serve /models/Qwen3.6-27B-FP8 \
  --served-model-name qwen3.6-27b-translate \
  --host 0.0.0.0 \
  --port 8000 \
  --language-model-only \
  --max-model-len 4096 \
  --max-num-seqs 32 \
  --max-num-batched-tokens 4096 \
  --gpu-memory-utilization 0.88 \
  --enable-prefix-caching \
  --trust-remote-code \
  --default-chat-template-kwargs '{"enable_thinking": false}'
```

MTP speculative decoding is an optional benchmark feature, not a mandatory default.

## VAD baseline configuration

```yaml
threshold: 0.50
speech_start_ms: 160
min_speech_ms: 250
soft_silence_ms: 450
hard_silence_ms: 900
speech_pad_before_ms: 200
speech_pad_after_ms: 250
max_utterance_ms: 15000
```

## ASR baseline configuration

```yaml
model: large-v3
device: cuda
compute_type: float16
partial_beam_size: 1
final_beam_size: 3
partial_interval_ms: 500
audio_overlap_ms: 1500
condition_on_previous_text: true
```

## Translation baseline configuration

```yaml
model: qwen3.6-27b-translate
temperature: 0.0
top_p: 1.0
max_input_tokens: 768
max_output_tokens: 256
request_timeout_ms: 3000
retry_count: 1
thinking: false
stream: false
```

## Priority policy

ASR scheduler:

1. Final ASR
2. Partial ASR

vLLM scheduler at application level:

1. Final translation
2. Translation retry
3. Completeness check

Completeness must be skipped when queue pressure exceeds the configured threshold.

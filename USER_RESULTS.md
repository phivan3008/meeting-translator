# User-Provided Verification Results

File này lưu tóm tắt kết quả kiểm thử thủ công do người dùng cung cấp. Không lưu secret hoặc nội dung cuộc họp nhạy cảm.

## Results

### GPU-ASR-001

- Date: 2026-08-10
- Environment: GPU server (containerized/Kubernetes pod; PVC-backed
  `/workspace`, overlay root filesystem, nvidia-fabricmanager present).
- Command summary:
  - `nvidia-smi`
  - `nvcc --version`
  - `free -h ; nproc`
  - `df -h .`
  - `python3 --version`
- Exit status: no errors observed for any command.
- Result: PASSED
- Relevant output summary:
  - GPU: 1x NVIDIA H100 80GB HBM3, 0 MiB / 81559 MiB used, driver 580.82.07,
    CUDA (driver) 13.0, no other processes running on the GPU.
  - `nvcc`: CUDA 12.8 toolkit (release 12.8, V12.8.93) present.
  - Host: 128 logical CPUs, 1.5 TiB total RAM, 696 GiB free, no swap.
  - Disk: container overlay 24T total / 18T avail; persistent `/workspace` PVC
    mount 300G total / 156G avail — both comfortably sufficient for the
    faster-whisper large-v3 weights (~3 GB).
  - Python: 3.11.13 (meets the 3.11+ requirement).
  - No errors, missing tools or insufficient-resource warnings reported.
- Redacted raw output file, if any: none (full command output pasted inline,
  no secrets or hostnames present).
- Follow-up: GPU ASR host confirmed capable of hosting faster-whisper
  large-v3. Marked PASSED in `MANUAL_ACTIONS.md`. Next step was GPU-ASR-002
  (install the faster-whisper package only into a persistent venv).

### GPU-ASR-002

- Date: 2026-08-11
- Environment: GPU server, `/workspace/meetting-translator/.venv-asr` virtual
  environment (confirmed exact path via GPU-ASR-003's `which python` output;
  earlier actions assumed `/workspace/.venv-asr`).
- Command summary:
  - `pip install "faster-whisper>=1.0,<2"`
  - `python -c "import faster_whisper; print(...)"`
  - `python -c "import torch; print(...)"`
- Exit status: install succeeded; the `torch` import command failed.
- Result: INCONCLUSIVE (the action itself was flawed, not the environment)
- Relevant output summary:
  - `faster-whisper` installed at version 1.2.1.
  - `torch` import raised `ModuleNotFoundError: No module named 'torch'`.
- Redacted raw output file, if any: none.
- Follow-up: The `torch` check in GPU-ASR-002 was incorrect — `faster-whisper`
  executes inference through CTranslate2, not PyTorch, and the project's
  `pyproject.toml` `gpu` extra pins only `faster-whisper>=1.0,<2` with no
  PyTorch requirement. Missing `torch` is expected and not a failure signal.
  GPU-ASR-002 is marked INCONCLUSIVE/superseded in `MANUAL_ACTIONS.md`.
  GPU-ASR-003 checks GPU visibility through `ctranslate2` directly instead.

### GPU-ASR-003

- Date: 2026-08-11
- Environment: GPU server, `/workspace/meetting-translator/.venv-asr`.
- Command summary:
  - `python -c "import ctranslate2; print(...__version__)"`
  - `python -c "import ctranslate2; print(...get_cuda_device_count())"`
  - `which python`, `python --version`, `pip --version`, `pip list`
  - `nvidia-smi`
  - `python -c "import ctranslate2, os; print(os.path.dirname(...))"`
  - `ldconfig -p | grep -i -E "cudnn|cublas|cudart"`
- Exit status: no errors observed for any command.
- Result: PASSED (for what it tests — see follow-up)
- Relevant output summary:
  - `ctranslate2` 4.8.1; `cuda_device_count()` = 1.
  - Active interpreter: `/workspace/meetting-translator/.venv-asr/bin/python`,
    Python 3.11.13, pip 26.2.1. Installed set includes `faster-whisper`
    1.2.1, `ctranslate2` 4.8.1, `numpy` 2.4.6, `onnxruntime` 1.28.0,
    `huggingface_hub` 1.27.0, `tokenizers` 0.23.1, `av` 18.0.0, and their
    transitive deps — no `torch` and no `nvidia-cudnn-cu12`/similar package.
  - `nvidia-smi`: same H100 80GB as GPU-ASR-001, 0 MiB used, driver 580.82.07,
    CUDA 13.0, no processes.
  - `ldconfig` grep matched `libcudart.so(.12)`, `libcublas.so(.12)` and
    `libcublasLt.so(.12)` under `/usr/local/cuda/targets/x86_64-linux/lib/`.
    No `libcudnn*` entry appeared in the grep output.
- Redacted raw output file, if any: none.
- Follow-up: By this action's own stated success criteria, this passes —
  `cuda_device_count` is 1 (not 0), so the missing `cudnn` match in
  `ldconfig` is not treated as disqualifying. This confirms CTranslate2 can
  see and enumerate the GPU, and confirms the real venv path is
  `/workspace/meetting-translator/.venv-asr` (corrected from the
  `/workspace/.venv-asr` assumed in GPU-ASR-002/003's prepared commands).
  However, enumerating a device is not the same as a model successfully
  loading and decoding — cuDNN could still be missing (or simply not visible
  to `ldconfig`, e.g. bundled inside the `ctranslate2` wheel) and only
  surface as an error when a real forward pass runs. GPU ASR verification
  therefore remains HARDWARE_PENDING. GPU-ASR-004 runs an actual model load
  and one decode call to resolve this open question.

### GPU-ASR-004

- Date: 2026-08-11
- Environment: GPU server, `/workspace/meetting-translator/.venv-asr`.
- Command summary:
  - `python /tmp/asr_smoke_test.py` (loads `large-v3` on cuda/float16,
    synthesizes a 3s 440 Hz tone, runs one `transcribe()` call)
  - `python /tmp/model_info.py` (records the cached model revision via
    `huggingface_hub.scan_cache_dir()`)
- Exit status: no errors observed for either command.
- Result: PASSED
- Relevant output summary:
  - `model_load_seconds=3.66`, `decode_seconds=0.29`.
  - `detected_language=ja probability=1.000`, `segment_count=1` (not
    meaningful — input was a pure tone, no real speech).
  - `OK: model loaded and decode call completed without error`.
  - Model revision: `Systran/faster-whisper-large-v3` @
    `edaa852ec7e145841d8ffdb056a99866b5f0a478`, `size_on_disk=3090835702`
    bytes (~2.88 GiB).
- Redacted raw output file, if any: none.
- Follow-up: This is a clean pass by the action's own success criteria — a
  real `large-v3` model load and a real GPU decode both completed with no
  CUDA/cuDNN/cuBLAS exception. This resolves the open question from
  GPU-ASR-003 (missing `libcudnn` in `ldconfig`): whatever the actual
  dependency resolution is (e.g. bundled inside the `ctranslate2` wheel), it
  works in practice on this host. GPU ASR verification remains
  HARDWARE_PENDING overall (this test used synthetic audio, not real
  speech, so transcription plausibility is still unverified).
  GPU-ASR-005 (WAITING_FOR_USER) runs the project's actual `WhisperAsrModel`
  adapter against two short real-speech samples (vi, ja) to get a first
  plausibility signal.

### GPU-ASR-005

- Date: 2026-08-11
- Environment: GPU server, `/workspace/meetting-translator/.venv-asr`.
- Command summary:
  - `PYTHONPATH=/workspace/meetting-translator python /tmp/asr_real_speech_test.py`
    against real `vi_sample.wav` (~28s) and `ja_sample.wav` (~20s) recordings.
- Exit status: no errors observed.
- Result: PASSED (2026-08-12: user confirmed "yes, the printed text is a
  roughly accurate rendering of what i said" for both clips)
- Relevant output summary:
  - `vi` (`vi_sample.wav`): `duration_ms=28000`, `segments=7`. Text is fluent,
    coherent Vietnamese describing a company profile (a biotech/agriculture
    seed company founded in Đà Lạt in 1989, expansion into hybrid seed
    business in 1994).
  - `ja` (`ja_sample.wav`): `duration_ms=20000`, `segments=8`. Text is fluent,
    coherent Japanese in a textbook sentence-pattern style (交番, 案内書, 駅の
    トイレ example sentences).
- Redacted raw output file, if any: none (transcript text itself is the
  content; no secrets present, but see follow-up on sensitivity note below).
- Follow-up: Both outputs meet the action's objective success indicators —
  no exception for either language, `segments > 0` for both, and the text is
  linguistically well-formed in each target language — and the user has now
  confirmed the ground-truth criterion (roughly accurate for both clips).
  GPU-ASR-005 is PASSED and closed. This is the first hardware confirmation
  that the project's own `WhisperAsrModel` adapter, not just the bare
  faster-whisper/ctranslate2 libraries, produces plausible real transcripts
  in both target languages. It remains a two-sample plausibility check, not
  a scored accuracy/latency benchmark, and `FinalTranscriber` is still not
  wired into the live gateway/VAD ingest path — both are separate, later
  work.

### GPU-TRANSLATE-001

- Date: 2026-08-12
- Environment: `/workspace/meetting-translator` -- the same physical host
  used for the ASR GPU work (`GPU-ASR-001`-`GPU-ASR-005`).
- Command summary:
  - `nvidia-smi`
  - `nvcc --version`
  - `free -h ; nproc`
  - `df -h .`
  - Step 5 (Docker/NVIDIA Container Toolkit check) intentionally skipped:
    user intends the bare-process `vllm serve` launch path, which does not
    need Docker.
- Exit status: no errors observed for steps 1-4.
- Result: PASSED
- Relevant output summary:
  - GPU: 1x NVIDIA H100 80GB HBM3, 0 MiB / 81559 MiB used, driver
    580.82.07, CUDA (driver) 13.0, no running processes.
  - `nvcc`: CUDA 12.8 toolkit (release 12.8, V12.8.93) -- same as
    GPU-ASR-001.
  - Host: 128 logical CPUs, 1.5 TiB total RAM, 596 GiB free, no swap --
    same host as GPU-ASR-001.
  - Disk: persistent `/workspace` PVC 300G total, 155G avail (9G less than
    at GPU-ASR-001's 2026-08-10 check, consistent with the ~2.88 GiB
    Whisper `large-v3` download plus other interim usage).
  - No errors, missing tools or insufficient-resource warnings reported.
- Redacted raw output file, if any: none.
- Follow-up: This action's objective success indicators are all met --
  sufficient VRAM (80 GB total, fully idle), ample RAM/CPU, and sufficient
  disk headroom (155G free vs. the officially published ~30.9 GB model
  size). One finding worth flagging explicitly rather than silently
  accepting: this host has only one GPU, and it is the *same* GPU already
  used for ASR -- `docs/ARCHITECTURE.md` recommends `Whisper large-v3` on
  one GPU and `Qwen3.6-27B-FP8` on a separate GPU, and explicitly cautions
  "do not assume Whisper large-v3 and Qwen3.6-27B-FP8 can safely coexist on
  one 48 GB GPU under production load." That caution was written with a
  48 GB GPU in mind; this is an 80 GB H100, and a back-of-envelope budget
  (Whisper `large-v3` float16 ~3 GB + Qwen3.6-27B-FP8 weights ~27-31 GB +
  vLLM KV cache/activations, likely well under 40 GB combined for
  reasonable `--max-model-len`/`--max-num-seqs` settings used together)
  leaves meaningful headroom -- so single-GPU co-location is plausible here,
  but this is a genuine capacity-planning judgment call for production load
  (both models loaded and serving concurrently), not something to assume
  silently. Flagged for the user's awareness; not a blocker for proceeding
  to GPU-TRANSLATE-002 (model download), since download doesn't depend on
  the final co-location decision.

### GPU-TRANSLATE-002

- Date: 2026-08-12
- Environment: Same host as GPU-TRANSLATE-001,
  `/workspace/meetting-translator/.venv-translate`.
- Command summary:
  - `python3 -m venv .venv-translate` + `pip install "huggingface_hub[cli]>=0.24"`
    (commands 1-2, completed normally per the user's report).
  - `python /tmp/download_qwen.py` (resolves revision via `HfApi`, then
    `snapshot_download`s the repo).
  - `du -sh /workspace/meetting-translator/models/Qwen3.6-27B-FP8`
- Exit status: no exception/traceback for any command.
- Result: PASSED
- Relevant output summary:
  - `repo_id=Qwen/Qwen3.6-27B-FP8`,
    `revision_sha=e89b16ebf1988b3d6befa7de50abc2d76f26eb09`.
  - Download: 80 files fetched in 8m11s; tool-reported completion
    "30.9GB / 30.9GB" at up to 193MB/s.
  - `du -sh`: `29G` on disk.
- Redacted raw output file, if any: none.
- Follow-up: Clean pass by the action's own success criteria -- no
  exception, a resolved revision SHA was printed, and the on-disk size
  (29G via `du -sh`, block-size-based) is consistent with the download
  tool's own "30.9GB / 30.9GB complete" report (GiB-vs-GB and filesystem
  block accounting explain the small difference; this is not evidence of a
  partial/truncated download, since the tool's own progress reporting
  already confirmed full completion). GPU-TRANSLATE-003 installs `vllm`
  into this venv and launches it as a server over these weights.

### GPU-TRANSLATE-003

- Date: 2026-08-12
- Environment: Same host, `/workspace/meetting-translator/.venv-translate`.
- Command summary:
  - `pip install vllm` (command 1, completed normally).
  - `nohup vllm serve /workspace/meetting-translator/models/Qwen3.6-27B-FP8 ...`
    (command 2, backgrounded launch).
  - Log file saved locally by the user at `vllm_serve.log` and read from
    the local project directory (not read from the GPU server directly).
- Exit status: command 1 normal; command 2's server process crashed during
  startup (commands 3-4 not meaningfully run since the process had already
  exited).
- Result: FAILED
- Relevant output summary (from `vllm_serve.log`):
  - vLLM 0.27.1 started, resolved architecture `Qwen3_5ForConditionalGeneration`,
    began loading the model, selected FlashAttention v3 and
    FlashInfer-based kernels for FP8/top-k/top-p.
  - `EngineCore failed to start`. Traceback bottoms out at
    `flashinfer/comm/fd_exchange.py:55`:
    `TypeError: type 'array.array' is not subscriptable`, raised while
    importing `flashinfer.comm` as part of vLLM's `AllReduceFusionPass`
    (`vllm/compilation/passes/fusion/allreduce_rms_fusion.py`), itself
    imported while constructing `TorchCompileWithNoGuardsWrapper` for the
    model's `torch.compile` backend.
  - `APIServer` then raised `RuntimeError: Engine core initialization
    failed.` and exited.
- Redacted raw output file, if any: none (log contained no secrets --
  paths, package versions and a Python traceback only).
- Follow-up: Root-caused via the traceback plus reading vLLM's own source
  on GitHub (`vllm/compilation/decorators.py`,
  `vllm/compilation/wrapper.py`): this is a genuine bug in the installed
  `flashinfer` package (an invalid `array.array[int]` type annotation that
  is evaluated eagerly at import time and always fails, since `array.array`
  has no `__class_getitem__`), not anything caused by this project, the
  model download, or the host. `--enforce-eager` sets
  `compilation_config.mode = CompilationMode.NONE`, which makes vLLM's own
  `do_not_compile` check short-circuit `TorchCompileWithNoGuardsWrapper`
  construction before `init_backend()` (and therefore the broken import)
  is ever reached -- confirmed by reading that exact conditional in vLLM's
  source, not assumed. GPU-TRANSLATE-004 retries with `--enforce-eager`
  added; the only known cost is disabling `torch.compile`/CUDA graph
  capture (slower inference, not a correctness issue).

### GPU-TRANSLATE-004

- Date: 2026-08-12
- Environment: Same host, `/workspace/meetting-translator/.venv-translate`.
- Command summary:
  - `pgrep -fa "vllm serve"` (command 1, confirmed no lingering process).
  - `nohup vllm serve ... --enforce-eager ...` (command 2, backgrounded
    relaunch with `--enforce-eager` added).
  - Log file saved locally by the user at `vllm_serve.log` (overwritten
    with this attempt's output) and read from the local project directory.
- Exit status: command 1 normal; command 2's server process crashed during
  startup, further along than GPU-TRANSLATE-003 (commands 3-4 not
  meaningfully run since the process had already exited).
- Result: FAILED (real progress, different failure point)
- Relevant output summary (from `vllm_serve.log`):
  - `enforce_eager: True` confirmed in the printed args; log explicitly
    shows "Enforce eager set, disabling torch.compile and CUDAGraphs" and
    "Cudagraph is disabled under eager mode" -- the fix from
    GPU-TRANSLATE-004's own design worked for its intended target.
  - Model construction succeeded this time: "Loading weights took 17.06
    seconds", "Model loading took 27.67 GiB memory and 23.710028 seconds".
  - KV cache computed successfully: "Available KV cache memory: 41.03 GiB",
    "GPU KV cache size: 292,522 tokens", "Maximum concurrency for 4,096
    tokens per request: 71.42x".
  - Then: `EngineCore failed to start` again, same
    `TypeError: type 'array.array' is not subscriptable` at
    `flashinfer/comm/fd_exchange.py:55`, but via a different call stack
    this time: `_initialize_kv_caches` -> `compile_or_warm_up_model` ->
    `kernel_warmup` -> `vllm.model_executor.warmup.minimax_m3_msa_warmup`
    (MiniMax-M3-specific code, unrelated to the Qwen3.5 model being served)
    -> `vllm.model_executor.layers.fused_allreduce_gemma_rms_norm` ->
    `vllm.compilation.passes.fusion.allreduce_rms_fusion` ->
    `flashinfer.comm` -> same broken line.
  - `APIServer` again raised `RuntimeError: Engine core initialization
    failed.` and exited.
- Redacted raw output file, if any: none (log contained no secrets --
  paths, package versions, timings and a Python traceback only).
- Follow-up: `--enforce-eager` correctly fixed the specific crash point it
  targeted (confirmed: model construction and KV-cache sizing both
  completed, which never happened before). But a second, independent code
  path (`kernel_warmup`'s unconditional MiniMax-M3 import) hits the exact
  same underlying `flashinfer` bug via a different route. Since there could
  be further such paths, chasing each one individually with launch flags is
  not a scalable fix -- GPU-TRANSLATE-005 instead patches the one broken
  line in the installed `flashinfer` package directly (quoting the invalid
  `array.array[int]` annotation as a string so it is never evaluated,
  leaving the function's actual behavior unchanged), which should resolve
  every import path that hits this specific bug at once.

### GPU-TRANSLATE-005

- Date: 2026-08-12
- Environment: Same host, `/workspace/meetting-translator/.venv-translate`.
- Command summary:
  - `pgrep -fa "vllm serve"` (command 1: no lingering process).
  - `/tmp/patch_flashinfer.py` (command 2: patches the broken annotation
    line in the installed `flashinfer` package).
  - `nohup vllm serve ... --enforce-eager ...` (commands 3-4: relaunch,
    same flags as GPU-TRANSLATE-004).
  - `nvidia-smi --query-gpu=memory.used,memory.total --format=csv`
    (command 5).
- Exit status: no exception/traceback for any command.
- Result: PASSED
- Relevant output summary:
  - Command 2: `patched OK`.
  - Commands 3-4 (server log): "Started server process [1643064]",
    "Waiting for application startup.", "Application startup complete.",
    "API server: HTTP server started".
  - Command 5: `72237 MiB, 81559 MiB` (used/total).
- Redacted raw output file, if any: none.
- Follow-up: Clean pass -- the direct patch resolved every remaining
  `flashinfer.comm` import path (only one was hit this time, none
  recurred), and the server reached full startup for the first time across
  five launch-related actions. GPU memory in use (72237 MiB) is consistent
  with weights (~27.67 GiB / ~28,340 MiB) plus KV cache
  (~41.03 GiB / ~42,020 MiB) both resident, no OOM. This is process-level
  confirmation only (the server started); GPU-TRANSLATE-006 checks it
  actually answers HTTP requests correctly.

### GPU-TRANSLATE-006

- Date: 2026-08-12
- Environment: Same host, vLLM server from GPU-TRANSLATE-005 running on
  port 8000.
- Command summary:
  - `curl -s -o NUL -w "http_status=%{http_code}`n" http://localhost:8000/health`
  - `curl -s http://localhost:8000/v1/models`
- Exit status: no error, timeout or unexpected status code for either
  command.
- Result: PASSED
- Relevant output summary:
  - Health: `http_status=200`.
  - Models: `{"object":"list","data":[{"id":"qwen3.6-27b-translate",...,"root":"/workspace/meetting-translator/models/Qwen3.6-27B-FP8","max_model_len":4096,...}]}`.
- Redacted raw output file, if any: none.
- Follow-up: Clean pass. Served model id, root path and `max_model_len`
  all match the GPU-TRANSLATE-005 launch config exactly. This confirms the
  server answers OpenAI-compatible HTTP requests correctly at the
  protocol level; GPU-TRANSLATE-007 sends a real translation request
  through the project's own prompt-building code to check output
  plausibility.

### GPU-TRANSLATE-007

- Date: 2026-08-12
- Environment: GPU server, `/workspace/meetting-translator/.venv-translate`;
  vLLM server from GPU-TRANSLATE-005 running on port 8000.
- Command summary:
  - `PYTHONPATH=/workspace/meetting-translator python /tmp/translate_smoke_test.py`
    (uses `server.translation.prompts.build_system_prompt`/
    `build_user_content` and `server.translation.types.TranslationConfig`
    against `/v1/chat/completions` via `urllib.request`).
- Exit status: no exception/traceback.
- Result: PASSED
- Relevant output summary:
  - JA->VI: source "来週のリリースについて確認したいです。" (I'd like to
    confirm about next week's release) -> translated "Tôi muốn xác nhận về
    bản phát hành vào tuần tới."
  - VI->JA: source "Tôi muốn xác nhận về đợt phát hành vào tuần tới." ->
    translated "来週のリリースについて確認したいのですが。"
  - vLLM engine log: two `POST /v1/chat/completions HTTP/1.1" 200 OK`
    entries, non-zero generation throughput (0.5-1.7 tokens/s), `GPU KV
    cache usage: 0.5%` during the run -- confirms real generation, not an
    empty/cached response.
  - Both outputs non-empty, correctly scripted (Vietnamese diacritics;
    Japanese kana/kanji), no forbidden-prefix label, no pathological
    repetition.
- Redacted raw output file, if any: none (throwaway example sentences, no
  sensitive content).
- Follow-up: Claude's own linguistic read (fluent in both languages): both
  translations are accurate, natural renderings of the source meaning in
  each direction. The user's report did not include an explicit first
  -person plausibility verdict (unlike GPU-ASR-005's "yes, the printed text
  is a roughly accurate rendering"); PASSED here rests on the technical
  success indicators (HTTP 200, non-empty, correct script, no forbidden
  prefix/repetition, real generation confirmed in the engine log) plus
  Claude's linguistic assessment, not an explicit user judgment call --
  flag if either translation reads as wrong to a native speaker. This was
  the last of Phase 07's staged GPU checkpoints; no further
  translation-specific manual action is currently pending.

### WINDOWS-UI-001

- Date: 2026-08-12
- Environment: Windows, PC Local, project root, new `.venv-ui`
  (`pip install -e ".[client]"` + `pip install -e ".[windows-audio]"`),
  Python 3.12 (per the traceback's path:
  `AppData\Local\Programs\Python\Python312`).
- Command summary:
  - `python -m client.ui.bootstrap`
- Exit status: app launched with no exception. Basic smoke test (window,
  device dropdowns, selection/toggling/preset switching, Tab navigation,
  caption font, settings persistence across relaunch) all reported OK.
  Connect/Disconnect flow FAILED with exceptions in both device patterns
  tested.
- Result: FAILED (Connect/Disconnect flow only; basic smoke test PASSED).
  Root-caused and fixed -- see `MANUAL_ACTIONS.md`'s `WINDOWS-UI-001`
  completed entry for the full analysis and `WINDOWS-UI-002` for the
  re-verification action.
- Relevant output summary (from the user's pasted terminal log,
  reproduced faithfully; some interleaving between the background
  thread's traceback and the main thread's repeated `_drain_capture`
  tracebacks was present in the original, consistent with the two-bug
  root cause below):
  - Pattern 1 (mic + loopback both enabled) and Pattern 2 (loopback only)
    both hit, on `Connect`: `Exception in thread session-controller: ...
    File "client/transport/sender.py", line 249, in connect ...
    File "client/transport/sender.py", line 280, in _websockets_connect
    ... from websockets.asyncio.client import connect ...
    ModuleNotFoundError: No module named 'websockets.asyncio'`.
  - Repeated (once per ~20ms capture-timer tick) after that:
    `File "client/ui/main_window.py", line 387, in _drain_capture ...
    File "client/ui/session_controller.py", line 143, in send_audio ...
    loop.call_soon_threadsafe(...) ... RuntimeError: Event loop is
    closed`.
  - Clicking "Disconnect" produced the same `RuntimeError: Event loop is
    closed`, from `session_controller.py` line 132 (`stop()`), and the
    button never reverted to "Connect".
  - Closing the app window produced the same error surfaced through Qt's
    `closeEvent` override
    (`Error calling Python override of QMainWindow::closeEvent(): ...
    RuntimeError: Event loop is closed`).
  - Step 4 (optional connected smoke test): not run (pending, per the
    user).
- Redacted raw output file, if any: none (the pasted terminal log
  contained only local file paths and Python tracebacks, no secrets or
  hostnames).
- Follow-up: Two real bugs found and fixed (full detail in
  `MANUAL_ACTIONS.md`): (1) `client/transport/sender.py` used a
  `websockets` import path (`websockets.asyncio.client`) that does not
  exist in the pinned `websockets>=12,<13` range -- switched to the
  stable top-level `websockets.connect`. (2) `SessionController`/
  `MainWindow` did not detect a dead background thread, so every
  subsequent `send_audio`/`stop()` call kept hitting the same closed
  event loop -- `SessionController.is_running` now checks
  `Thread.is_alive()`, `stop()`/`send_audio()` no longer touch a dead
  loop, and a new `on_fatal_error` callback auto-cleans-up the UI state
  once instead of raising on every timer tick. 4 new regression tests
  added; full local suite (342 tests), ruff and mypy re-verified clean.
  `WINDOWS-UI-002` is the next action, re-testing the same Connect/
  Disconnect flow plus (optionally) a real connected session against a
  local dev server.

### WINDOWS-UI-002

- Date: 2026-08-13
- Environment: Windows, PC Local, same `.venv-ui` as `WINDOWS-UI-001`
  reused; second terminal with `.venv-server` running the local dev
  server (`uvicorn server.app:app --host 0.0.0.0 --port 8080`) for Test B.
- Command summary:
  - `python -m client.ui.bootstrap`
  - `uvicorn server.app:app --host 0.0.0.0 --port 8080` (second terminal)
- Exit status: no exception/traceback for either test.
- Result: PASSED (both Test A and Test B met their stated success
  criteria). One separately-tracked finding surfaced from the server log
  (not a failure of this action) -- see below and `WINDOWS-UI-003`.
- Relevant output summary:
  - Test A (no server): both device-enabled patterns from
    `WINDOWS-UI-001`'s report, plus closing the app while connected, all
    updated the button/state label correctly with no tracebacks in the
    terminal.
  - Test B (with server): state reached "connected". Disconnect-after
    -connected worked cleanly.
  - Server terminal log (pasted by the user):
    ```
    INFO:     Started server process [1500]
    INFO:     Waiting for application startup.
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
    INFO:     connection open
    INFO:     127.0.0.1:54706 - "WebSocket /ws/stream" [accepted]
    2026-08-13 08:33:38,201 INFO server.transport.gateway session meeting-e247dcc189f9 idle timeout
    INFO:     connection open
    INFO:     127.0.0.1:49560 - "WebSocket /ws/stream" [accepted]
    INFO:     connection open
    INFO:     127.0.0.1:63917 - "WebSocket /ws/stream" [accepted]
    2026-08-13 08:33:59,886 INFO server.transport.gateway session meeting-6540c917e8c2 idle timeout
    2026-08-13 08:34:12,969 INFO server.transport.gateway session meeting-59b559b55797 idle timeout
    INFO:     Shutting down
    INFO:     Waiting for application shutdown.
    INFO:     Application shutdown complete.
    INFO:     Finished server process [1500]
    ```
    Three separate sessions, each ending in `idle timeout`
    (`ws_idle_timeout_ms`, 15s of receiving nothing at all) rather than a
    clean client-initiated close.
- Redacted raw output file, if any: none (log contains only local
  loopback addresses and internally-generated session ids, no secrets).
- Follow-up: `server/transport/gateway.py`'s idle-timeout loop resets on
  receiving *any* message (`await asyncio.wait_for(websocket.receive(),
  timeout=idle_timeout_s)`, unconditionally looping back on any message
  type), so hitting it means the server received literally nothing for
  15s -- despite the client being expected to stream a 20ms audio frame
  continuously (including silence) once connected. This is a real,
  separately-tracked finding suggesting the capture -> enqueue -> send
  pipeline is not actually delivering frames, even though the WebSocket
  handshake itself succeeds. Added temporary, non-sensitive (counts only)
  diagnostic logging to `client/ui/main_window.py` to pinpoint the exact
  stalling stage rather than guessing; `WINDOWS-UI-003` re-runs Test B
  with this logging active.

### WINDOWS-UI-003

- Date: 2026-08-13
- Environment: Windows, PC Local, same `.venv-ui`/`.venv-server` as prior
  UI actions.
- Command summary:
  - `python -m client.ui.bootstrap`
  - `uvicorn server.app:app --host 0.0.0.0 --port 8080` (second terminal)
  - Test steps: both Microphone and Meeting audio (loopback) enabled;
    Connect; ~10s capture; Disconnect; close app.
- Exit status: no exception/traceback in either terminal.
- Result: PASSED (diagnostic goal achieved -- pinpointed the exact stage).
- Relevant output summary:
  - Client terminal: `capture started` logged for both
    `source=microphone` (device_index=1, 44100Hz, 2ch) and
    `source=loopback` (device_index=17, 48000Hz, 2ch).
  - Microphone `capture stats` across six ~2s samples:
    `chunks_enqueued` 85 -> 171 -> 257 -> 344 -> 430 -> 461;
    `frames_produced`/`frames_sent_total` 98 -> 198 -> 298 -> 399 -> 499 ->
    535 (matching exactly at every sample -- everything produced was
    sent).
  - Loopback `capture stats` across the same six samples:
    `chunks_enqueued=0 chunks_dropped=0 overflow_events=0
    frames_produced=0` throughout (only `frames_sent_total` changed,
    tracking the microphone's running total since it is a shared
    counter).
  - Server terminal: `connection open`, `WebSocket /ws/stream` accepted,
    then (at disconnect time) `client disconnected` -- no `idle timeout`
    this run.
- Redacted raw output file, if any: none (counts and device metadata
  only, no secrets).
- Follow-up: Microphone pipeline confirmed fully working end-to-end
  (resolves `WINDOWS-UI-002`'s idle-timeout finding for the working
  case). Loopback produced zero data throughout; leading hypothesis is
  that nothing was actively playing on the output device during this
  test (a documented WASAPI loopback behavior, matching why
  `WINDOWS-AUDIO-001`'s prerequisites required active playback for this
  same device index) rather than a code defect. `WINDOWS-UI-004`
  re-confirms with active playback before ruling out a real bug.

### WINDOWS-UI-004

- Date: 2026-08-13
- Environment: Windows, PC Local, same `.venv-ui`/`.venv-server` as prior
  UI actions; a WAV file with Vietnamese speech playing through the
  default output device for the duration of both test patterns.
- Command summary:
  - `python -m client.ui.bootstrap`
  - `uvicorn server.app:app --host 0.0.0.0 --port 8080` (second terminal)
  - Pattern 1: microphone unchecked, loopback checked; Connect; ~10s;
    Disconnect.
  - Pattern 2: both microphone and loopback checked; Connect; ~10s;
    Disconnect.
- Exit status: no exception/traceback in either pattern.
- Result: PASSED. Hypothesis from `WINDOWS-UI-003` confirmed: loopback
  works correctly once something is actively playing.
- Relevant output summary:
  - Pattern 1 (loopback only): `capture stats: source=loopback` across
    six ~2s samples -- `chunks_enqueued` 93 -> 187 -> 280 -> 374 -> 468 ->
    503; `frames_produced`/`frames_sent_total` 99 -> 198 -> 298 -> 398 ->
    498 -> 536 (matching exactly throughout).
  - Pattern 2 (mic + loopback): both sources' `capture started` logged at
    connect; microphone `chunks_enqueued` 85 -> 172 -> 258 -> 344 -> 381,
    `frames_produced` 98 -> 198 -> 298 -> 399 -> 442; loopback
    `chunks_enqueued` 94 -> 187 -> 281 -> 375 -> 414, `frames_produced` 99
    -> 199 -> 298 -> 398 -> 441 -- both climbing independently and
    correctly in parallel. `frames_sent_total` was identical on both
    sources' log lines at each timestamp (197, 397, 596, 797, 883),
    consistent with it being a single window-wide cumulative counter
    across both sources, not per-source.
- Redacted raw output file, if any: none (counts and device metadata
  only; the WAV file's content/filename were not shared and are not
  needed).
- Follow-up: Confirms no code bug exists in the audio capture/enqueue
  /send pipeline for either source, together or independently. The
  temporary diagnostic logging added for this investigation
  (`WINDOWS-UI-003`) was removed afterward now that its purpose is
  served (kept: the one-time `capture started` line and the
  `configure_logging()` call, both judged genuinely useful rather than
  investigation-specific). `WINDOWS-UI-005` is a quick final regression
  check confirming the trimmed code still behaves identically.

### WINDOWS-UI-005

- Date: 2026-08-13
- Environment: Windows, PC Local, same `.venv-ui`/`.venv-server` as prior
  UI actions; a WAV file with Vietnamese speech playing throughout.
- Command summary:
  - `python -m client.ui.bootstrap`
  - `uvicorn server.app:app --host 0.0.0.0 --port 8080` (second terminal)
  - Both Microphone and Meeting audio (loopback) enabled; Connect; ~10s;
    Disconnect.
- Exit status: no exception/traceback in the app terminal.
- Result: PASSED for its own goal (diagnostic-logging removal confirmed
  safe), but surfaced a new, separate finding -- see follow-up.
- Relevant output summary:
  - App terminal: exactly the two expected `capture started` lines
    (`source=microphone device_index=1 ...`, `source=loopback
    device_index=17 ...`), no `capture stats` lines (confirming the
    removal took effect).
  - Server terminal (new, never seen before):
    ```
    INFO:     connection open
    INFO:     127.0.0.1:64890 - "WebSocket /ws/stream" [accepted]
    2026-08-13 11:05:35,848 WARNING server.transport.gateway session meeting-04c886fc473f stream 1 lost 5 packets (jitter overflow)
    2026-08-13 11:05:35,849 WARNING server.transport.gateway session meeting-04c886fc473f stream 2 lost 4 packets (jitter overflow)
    2026-08-13 11:05:52,000 INFO server.transport.gateway client disconnected
    ```
    Both warnings appeared within 1ms of each other, ~3 seconds after
    connection acceptance; the session otherwise ran normally and
    disconnected cleanly ~16 seconds later.
- Redacted raw output file, if any: none (log contains only local
  loopback addresses, an internally-generated session id, and packet
  counts -- no secrets).
- Follow-up: Root-caused: the capture-send timer was starting immediately
  after `session.start()` (which only waits for the background event loop
  to exist, not for the handshake to complete), letting early audio
  packets get sent once via `AudioSender`'s reconnect-oriented
  resend-pending step and again via the normal outgoing pump -- a
  duplicate/early-traffic burst landing while the server's bounded
  (64-slot) jitter reorder window was still warming up. Fixed by
  deferring the capture-send timer's start until the first `CONNECTED`
  state change; capture itself is unaffected. `WINDOWS-UI-006`
  re-verifies no more `jitter overflow` warnings appear.

### WINDOWS-UI-006

- Date: 2026-08-13
- Environment: Windows, PC Local, same `.venv-ui`/`.venv-server` as prior
  UI actions; a WAV file with Vietnamese speech playing throughout.
- Command summary:
  - `python -m client.ui.bootstrap`
  - `uvicorn server.app:app --host 0.0.0.0 --port 8080` (second terminal)
  - Connect with audio playing; run; Disconnect.
- Exit status: no exception/traceback reported.
- Result: PASSED for the primary purpose ("everything is same as
  expected. OK" -- no `jitter overflow` warning this time). Separately
  reported a new finding around Disconnect timing -- see follow-up.
- Relevant output summary:
  - Primary test: matched expectations, no `jitter overflow` warning.
  - Additional observation: after clicking Disconnect, the button/state
    label took ~5 seconds to update to "Connect"/"disconnected". ~10
    seconds after that (~15s total after the click), the client terminal
    logged `INFO client.transport.sender transport closed; will
    reconnect`, and the server terminal logged
    `INFO server.transport.gateway session meeting-5b85be3f05dd idle
    timeout`.
- Redacted raw output file, if any: none (log lines only contain an
  internally-generated session id, no secrets).
- Follow-up: Root-caused: `AudioSender._pump_incoming` awaited the real
  transport's `recv()` directly (blocks indefinitely with nothing
  incoming), so it never noticed `stop` being set on its own;
  `SessionController.stop()`'s `thread.join(timeout=5.0)` -- called
  synchronously from the Qt main thread, explaining the ~5s UI freeze --
  gave up after that timeout and silently orphaned the still-running
  background thread, which only actually exited once the server's own
  15s idle timeout eventually force-closed the connection (matching the
  ~15s total timeline observed). Fixed by polling `recv()` with a short
  (50ms) timeout instead of awaiting it directly, matching the existing
  `_pump_outgoing` pattern; added a regression test simulating a
  permanently-blocked `recv()`. `WINDOWS-UI-007` re-verifies Disconnect
  now updates promptly with no delayed reconnect/idle-timeout log lines.

### WINDOWS-UI-007

- Date: 2026-08-13
- Environment: Windows, PC Local, same `.venv-ui`/`.venv-server` as prior
  UI actions; a WAV file with Vietnamese speech playing throughout.
- Command summary:
  - `python -m client.ui.bootstrap`
  - `uvicorn server.app:app --host 0.0.0.0 --port 8080` (second terminal)
  - Connect with audio playing; run; Disconnect.
- Exit status: no exception/traceback.
- Result: PASSED ("everything is good. OK.").
- Relevant output summary: Disconnect updated the UI promptly; no delayed
  reconnect attempt or server-side idle timeout observed afterward.
- Redacted raw output file, if any: none.
- Follow-up: Confirms the `_pump_incoming` fix from `WINDOWS-UI-006`.
  This closes out Phase 09's manual-verification sequence -- no further
  Phase 09 manual action is currently pending. All four bugs found across
  `WINDOWS-UI-001`-`WINDOWS-UI-007` (websockets import, background
  -thread-crash cleanup, premature capture-send-timer start, and
  `_pump_incoming` not noticing `stop`) are now hardware-confirmed fixed,
  and the audio pipeline is confirmed working for both sources.

### WINDOWS-AUDIO-001

- Date: 2026-08-10
- Environment: Windows, PowerShell, project root (virtualized audio devices:
  VMware / Teradici virtual microphone and speakers).
- Command summary:
  - `python -m client.audio.wav_cli list`
  - `python -m client.audio.wav_cli capture --source microphone --seconds 5 --out mic_test.wav`
  - `python -m client.audio.wav_cli capture --source loopback --seconds 5 --out loopback_test.wav --device 17`
- Exit status: 0 for all commands.
- Result: PASSED
- Relevant output summary:
  - Enumeration: 8 input devices and 2 loopback devices detected. Loopback
    devices were [16] Teradici and [17] VMware (DevTap).
  - Microphone capture: `mic_test.wav` = 158720 bytes, 248 frames, dropped=0.
  - Loopback capture (device 17): `loopback_test.wav` = 159360 bytes,
    249 frames, dropped=0.
  - Frame math consistent with mono 16 kHz S16LE 20 ms frames (640 bytes/frame;
    248 x 640 = 158720, 249 x 640 = 159360), i.e. ~4.96-4.98 s of audio.
  - No errors observed.
- Redacted raw output file, if any: none (raw WAV audio not attached, kept local).
- Follow-up: Windows audio marked HARDWARE_VERIFIED. Independent mic/loopback
  capture confirmed on real (virtualized) Windows devices.

### WINDOWS-PACKAGE-001

- Date: 2026-08-14
- Environment: Windows, PowerShell, project root, fresh `.venv`
  (`pip install -e ".[client,windows-audio,packaging,server]"`); a WAV
  file with Vietnamese speech playing through the default output device
  while the app was connected.
- Command summary:
  - `python -m venv .venv`
  - `.venv\Scripts\activate`
  - `pip install -e ".[client,windows-audio,packaging,server]"`
  - `python scripts\build_windows_client.py --clean`
  - `.\dist\MeetingTranslator-0.1.0\MeetingTranslator-0.1.0.exe`
  - `uvicorn server.app:app --host 0.0.0.0 --port 8080 --reload` (second
    terminal, local dev server to connect against)
- Exit status: no traceback/error/exception reported for any step.
- Result: PASSED
- Relevant output summary:
  - Build completed with no error.
  - The `.exe` launched a window titled "Meeting Translator v0.1.0".
  - Device dropdowns populated with real input/loopback devices.
  - Connect/Disconnect worked against the local dev server with no
    traceback or freeze.
  - Expected artifacts present: `dist/MeetingTranslator-0.1.0/`; no other
    artifacts reported.
- Redacted raw output file, if any: none.
- Follow-up: First hardware confirmation that a packaged (PyInstaller)
  build of the Windows client -- not just `python -m client.ui.bootstrap`
  -- launches and behaves correctly, matching the same Connect/Disconnect
  behavior already hardware-verified for the unpackaged app in
  `WINDOWS-UI-005`-`WINDOWS-UI-007`. This is a UI/connectivity check only;
  no live captions were expected or observed, since `UtteranceOrchestrator`
  is still not wired into the live gateway. `WINDOWS-PACKAGE-001` is
  PASSED and closed. `GPU-E2E-001` and `LATENCY-001` remain
  `WAITING_FOR_USER`.

### GPU-E2E-001 (attempt 1)

- Date: 2026-08-14
- Environment: GPU server, fresh `.venv-asr` created via `python -m venv
  .venv-asr` at `/workspace/meeting-translator`.
- Command summary:
  - `python -m venv .venv-asr`
  - `source .venv-asr/bin/activate`
  - `pip install -e ".[dev]"`
  - `pytest -m gpu tests/test_e2e_gpu.py -v -s`
- Exit status: pytest ran cleanly, 0 failures.
- Result: SKIPPED (not a pass) -- environment gap, not a code defect.
- Relevant output summary: `tests/test_e2e_gpu.py s` / `1 skipped in
  0.36s`. No transcription/translation output printed, since the test's
  own `requires_gpu_stack` skip-marker fired before the body ran.
- Redacted raw output file, if any: none.
- Follow-up: Root cause is a mistake in the command set Claude originally
  prepared for `GPU-E2E-001`, not anything the user did wrong.
  `faster-whisper` (which `tests/test_e2e_gpu.py` gates on via
  `importlib.util.find_spec("faster_whisper")`) lives behind
  `pyproject.toml`'s separate `gpu` extra
  (`faster-whisper>=1.0,<2`/`silero-vad>=5,<6`/`vllm`), not `dev` -- so
  `pip install -e ".[dev]"` alone never installs it, and a freshly created
  venv has no prior install to fall back on. Corrected command set
  installs `faster-whisper` directly (matching the precedent already
  established in `GPU-ASR-002`, rather than the full `gpu` extra, since
  installing `vllm` again on the ASR host is unnecessary weight -- this
  test's `VllmTranslationClient` only needs `httpx`, already in `dev`, to
  reach the already-running vLLM server over HTTP). See
  `MANUAL_ACTIONS.md`'s updated `GPU-E2E-001` for the retry commands.

### GPU-E2E-001 (attempt 2, retry)

- Date: 2026-08-14
- Environment: GPU server, same `.venv-asr` as attempt 1 plus `pip install
  "faster-whisper>=1.0,<2"`.
- Command summary:
  - `pip install "faster-whisper>=1.0,<2"`
  - `python -c "import faster_whisper; print(...)"`
  - `pytest -m gpu tests/test_e2e_gpu.py -v -s`
- Exit status: `faster_whisper 1.2.1` printed; pytest `1 passed in 11.13s`.
- Result: PASSED by the test's own (deliberately loose) assertions, but
  with a real, unresolved finding -- see follow-up.
- Relevant output summary:
  - `transcription: 'ご視聴ありがとうございました'` -- a well-known
    faster-whisper/Whisper hallucination on non-speech input (this
    Japanese phrase, "thank you for watching", is a documented artifact
    the model produces on silence/synthetic tones with no real speech).
    Expected given the test's synthetic sine-tone input; not a defect,
    and consistent with the test's own docstring (content accuracy on a
    synthetic tone is explicitly not asserted).
  - `translation_status: <TranslationStatus.FAILED: 'failed'>`
  - `translation: None`
  - The test passed only because its own assertion is
    `final_event.translation_status is not None` when transcription is
    non-empty -- `FAILED` satisfies "is not None", so this is not
    evidence the translation leg actually worked.
- Redacted raw output file, if any: none.
- Follow-up: **Real, unresolved finding**: the translation leg genuinely
  failed against the real vLLM server, for one of several possible
  reasons the test itself cannot distinguish (the wire protocol's
  `UtteranceFinal` message does not carry the internal
  `TranslationOutcome.issue`/reason string, only `translation_status`) --
  circuit breaker open, request timeout, vLLM unreachable/down since
  `GPU-TRANSLATE-005`, `VLLM_BASE_URL` unset or wrong in this venv/host
  (this may be a different pod/session than the one `GPU-TRANSLATE-005`
  -`007` ran on), or a validation-failure reason (`server/translation/
  worker.py`'s `validate_translation`). Do not run `LATENCY-001` yet --
  measuring latency against a broken translation backend would produce
  misleading numbers. `GPU-E2E-002` (see `MANUAL_ACTIONS.md`) is a small,
  read-only diagnostic to narrow this down before proceeding.

### GPU-E2E-002

- Date: 2026-08-14
- Environment: GPU server, `.venv-asr` (same as `GPU-E2E-001`).
- Command summary:
  - `python -c "from shared.settings import Settings; print(Settings().vllm_base_url)"`
  - `pgrep -fa "vllm serve"`
  - `curl .../health`, `curl .../v1/models`
  - `/tmp/translate_diag.py` (one real `VllmTranslationClient.complete_chat` call)
- Exit status: no exception in commands 1-3; command 4's translation
  attempt raised (caught and printed by the script itself, not an
  uncaught crash).
- Result: PASSED as a diagnostic (root cause found, unambiguous).
- Relevant output summary:
  - Step 1: `resolved vllm_base_url=http://localhost:8000/v1` -- config
    resolution is correct, not the problem.
  - Step 2: `no vllm serve process found on this host`.
  - Step 3: `http_status=000` / `unreachable` -- no server listening on
    that port at all (not a 4xx/5xx, not a timeout on a live process --
    connection itself fails).
  - Step 4: `vllm_base_url='http://localhost:8000/v1'
    model='qwen3.6-27b-translate'` (config correct) then
    `ERROR: TranslationOverloadedError: All connection attempts failed`
    (`VllmTranslationClient` correctly classified the raw `httpx`
    connection failure as `TranslationOverloadedError` via
    `classify_backend_error`'s "connect"-in-exception-name heuristic --
    working as designed, not a client bug).
- Redacted raw output file, if any: none.
- Follow-up: Root cause is unambiguous and not a code defect anywhere in
  this project -- the vLLM server from `GPU-TRANSLATE-005` is simply not
  running on this host right now (no process, no listener on port 8000).
  `GPU-E2E-001`'s `TranslationStatus.FAILED` result is now fully
  explained. `GPU-TRANSLATE-008` (see `MANUAL_ACTIONS.md`) restarts the
  server so `GPU-E2E-001` and `LATENCY-001` can be meaningfully re-run
  afterward.

### GPU-TRANSLATE-008 (attempt 1)

- Date: 2026-08-14
- Environment: GPU server, freshly recreated `.venv-translate`.
- Command summary: steps 1-4 (venv creation, `huggingface_hub` install,
  weights re-download, `pip install vllm`, `pgrep` check) then step 5
  (`nohup vllm serve ...`) then step 6 (flashinfer patch script).
- Exit status: steps 1-4 reported OK by the user with no further detail
  requested. Step 5's server process crashed on the known flashinfer
  import-time bug. Step 6's patch script itself raised an uncaught
  `TypeError`.
- Result: FAILED at step 6 (patch script bug, not a server/environment
  problem) -- user correctly stopped and reported back rather than
  guessing further.
- Relevant output summary: Step 6's traceback:
  ```
  File "/workspace/meeting-translator/.venv-translate/lib/python3.11/site-packages/flashinfer/comm/fd_exchange.py", line 55, in <module>
      def _fd_ancillary(fd: int) -> tuple[tuple[int, int, array.array[int]]]:
  TypeError: type 'array.array' is not subscriptable
  ```
  raised from `import flashinfer.comm.fd_exchange as m` inside the patch
  script itself (visible via the `flashinfer/comm/__init__.py` ->
  `trtllm_ar.py` -> `mnnvl.py` -> `fd_exchange.py` import chain in the
  traceback), not from the vLLM server process.
- Redacted raw output file, if any: none.
- Follow-up: Root cause is a mistake in the patch script Claude prepared,
  not anything the user did wrong or a new server-side issue. Locating
  the broken file by importing it is self-defeating, since importing it
  is exactly what triggers the bug. Corrected in `MANUAL_ACTIONS.md`'s
  `GPU-TRANSLATE-008` to locate the file via a filesystem glob under
  `.venv-translate/lib/` instead (the failed attempt's own traceback
  already confirmed the real path, so this isn't a guess). The
  `Qwen3.6-27B-FP8` re-download and `vllm` install themselves are not
  known to be a problem -- only the patch step needs retrying.

### GPU-TRANSLATE-008 (attempt 2, retry)

- Date: 2026-08-14
- Environment: GPU server, `.venv-translate`.
- Command summary: corrected flashinfer patch script (filesystem-glob
  locator), relaunch, then the `/health`/`/v1/models`/`nvidia-smi`
  verification commands.
- Exit status: reported by the user as "All command is OK. Don't have any
  traceback, error or exception," without pasting the specific requested
  return values.
- Result: PASSED, on the user's word -- but NOT independently verified
  against specific output (no `/health` status code, `/v1/models`
  response, `nvidia-smi` memory line, or `vllm_serve.log` excerpt was
  provided). Recorded honestly as such per `CLAUDE.md`'s "never assume a
  manual command succeeded" -- this is a terse user confirmation, not
  verified detail.
- Relevant output summary: none pasted.
- Redacted raw output file, if any: none.
- Follow-up: `GPU-E2E-001` is being re-run next specifically because it
  gives a stronger, self-contained proof regardless of this gap -- it
  exercises the real translation path end-to-end through the project's
  own code and prints the actual `translation_status`/`translation`
  values, which will conclusively show whether the rebuilt vLLM server
  actually works, independent of whatever wasn't pasted here.

## Result template

```markdown
### Action ID

- Date:
- Environment:
- Command summary:
- Exit status:
- Result: PASSED | FAILED | INCONCLUSIVE
- Relevant output summary:
- Redacted raw output file, if any:
- Follow-up:
```

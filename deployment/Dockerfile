# Application server image (CPU transport gateway).
#
# GPU inference (faster-whisper, vLLM) is NOT built or run here. Those run on
# the GPU host per GPU_MANUAL_WORKFLOW.md. This image contains only the CPU
# server transport layer.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY shared ./shared
COPY server ./server

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[server]"

EXPOSE 8080

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8080"]

# speech_service (Part B) in a Linux container, so Whisper runs even where Windows
# Smart App Control blocks its native libraries.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/cache \
    CLIPS_DIR=/clips \
    SIGN_WS_URL=ws://host.docker.internal:8001/ws

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY signbridge_speech ./signbridge_speech
COPY scripts ./scripts
COPY service.py .

EXPOSE 8002
CMD ["python", "service.py", "--preload-whisper"]

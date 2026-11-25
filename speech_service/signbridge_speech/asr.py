"""Speech-to-text, tried in order:

  1. Groq-hosted Whisper large-v3 (free, same GROQ_API_KEY): much better Hindi/Telugu, ~0.5-1.5 s
  2. local Whisper (faster-whisper, default "small"), loaded lazily: works offline

If neither is available (no key and faster-whisper blocked, e.g. by Windows Smart App Control), the
service still runs and /speech returns 503: Part C then sends text (browser speech recognition) instead.

Audio input: any format. WAV is decoded with the standard library, others (webm/ogg/mp3/m4a) with PyAV.
"""
from __future__ import annotations

import io
import logging
import os
import threading
import time
import wave

import numpy as np

from . import config

log = logging.getLogger("speech_service.asr")

_model = None
_error: str | None = None
_lock = threading.Lock()
_groq_cooldown = 0.0


def _load():
    global _model, _error
    with _lock:
        if _model is not None or _error is not None:
            return
        try:
            from faster_whisper import WhisperModel
            log.info("loading Whisper '%s' (first time downloads the model)...", config.WHISPER_MODEL)
            _model = WhisperModel(config.WHISPER_MODEL, device=config.WHISPER_DEVICE,
                                  compute_type="int8" if config.WHISPER_DEVICE in ("auto", "cpu") else "float16")
        except Exception as e:  # noqa: BLE001 - ImportError, OSError (blocked DLL), download errors...
            _error = f"{type(e).__name__}: {e}"
            log.warning("Whisper unavailable: %s", _error)


def local_available() -> bool:
    _load()
    return _model is not None


def _groq_ok() -> bool:
    return "groq" in config.ASR_PROVIDERS and bool(os.getenv("GROQ_API_KEY")) and time.time() >= _groq_cooldown


def available() -> bool:
    return _groq_ok() or local_available()


def status() -> dict:
    return {"providers": config.ASR_PROVIDERS, "groq_model": config.GROQ_ASR_MODEL if _groq_ok() else None,
            "loaded": _model is not None, "model": config.WHISPER_MODEL, "error": _error}


def _wav_to_float(data: bytes) -> np.ndarray | None:
    try:
        with wave.open(io.BytesIO(data)) as w:
            sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        return None
    if width != 2:
        return None
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != 16000:                                       # linear resample to 16 kHz
        n = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


def _decode_any(data: bytes) -> np.ndarray:
    """Any container/codec (webm/ogg/mp3/m4a...) -> 16 kHz mono float32, using PyAV directly
    (avoids faster-whisper's own decoder, which breaks with newer PyAV releases)."""
    import av
    out = []
    with av.open(io.BytesIO(data)) as container:
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(stream):
            for f in resampler.resample(frame):
                out.append(f.to_ndarray().reshape(-1))
        for f in resampler.resample(None):             # flush
            out.append(f.to_ndarray().reshape(-1))
    if not out:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(out).astype(np.float32) / 32768.0


def _transcribe_local(data: bytes, language: str | None = None, translate: bool = False, fast: bool = False) -> dict:
    """-> {"text", "language", "confidence"}. language: "en"/"hi"/"te" or None to auto-detect.
    fast=True (greedy decoding) is for live partial captions on audio that is still being recorded."""
    if not local_available():
        raise RuntimeError(f"Whisper not available: {_error}")
    audio = _wav_to_float(data)
    if audio is None:
        audio = _decode_any(data)                      # browser webm/ogg, phone m4a, mp3...
    if audio.size < 1600:                              # < 0.1 s
        return {"text": "", "language": language or "en", "confidence": 0.0}
    segments, info = _model.transcribe(
        audio, language=language or None, task="translate" if translate else "transcribe",
        beam_size=1 if fast else 5, vad_filter=not fast, condition_on_previous_text=not fast,
        initial_prompt="Doctor, hospital, medicine, fever, sick, family.")
    segs = list(segments)
    text = " ".join(s.text.strip() for s in segs).strip()
    conf = float(np.exp(np.mean([s.avg_logprob for s in segs]))) if segs else 0.0
    lang = info.language if info.language in config.LANG_NAMES else (language or "en")
    return {"text": text, "language": lang, "confidence": round(conf, 3)}


def _audio_ext(data: bytes) -> str:
    """File extension from the first bytes (Groq picks the decoder from the file name)."""
    head = data[:12]
    if head[:4] == b"RIFF":
        return "wav"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"                                   # browser MediaRecorder (Chrome)
    if head[4:8] == b"ftyp":
        return "m4a"                                    # phones, Safari
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    return "webm"


def _transcribe_groq(data: bytes, language: str | None, fast: bool) -> dict | None:
    global _groq_cooldown
    import httpx
    model = config.GROQ_ASR_MODEL_FAST if fast else config.GROQ_ASR_MODEL
    form = {"model": model, "response_format": "verbose_json", "temperature": "0",
            "prompt": "Doctor, hospital, medicine, fever."}
    if language:
        form["language"] = language
    try:
        r = httpx.post("https://api.groq.com/openai/v1/audio/transcriptions", timeout=30,
                       headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
                       files={"file": (f"audio.{_audio_ext(data)}", data, "application/octet-stream")}, data=form)
    except httpx.HTTPError as e:
        log.warning("Groq Whisper unreachable: %s", e)
        return None
    if r.status_code == 429:
        _groq_cooldown = time.time() + min(float(r.headers.get("retry-after", "30") or 30), 300)
        log.warning("Groq Whisper free-tier limit reached; using local Whisper for a while")
        return None
    if r.status_code != 200:
        log.warning("Groq Whisper HTTP %s: %s", r.status_code, r.text[:200])
        return None
    d = r.json()
    segs = d.get("segments") or []
    conf = float(np.exp(np.mean([s.get("avg_logprob", -1.0) for s in segs]))) if segs else 0.0
    lang = _LANG_CODES.get(str(d.get("language", "")).lower(), language or "en")
    return {"text": str(d.get("text", "")).strip(), "language": lang, "confidence": round(conf, 3), "asr": model}


_LANG_CODES = {"english": "en", "hindi": "hi", "telugu": "te", "en": "en", "hi": "hi", "te": "te"}


def transcribe(data: bytes, language: str | None = None, translate: bool = False, fast: bool = False) -> dict:
    """-> {"text", "language", "confidence", "asr"}. Groq Whisper first, local Whisper as fallback.
    translate=True (English output) is only used offline, so it always runs locally."""
    if not translate and _groq_ok():
        r = _transcribe_groq(data, language, fast)
        if r is not None:
            return r
    r = _transcribe_local(data, language, translate, fast)
    return {**r, "asr": f"local-{config.WHISPER_MODEL}"}

"""Speech-to-text with Whisper (faster-whisper), loaded lazily on first use.

If faster-whisper can't load (not installed, or Windows Application Control blocks its DLLs), the
service still runs and `available()` is False: Part C then sends text instead of audio.

Audio input: WAV (any rate, mono/stereo, 16-bit) is decoded here with the standard library, so PyAV is
not needed for WAV. Other formats (webm/ogg/mp3 from MediaRecorder) need PyAV via faster-whisper.
"""
from __future__ import annotations

import io
import logging
import threading
import wave

import numpy as np

from . import config

log = logging.getLogger("speech_service.asr")

_model = None
_error: str | None = None
_lock = threading.Lock()


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


def available() -> bool:
    _load()
    return _model is not None


def status() -> dict:
    return {"loaded": _model is not None, "model": config.WHISPER_MODEL, "error": _error}


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


def transcribe(data: bytes, language: str | None = None, translate: bool = False) -> dict:
    """-> {"text", "language", "confidence"}. language: "en"/"hi"/"te" or None to auto-detect."""
    if not available():
        raise RuntimeError(f"Whisper not available: {_error}")
    audio = _wav_to_float(data)
    src = audio if audio is not None else io.BytesIO(data)   # non-WAV: let faster-whisper/PyAV decode
    segments, info = _model.transcribe(
        src, language=language or None, task="translate" if translate else "transcribe",
        beam_size=5, vad_filter=True,
        initial_prompt="Doctor, hospital, medicine, fever, sick, family.")
    segs = list(segments)
    text = " ".join(s.text.strip() for s in segs).strip()
    conf = float(np.exp(np.mean([s.avg_logprob for s in segs]))) if segs else 0.0
    lang = info.language if info.language in config.LANG_NAMES else (language or "en")
    return {"text": text, "language": lang, "confidence": round(conf, 3)}

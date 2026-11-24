"""Shared message format, Part B side.

Signer -> hearing (gloss from sign_service, `sentence` filled in by Part B):
  {"from":"signer","type":"gloss","content":"ME HOT YESTERDAY TODAY",
   "sentence":"I've had a fever since yesterday.", "sentence_en": "...", "language":"en",
   "emotion":"neutral","confidence":0.89,"timestamp":"...","source":"groq"}      # source: groq / ollama / anthropic / rules

Hearing -> signer (speech or typed text from Part C):
  {"from":"hearing","type":"speech","content":"<what was said, original language>",
   "sentence":"<English caption>","gloss":"DOCTOR TOMORROW","language":"hi","emotion":"question",
   "confidence":0.93,"timestamp":"...","clips":[{"gloss":"DOCTOR","video":"DOCTOR.mp4"}, ...]}
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def make_message(from_: str, type_: str, content: str, sentence: str, *, language: str = "en",
                 emotion: str = "neutral", confidence: float = 1.0, **extra) -> dict:
    return {
        "from": from_,
        "type": type_,
        "content": content,
        "sentence": sentence,
        "language": language,
        "emotion": emotion,
        "confidence": round(float(confidence), 3),
        "timestamp": now(),
        **extra,
    }

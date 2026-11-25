"""Shared message format (section 6 of the project doc), Part B side.

  {"from": "signer | speaker", "type": "gloss | text | speech_partial | alert", "content": ..., "sentence": ...,
   "language": "en | hi | te", "emotion": "neutral | happy | angry | urgent | question",
   "confidence": 0.92, "timestamp": "2026-11-23T22:56:00+05:30"}

Signer, gloss from sign_service with `sentence` filled in by Part B:
  {"from":"signer","type":"gloss","content":"ME HOT YESTERDAY TODAY","sentence":"I've had a fever since yesterday.",
   "sentence_en":"...", "source":"groq"}                                   source: groq / ollama / anthropic / rules
Signer taps a phrase or a suggestion:  {"from":"signer","type":"text","content":"<English>","sentence":"<listener language>","kind":"quick_reply|suggestion"}
Signer SOS:                            {"from":"signer","type":"alert","content":"SOS","sentence":"Emergency! ...","emotion":"urgent"}
Speaker live caption:                  {"from":"speaker","type":"speech_partial","content":"Do you have","sentence":"Do you have"}
Speaker final:  {"from":"speaker","type":"text","content":"<as said>","sentence":"<English caption>","language":"te",
                 "emotion":"question","gloss":"YESTERDAY YOU HOT","clips":[{"gloss":"YESTERDAY","video":"YESTERDAY.mp4",...}]}
Additions (like Part A's gloss_partial/status), from "system":
  {"type":"suggestions","suggestions":[{"id":"s1","text_en":"Yes, I have a fever.","text":"అవును, నాకు జ్వరం ఉంది."}, ...]}
  {"type":"summary","content":"<summary>","key_points":[...],"transcript":[...]}
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

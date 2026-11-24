"""Shared message format (section 6 of the project doc)."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def make_message(type_: str, glosses: list[str], confidence: float, *, emotion: str = "neutral",
                 language: str = "en", **extra) -> dict:
    """Part A always sends from='signer'. `sentence` is left empty for Part B to fill.

    type_: "gloss"         - a finished signed sentence (send this to Part B)
           "gloss_partial" - words recognised so far (for live UI feedback only)
    Extra keys (e.g. per-word details) are added under "words" and can be ignored.
    """
    return {
        "from": "signer",
        "type": type_,
        "content": " ".join(glosses),
        "sentence": "",
        "language": language,
        "emotion": emotion,
        "confidence": round(float(confidence), 3),
        "timestamp": datetime.now(IST).isoformat(timespec="seconds"),
        **extra,
    }

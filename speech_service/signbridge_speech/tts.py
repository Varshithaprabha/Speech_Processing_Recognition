"""Text-to-speech for the signer's sentences via edge-tts (needs internet; sends the text to Microsoft's
online TTS). If it fails, Part C can use the browser's speechSynthesis instead."""
from __future__ import annotations

VOICES = {"en": "en-IN-NeerjaNeural", "hi": "hi-IN-SwaraNeural", "te": "te-IN-ShrutiNeural"}
URGENT_RATE = "+15%"


async def synthesize(text: str, language: str = "en", emotion: str = "neutral") -> bytes:
    import edge_tts
    voice = VOICES.get(language, VOICES["en"])
    com = edge_tts.Communicate(text, voice, rate=URGENT_RATE if emotion == "urgent" else "+0%")
    audio = bytearray()
    async for chunk in com.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    if not audio:
        raise RuntimeError("edge-tts returned no audio")
    return bytes(audio)

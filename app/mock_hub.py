"""Stand-in for speech_service (Part B) + sign_service (Part A), for working on the UI alone.

Speaks the same section-6 messages on /mock/ws as speech_service does on ws://localhost:8002/ws.
No AI and no Whisper: captions are what was typed, avatar signs come from simple keyword matching, and
"flush" (the Send button) plays the next line of a scripted hospital conversation from the signer.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

IST = timezone(timedelta(hours=5, minutes=30))

QUICK_REPLIES = [
    {"id": "yes", "text": "Yes.", "emotion": "neutral"},
    {"id": "no", "text": "No.", "emotion": "neutral"},
    {"id": "wait", "text": "Please wait a moment.", "emotion": "neutral"},
    {"id": "repeat", "text": "Please say that again, slowly.", "emotion": "question"},
    {"id": "write", "text": "Please write it down for me.", "emotion": "neutral"},
    {"id": "understand_not", "text": "I don't understand.", "emotion": "question"},
    {"id": "pain", "text": "I am in pain.", "emotion": "urgent"},
    {"id": "water", "text": "May I have some water, please?", "emotion": "question"},
    {"id": "washroom", "text": "Where is the washroom?", "emotion": "question"},
    {"id": "family", "text": "Please call my family.", "emotion": "urgent"},
    {"id": "thanks", "text": "Thank you.", "emotion": "happy"},
]
SIGNER_SCRIPT = [
    ("HELLO", "Hello.", "happy"),
    ("ME SICK YESTERDAY TODAY", "I have been sick since yesterday.", "neutral"),
    ("ME HOT", "I have a fever.", "urgent"),
    ("MEDICINE GOOD", "Is the medicine good?", "question"),
    ("THANK-YOU", "Thank you.", "happy"),
]
KEYWORDS = {  # English / Hindi / Telugu word -> gloss
    "HELLO": ["hello", "hi", "namaste", "నమస్తే", "नमस्ते"],
    "HOW-ARE-YOU": ["how are you"],
    "THANK-YOU": ["thank", "thanks", "dhanyavad", "धन्यवाद", "ధన్యవాదాలు"],
    "ME": [" i ", " me ", " my "],
    "YOU": ["you", "your", "आप", "మీరు", "మీకు"],
    "DOCTOR": ["doctor", "डॉक्टर", "డాక్టర్"],
    "HOSPITAL": ["hospital", "अस्पताल", "ఆసుపత్రి"],
    "SICK": ["sick", "ill", "unwell", "बीमार"],
    "HOT": ["fever", "hot", "temperature", "बुखार", "జ్వరం"],
    "GOOD": ["good", "fine", "well", "अच्छा", "మంచి"],
    "BAD": ["bad", "worse", "बुरा"],
    "MEDICINE": ["medicine", "tablet", "दवा", "మందు"],
    "TODAY": ["today", "आज", "ఈరోజు"],
    "TOMORROW": ["tomorrow", "कल", "రేపు"],
    "YESTERDAY": ["yesterday", "నిన్న"],
    "MOTHER": ["mother", "mom", "माँ", "అమ్మ"],
    "FATHER": ["father", "dad", "पिता", "నాన్న"],
    "FAMILY": ["family", "परिवार", "కుటుంబ"],
}
URGENT = ["urgent", "immediately", "emergency", "now", "quick", "hurry", "turant", "తొందరగా", "వెంటనే", "तुरंत"]


def now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def msg(from_: str, type_: str, content: str, sentence: str, **extra) -> dict:
    base = {"from": from_, "type": type_, "content": content, "sentence": sentence, "language": "en",
            "emotion": "neutral", "confidence": 1.0, "timestamp": now(), "source": "mock"}
    return {**base, **extra}


def tone(text: str) -> str:
    t = f" {text.lower()} "
    if any(w in t for w in URGENT) or text.strip().endswith("!"):
        return "urgent"
    if text.isupper() and len(text) > 6:
        return "angry"
    if text.strip().endswith("?") or t.strip().startswith(("do ", "are ", "is ", "what", "how", "when", "where")):
        return "question"
    if any(w in t for w in ("great", "good news", "happy", "congrat")):
        return "happy"
    return "neutral"


def to_gloss(text: str, allowed: set[str]) -> list[str]:
    t = " " + re.sub(r"[.,!?;:\"'()]", " ", text.lower()) + " "   # keep Indic vowel signs
    found = []
    for g, words in KEYWORDS.items():
        pos = min((t.find(w) for w in words if w in t), default=-1)
        if pos >= 0 and g in allowed:
            found.append((pos, g))
    order = sorted(found)
    time = [g for _, g in order if g in ("YESTERDAY", "TODAY", "TOMORROW")]   # ISL: time first
    return time + [g for _, g in order if g not in time]


def attach_mock(app: FastAPI, clips_dir: Path):
    try:
        index = json.loads((clips_dir / "index.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        index = {}
    clients: set[WebSocket] = set()
    transcript: list[dict] = []
    state = {"line": 0, "language": "en"}

    async def broadcast(m: dict):
        for ws in list(clients):
            try:
                await ws.send_text(json.dumps(m, ensure_ascii=False))
            except Exception:  # noqa: BLE001
                clients.discard(ws)

    def remember(m: dict):
        transcript.append(m)

    async def suggestions():
        await asyncio.sleep(0.6)
        last = transcript[-1]["sentence"].lower() if transcript else ""
        if "fever" in last or "sick" in last:
            items = ["Yes, since yesterday.", "No fever.", "I took medicine.", "Please call the doctor."]
        elif last.endswith("?"):
            items = ["Yes.", "No.", "I don't know.", "Please write it down."]
        else:
            items = ["Okay.", "Thank you.", "Please wait.", "I don't understand."]
        await broadcast(msg("system", "suggestions", "", "", language=state["language"], suggestions=[
            {"id": f"s{i + 1}", "text_en": t, "text": t} for i, t in enumerate(items)]))
        state["suggest"] = items

    async def speaker_text(content: str, language: str):
        state["language"] = language
        gloss = to_gloss(content, set(index))
        clips = [{"gloss": g, **index[g]} for g in gloss]
        unclear = len(content.strip()) < 2
        m = msg("speaker", "text", content, content, language=language, emotion=tone(content),
                gloss=" ".join(gloss), clips=clips, unclear=unclear, input="text")
        remember(m)
        await broadcast(m)
        asyncio.create_task(suggestions())

    async def signer_line():
        gloss, sentence, emotion = SIGNER_SCRIPT[state["line"] % len(SIGNER_SCRIPT)]
        state["line"] += 1
        await broadcast(msg("signer", "status", "signing", ""))
        words = gloss.split()
        for i in range(1, len(words) + 1):
            await broadcast(msg("signer", "gloss_partial", " ".join(words[:i]), "", confidence=0.8))
            await asyncio.sleep(0.5)
        m = msg("signer", "gloss", gloss, sentence, emotion=emotion, confidence=0.86, sentence_en=sentence)
        remember(m)
        await broadcast(m)
        await broadcast(msg("signer", "status", "idle", ""))

    @app.get("/mock/health")
    def health():
        return {"ok": True, "llm": "mock", "sign_service": True, "whisper": {"ok": False},
                "listener_language": state["language"], "avatar_vocab": list(index), "mock": True}

    @app.get("/mock/quick_replies")
    def quick_replies():
        return QUICK_REPLIES

    @app.get("/mock/tts")
    def tts():
        raise HTTPException(503, "mock: use the browser's speechSynthesis")

    @app.post("/mock/speech")
    def speech():
        raise HTTPException(503, "mock: no Whisper, use browser speech recognition")

    @app.websocket("/mock/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        clients.add(sock)
        try:
            while True:
                try:
                    data = json.loads(await sock.receive_text())
                except json.JSONDecodeError:
                    continue
                cmd, content = data.get("cmd", ""), str(data.get("content", "")).strip()
                lang = data.get("language", "en")
                if cmd == "partial" and content:
                    await broadcast(msg("speaker", "speech_partial", content, content, language=lang,
                                        emotion=tone(content)))
                elif cmd == "text" and content:
                    await speaker_text(content, lang)
                elif cmd == "flush":
                    asyncio.create_task(signer_line())
                elif cmd == "quick_reply":
                    rid = str(data.get("id", ""))
                    if rid.startswith("s") and rid[1:].isdigit():
                        items = state.get("suggest", [])
                        k = int(rid[1:]) - 1
                        if 0 <= k < len(items):
                            m = msg("signer", "text", items[k], items[k], kind="suggestion", sentence_en=items[k])
                            remember(m)
                            await broadcast(m)
                    else:
                        q = next((r for r in QUICK_REPLIES if r["id"] == rid), None)
                        if q:
                            m = msg("signer", "text", q["text"], q["text"], emotion=q["emotion"],
                                    kind="quick_reply", sentence_en=q["text"])
                            remember(m)
                            await broadcast(m)
                elif cmd == "sos":
                    m = msg("signer", "alert", "SOS",
                            "Emergency! I am Deaf and I need help right now. Please call a doctor.",
                            emotion="urgent", kind="sos")
                    remember(m)
                    await broadcast(m)
                elif cmd == "summary":
                    lines = [{"from": t["from"], "type": t["type"], "text": t["sentence"], "original": t["content"],
                              "emotion": t["emotion"], "timestamp": t["timestamp"]} for t in transcript]
                    s = (f"{len(lines)} messages. " +
                         " ".join(f"{'Patient' if t['from'] == 'signer' else 'Staff'}: {t['text']}"
                                  for t in lines[-4:])) if lines else "No conversation yet."
                    await broadcast(msg("system", "summary", s, s, key_points=[], transcript=lines))
                elif cmd == "new_conversation":
                    transcript.clear()
                    state["line"] = 0
                elif cmd == "set_language":
                    state["language"] = data.get("language", "en")
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(sock)

"""speech_service - Part B's deliverable (Speech, Language & AI).

    python service.py                  # connects to sign_service on ws://localhost:8001/ws, serves port 8002
    python service.py --no-llm         # rules only (no Claude calls)
    python service.py --no-sign        # don't connect to sign_service (test the hearing side alone)

Part C connects ONLY to ws://localhost:8002/ws and receives everything:
    from sign_service (forwarded):  gloss_partial, status
    filled by Part B:               gloss (with `sentence`), quick_reply, sos   (from = "signer")
    hearing person:                 speech / text (caption + tone + gloss + clips)  (from = "hearing")

Client -> server JSON commands on /ws:
    {"cmd":"text", "content":"Did you take your medicine?", "language":"en"}   hearing person typed/spoke
    {"cmd":"quick_reply", "id":"water"}   {"cmd":"sos"}
    {"cmd":"set_language", "language":"hi"}       language the hearing person wants to hear
    {"cmd":"flush"|"reset"|"pause"|"resume"}       forwarded to sign_service

HTTP:
    POST /speech   multipart: file=<audio, WAV best>, language=en|hi|te (optional)  -> hearing message
    POST /text     JSON {"content": "...", "language": "en"}                         -> hearing message
    POST /gloss    JSON {"content": "ME HOT YESTERDAY TODAY", "emotion": "neutral"}  -> gloss message (testing)
    GET  /tts?text=...&language=en&emotion=neutral  -> audio/mpeg
    GET  /quick_replies    GET /health
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from signbridge_speech import asr, config, llm, tts
from signbridge_speech.messages import make_message
from signbridge_speech.pipeline import QUICK_REPLIES, Conversation

log = logging.getLogger("speech_service")
FORWARD_TO_SIGN = {"flush", "reset", "pause", "resume"}


class TextIn(BaseModel):
    content: str
    language: str = "en"


class GlossIn(BaseModel):
    content: str
    emotion: str = "neutral"


class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.upstream = None                   # websocket to sign_service
        self.sign_connected = False

    async def broadcast(self, msg: dict):
        text = json.dumps(msg, ensure_ascii=False)
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001
                self.clients.discard(ws)

    async def to_sign(self, cmd: str) -> bool:
        if self.upstream is None:
            return False
        try:
            await self.upstream.send(json.dumps({"cmd": cmd}))
            return True
        except Exception:  # noqa: BLE001
            return False


async def sign_listener(hub: Hub, conv: Conversation, url: str):
    """Keep a connection to sign_service; fill `sentence` in every gloss and re-broadcast."""
    from websockets.asyncio.client import connect
    while True:
        try:
            async with connect(url, max_size=2**20) as ws:
                hub.upstream, hub.sign_connected = ws, True
                log.info("connected to sign_service at %s", url)
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "gloss":
                        msg = await conv.on_gloss(msg)
                        log.info("gloss %-28s -> %s [%s]", msg["content"], msg["sentence"], msg["source"])
                    await hub.broadcast(msg)       # gloss_partial / status are forwarded unchanged
        except (OSError, asyncio.TimeoutError) as e:
            log.debug("sign_service not reachable: %s", e)
        except Exception as e:  # noqa: BLE001 - connection closed etc.
            log.warning("sign_service connection lost: %s", e)
        if hub.sign_connected:
            await hub.broadcast(make_message("system", "status", "sign_service_disconnected", ""))
        hub.upstream, hub.sign_connected = None, False
        await asyncio.sleep(2.0)


def build_app(args) -> FastAPI:
    hub, conv = Hub(), Conversation()
    if args.no_llm:
        config.USE_LLM = False

    @asynccontextmanager
    async def lifespan(_app):
        tasks = []
        if not args.no_sign:
            tasks.append(asyncio.create_task(sign_listener(hub, conv, args.sign_url)))
        if args.preload_whisper:
            asyncio.get_running_loop().run_in_executor(None, asr.available)
        log.info("AI: %s", await llm.status())
        tasks.append(asyncio.create_task(llm.warm_up()))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="SignBridge speech_service", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    async def hearing(text: str, language: str, confidence: float = 1.0, english_hint: str | None = None,
                      type_: str = "speech") -> dict:
        m = await conv.on_hearing_text(text, language, confidence, english_hint, type_)
        log.info("hearing %r -> %s | %s [%s]", text, m["sentence"], m["gloss"], m["source"])
        await hub.broadcast(m)
        return m

    @app.get("/health")
    async def health():
        return {"ok": True, "llm": await llm.status(),
                "sign_service": hub.sign_connected, "whisper": asr.status(), "clients": len(hub.clients),
                "listener_language": conv.listener_language, "avatar_vocab": list(conv.clips)}

    @app.get("/quick_replies")
    def quick_replies():
        return QUICK_REPLIES

    @app.post("/text")
    async def text_in(body: TextIn):
        return await hearing(body.content, body.language, type_="text")

    @app.post("/gloss")
    async def gloss_in(body: GlossIn):
        msg = make_message("signer", "gloss", body.content.upper(), "", emotion=body.emotion)
        msg = await conv.on_gloss(msg)
        await hub.broadcast(msg)
        return msg

    @app.post("/speech")
    async def speech_in(file: UploadFile = File(...), language: str | None = Form(None)):
        data = await file.read()
        if not await asyncio.to_thread(asr.available):
            raise HTTPException(503, f"Whisper not available on this machine ({asr.status()['error']}). "
                                     "Send text to /text or {'cmd':'text'} on /ws instead.")
        lang = language if language in config.LANG_NAMES else None
        try:
            r = await asyncio.to_thread(asr.transcribe, data, lang)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"could not decode/transcribe audio: {e}") from e
        if not r["text"]:
            raise HTTPException(422, "no speech detected")
        hint = None
        if r["language"] != "en" and not await llm.reachable():  # no AI: let Whisper translate to English
            hint = (await asyncio.to_thread(asr.transcribe, data, r["language"], True))["text"]
        return await hearing(r["text"], r["language"], r["confidence"], hint)

    @app.get("/tts")
    async def tts_get(text: str, language: str = "en", emotion: str = "neutral"):
        try:
            audio = await tts.synthesize(text, language, emotion)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"TTS unavailable ({e}); use the browser's speechSynthesis") from e
        return Response(audio, media_type="audio/mpeg")

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        hub.clients.add(sock)
        try:
            while True:
                try:
                    data = json.loads(await sock.receive_text())
                except json.JSONDecodeError:
                    continue
                cmd = data.get("cmd", "")
                if cmd in FORWARD_TO_SIGN:
                    await hub.to_sign(cmd)
                elif cmd == "text" and data.get("content", "").strip():
                    await hearing(data["content"], data.get("language", "en"),
                                  float(data.get("confidence", 1.0)), type_="text")
                elif cmd == "quick_reply":
                    m = conv.quick_reply(data.get("id", ""))
                    if m:
                        await hub.broadcast(m)
                elif cmd == "sos":
                    await hub.broadcast(conv.sos())
                elif cmd == "set_language" and data.get("language") in config.LANG_NAMES:
                    conv.listener_language = data["language"]
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(sock)

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8002)
    ap.add_argument("--sign-url", default=config.SIGN_WS_URL)
    ap.add_argument("--no-sign", action="store_true", help="don't connect to sign_service")
    ap.add_argument("--no-llm", action="store_true", help="rule-based only, no Claude calls")
    ap.add_argument("--preload-whisper", action="store_true", help="load Whisper at startup, not on first use")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2", "huggingface_hub", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    uvicorn.run(build_app(args), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

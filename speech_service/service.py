"""speech_service - Part B's deliverable (Speech, Language & AI): speech + language service on port 8002.

    python service.py                  # connects to sign_service on ws://localhost:8001/ws, serves port 8002
    python service.py --no-llm         # rules only (no AI calls)
    python service.py --no-sign        # don't connect to sign_service (test the speaker side alone)

Messages follow section 6 of the project doc. Part C connects ONLY to ws://localhost:8002/ws and receives:
    from "signer":   gloss (with `sentence` filled in), text (phrase board / suggestion tapped), alert (SOS)
                     gloss_partial, status   (forwarded unchanged from sign_service)
    from "speaker":  speech_partial (live caption), text (final caption + tone + gloss + clips for the avatar)
    from "system":   suggestions (smart quick replies), summary, status

Client -> server JSON commands on /ws:
    {"cmd":"partial", "content":"Do you have", "language":"en"}       live caption (browser speech interim result)
    {"cmd":"text", "content":"Do you have a fever?", "language":"en"}  speaker's final words (typed or browser STT)
    {"cmd":"quick_reply", "id":"water"}      phrase board        {"cmd":"quick_reply", "id":"s2"}  smart suggestion
    {"cmd":"sos"}     {"cmd":"summary"}     {"cmd":"new_conversation"}
    {"cmd":"set_language", "language":"hi"}       language the speaker wants to hear
    {"cmd":"flush"|"reset"|"pause"|"resume"}       forwarded to sign_service

HTTP:
    POST /speech           multipart file=<audio>, language=en|hi|te (optional)  -> final "text" message
    POST /speech_partial   same, for audio still being recorded (fast Whisper)    -> "speech_partial" message
    POST /text   {"content","language"}      POST /gloss {"content","emotion"}   (testing)
    GET  /suggestions      GET /summary      GET /transcript      GET /quick_replies
    GET  /tts?text=...&language=en&emotion=neutral  -> audio/mpeg
    GET  /health
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
    background: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(_app):
        tasks = []
        if not args.no_sign:
            tasks.append(asyncio.create_task(sign_listener(hub, conv, args.sign_url)))
        if args.preload_whisper:
            asyncio.get_running_loop().run_in_executor(None, asr.local_available)   # offline fallback ready
        log.info("AI: %s", await llm.status())
        tasks.append(asyncio.create_task(llm.warm_up()))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="SignBridge speech_service", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    async def send_suggestions():
        m = await conv.suggest()
        log.info("suggestions: %s [%s]", " | ".join(s["text_en"] for s in m["suggestions"]), m["source"])
        await hub.broadcast(m)

    async def speaker(text: str, language: str, confidence: float = 1.0, english_hint: str | None = None,
                      input_: str = "speech") -> dict:
        m = await conv.on_speaker_text(text, language, confidence, english_hint, input_)
        log.info("speaker %r -> %s | %s (%s) [%s]", text, m["sentence"], m["gloss"], m["emotion"], m["source"])
        await hub.broadcast(m)
        t = asyncio.create_task(send_suggestions())    # smart replies follow a moment later
        background.add(t)
        t.add_done_callback(background.discard)
        return m

    @app.get("/health")
    async def health():
        return {"ok": True, "llm": await llm.status(),
                "sign_service": hub.sign_connected, "whisper": asr.status(), "clients": len(hub.clients),
                "listener_language": conv.listener_language, "avatar_vocab": list(conv.clips)}

    @app.get("/quick_replies")
    def quick_replies():
        return QUICK_REPLIES

    @app.get("/suggestions")
    async def suggestions():
        return await conv.suggest()

    @app.get("/summary")
    async def summary():
        return await conv.summary()

    @app.get("/transcript")
    def transcript():
        return conv.transcript

    @app.post("/text")
    async def text_in(body: TextIn):
        return await speaker(body.content, body.language, input_="text")

    @app.post("/gloss")
    async def gloss_in(body: GlossIn):
        msg = make_message("signer", "gloss", body.content.upper(), "", emotion=body.emotion)
        msg = await conv.on_gloss(msg)
        await hub.broadcast(msg)
        return msg

    async def _transcribe(file: UploadFile, language: str | None, fast: bool) -> tuple[dict, bytes]:
        data = await file.read()
        if not await asyncio.to_thread(asr.available):
            raise HTTPException(503, f"Whisper not available on this machine ({asr.status()['error']}). "
                                     "Send text to /text or {'cmd':'text'} on /ws instead.")
        lang = language if language in config.LANG_NAMES else None
        try:
            return await asyncio.to_thread(asr.transcribe, data, lang, False, fast), data
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"could not decode/transcribe audio: {e}") from e

    @app.post("/speech")
    async def speech_in(file: UploadFile = File(...), language: str | None = Form(None)):
        r, data = await _transcribe(file, language, fast=False)
        if not r["text"]:
            raise HTTPException(422, "no speech detected")
        hint = None
        if r["language"] != "en" and not await llm.reachable():  # no AI: let Whisper translate to English
            try:
                hint = (await asyncio.to_thread(asr.transcribe, data, r["language"], True))["text"]
            except Exception as e:  # noqa: BLE001 - local Whisper not available
                log.warning("translate pass failed: %s", e)
        m = await speaker(r["text"], r["language"], r["confidence"], hint)
        return {**m, "asr": r.get("asr")}

    @app.post("/speech_partial")
    async def speech_partial_in(file: UploadFile = File(...), language: str | None = Form(None)):
        r, _ = await _transcribe(file, language, fast=True)
        m = conv.partial(r["text"], r["language"], r["confidence"])
        if r["text"]:
            await hub.broadcast(m)
        return m

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
                content = str(data.get("content", "")).strip()
                if cmd in FORWARD_TO_SIGN:
                    await hub.to_sign(cmd)
                elif cmd == "partial" and content:
                    await hub.broadcast(conv.partial(content, data.get("language", "en"),
                                                     float(data.get("confidence", 1.0))))
                elif cmd == "text" and content:
                    await speaker(content, data.get("language", "en"), float(data.get("confidence", 1.0)),
                                  input_=data.get("input", "text"))
                elif cmd == "quick_reply":
                    m = conv.quick_reply(str(data.get("id", "")))
                    if m:
                        await hub.broadcast(m)
                elif cmd == "sos":
                    await hub.broadcast(conv.sos())
                elif cmd == "summary":
                    await hub.broadcast(await conv.summary())
                elif cmd == "new_conversation":
                    conv.reset()
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
    ap.add_argument("--no-llm", action="store_true", help="rule-based only, no AI calls")
    ap.add_argument("--preload-whisper", action="store_true", help="load Whisper at startup, not on first use")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2", "huggingface_hub", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    uvicorn.run(build_app(args), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

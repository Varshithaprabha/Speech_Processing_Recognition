"""sign_service - Part A's deliverable.

Runs the camera + recogniser and streams shared-format messages over WebSocket.

    python service.py                       # webcam 0, port 8001
    python service.py --camera 1
    python service.py --source demo.mp4     # feed a video file instead of the webcam (testing)
    python service.py --mock                # no camera/model: scripted messages for Parts B & C

Endpoints
    WS   /ws           server -> client: shared-format messages
                         type "gloss_partial"  words recognised so far (live feedback)
                         type "gloss"          finished signed sentence -> send to Part B
                         type "status"         {"content": "signing" | "idle" | "camera_error"}
                       client -> server (optional JSON commands):
                         {"cmd": "flush"}  finish the sentence now (e.g. a "Send" button)
                         {"cmd": "reset"}  clear words recognised so far
                         {"cmd": "pause"} / {"cmd": "resume"}
    GET  /video_feed   MJPEG camera preview with skeleton (use as <img src=...>)
    GET  /health       {"ok": true, "mode": ..., "classes": [...]}
    GET  /vocab        list of glosses this model knows
    POST /predict      multipart "file" = video of ONE sign -> {gloss, confidence, top3}
    POST /predict_sequence  video of several signs -> the gloss message
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

os.environ.setdefault("GLOG_minloglevel", "2")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

from signbridge_sign import config  # noqa: E402
from signbridge_sign.messages import make_message  # noqa: E402

MOCK_SENTENCES = [
    (["HELLO"], "neutral"),
    (["ME", "SICK"], "neutral"),
    (["ME", "HOT", "YESTERDAY", "TODAY"], "neutral"),
    (["DOCTOR", "HOSPITAL"], "question"),
    (["MEDICINE", "GOOD"], "neutral"),
    (["MOTHER", "FATHER", "FAMILY"], "urgent"),
    (["THANK-YOU"], "happy"),
]


class Hub:
    """Fan-out of messages from the camera thread to all WebSocket clients."""

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.commands: list[str] = []
        self.lock = threading.Lock()

    def publish(self, msg: dict):                      # thread-safe
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._send(msg), self.loop)

    async def _send(self, msg: dict):
        text = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001
                self.clients.discard(ws)

    def push_cmd(self, cmd: str):
        with self.lock:
            self.commands.append(cmd)

    def pop_cmds(self) -> list[str]:
        with self.lock:
            c, self.commands = self.commands, []
        return c


def status_msg(state: str) -> dict:
    return make_message("status", [state], 1.0)


class CameraWorker(threading.Thread):
    def __init__(self, hub: Hub, source, settings=None):
        super().__init__(daemon=True)
        from signbridge_sign.landmarks import Landmarker
        from signbridge_sign.model import Predictor
        from signbridge_sign.recognizer import ContinuousRecognizer

        self.hub, self.source = hub, source
        self.predictor = Predictor()
        self.rec = ContinuousRecognizer(self.predictor, settings)
        self.lm = Landmarker()
        self.jpeg: bytes | None = None
        self.paused = False
        self.fps = 0.0

    def _open(self):
        if isinstance(self.source, int) and os.name == "nt":
            cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(self.source)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        return cap

    def run(self):
        from signbridge_sign.landmarks import draw
        cap = self._open()
        is_file = not isinstance(self.source, int)
        file_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        t0, n, last_status, ft = time.time(), 0, "idle", time.time()
        while True:
            ok, frame = cap.read()
            if not ok:
                if is_file:                               # loop test videos
                    for m in self.rec.flush():
                        self.hub.publish(m)
                    cap.release()
                    time.sleep(1.0)
                    cap = self._open()
                    continue
                self.hub.publish(status_msg("camera_error"))
                time.sleep(1.0)
                cap.release()
                cap = self._open()
                continue
            n += 1
            t = n / file_fps if is_file else time.time() - t0
            for cmd in self.hub.pop_cmds():
                if cmd == "flush":
                    for m in self.rec.flush():
                        self.hub.publish(m)
                elif cmd == "reset":
                    self.rec.reset()
                elif cmd in ("pause", "resume"):
                    self.paused = cmd == "pause"
            raw = self.lm.process(frame, int(t * 1000))
            if not self.paused:
                for m in self.rec.feed(raw, t):
                    self.hub.publish(m)
                if self.rec.status != last_status:
                    last_status = self.rec.status
                    self.hub.publish(status_msg(last_status))
            # preview
            view = cv2.flip(draw(frame, raw), 1)
            if self.rec.status == "signing":
                cv2.circle(view, (30, 30), 12, (0, 0, 255), -1)
            words = " ".join(w for w, _ in self.rec.st.words)
            if words:
                cv2.putText(view, words, (20, view.shape[0] - 25), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 3)
            view = cv2.resize(view, (640, int(view.shape[0] * 640 / view.shape[1])))
            self.jpeg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes()
            if n % 30 == 0:
                self.fps, ft = 30 / (time.time() - ft), time.time()
            if is_file:
                time.sleep(max(0.0, 1 / file_fps - 0.005))


class MockWorker(threading.Thread):
    """Emits scripted signer sentences so Parts B and C can integrate before the model is ready."""

    def __init__(self, hub: Hub, every: float):
        super().__init__(daemon=True)
        self.hub, self.every = hub, every
        self.jpeg = None
        self.paused = False
        self.fps = 0.0

    def run(self):
        i = 0
        while True:
            glosses, emotion = MOCK_SENTENCES[i % len(MOCK_SENTENCES)]
            i += 1
            deadline = time.time() + self.every
            while time.time() < deadline:            # react to commands while waiting
                if "flush" in self.hub.pop_cmds():
                    break
                time.sleep(0.1)
            if self.paused:
                continue
            self.hub.publish(status_msg("signing"))
            for k in range(1, len(glosses) + 1):
                time.sleep(0.6)
                self.hub.publish(make_message("gloss_partial", glosses[:k], 0.9))
            self.hub.publish(status_msg("idle"))
            self.hub.publish(make_message("gloss", glosses, round(float(np.random.uniform(0.75, 0.97)), 2),
                                          emotion=emotion))


def build_app(args) -> FastAPI:
    hub = Hub()
    worker: dict = {}

    @asynccontextmanager
    async def lifespan(_app):
        await _start()
        yield

    app = FastAPI(title="SignBridge sign_service", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    async def _start():
        hub.loop = asyncio.get_running_loop()
        if args.mock:
            w = MockWorker(hub, args.mock_every)
        else:
            from signbridge_sign.recognizer import Settings
            src = args.source if args.source else args.camera
            w = CameraWorker(hub, src, Settings(min_conf=args.min_conf))
        worker["w"] = w
        w.start()

    @app.get("/health")
    def health():
        w = worker.get("w")
        classes = config.glosses() if args.mock else w.predictor.classes
        return {"ok": True, "mode": "mock" if args.mock else "camera", "fps": round(w.fps, 1),
                "classes": classes, "clients": len(hub.clients)}

    @app.get("/vocab")
    def vocab():
        return config.glosses() if args.mock else worker["w"].predictor.classes

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        hub.clients.add(sock)
        try:
            while True:
                try:
                    cmd = json.loads(await sock.receive_text()).get("cmd", "")
                except json.JSONDecodeError:
                    continue
                if cmd in ("pause", "resume"):
                    worker["w"].paused = cmd == "pause"
                hub.push_cmd(cmd)
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(sock)

    @app.get("/video_feed")
    async def video_feed():
        async def gen():
            while True:
                j = worker["w"].jpeg
                if j:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + j + b"\r\n"
                await asyncio.sleep(1 / 20)
        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    def _video_raw(data: bytes, suffix: str) -> np.ndarray:
        from signbridge_sign.landmarks import video_to_keypoints
        with tempfile.NamedTemporaryFile(suffix=suffix or ".mp4", delete=False) as f:
            f.write(data)
        try:
            return video_to_keypoints(Path(f.name))
        finally:
            os.unlink(f.name)

    @app.post("/predict")
    async def predict(file: UploadFile = File(...)):
        if args.mock:
            return {"gloss": "HELLO", "confidence": 0.9, "top3": [["HELLO", 0.9]]}
        raw = await asyncio.to_thread(_video_raw, await file.read(), Path(file.filename or "").suffix)
        top = worker["w"].predictor.predict_raw(raw)
        return {"gloss": top[0][0], "confidence": round(top[0][1], 3),
                "top3": [[g, round(c, 3)] for g, c in top]}

    @app.post("/predict_sequence")
    async def predict_sequence(file: UploadFile = File(...)):
        if args.mock:
            return make_message("gloss", ["ME", "SICK"], 0.9)
        from signbridge_sign.recognizer import ContinuousRecognizer, Settings
        raw = await asyncio.to_thread(_video_raw, await file.read(), Path(file.filename or "").suffix)
        rec = ContinuousRecognizer(worker["w"].predictor, Settings(min_conf=args.min_conf))
        msgs = []
        for i, r in enumerate(raw):                    # video_to_keypoints samples at 15 fps
            msgs += rec.feed(r, i / 15.0)
        msgs += rec.flush()
        finals = [m for m in msgs if m["type"] == "gloss"]
        return finals[-1] if finals else make_message("gloss", [], 0.0)

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--source", default=None, help="video file instead of webcam")
    ap.add_argument("--min-conf", type=float, default=0.45)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--mock-every", type=float, default=8.0, help="seconds between mock sentences")
    args = ap.parse_args()
    if not args.mock and not config.CLASSIFIER_PATH.exists():
        raise SystemExit("No trained model yet (models/sign_classifier.pt). Train it, or run with --mock.")
    uvicorn.run(build_app(args), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

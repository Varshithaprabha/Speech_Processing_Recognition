"""SignBridge app backend - Part C (App, Avatar & Integration), port 8000.

    python server.py            # serves the built web app (web/dist) + sign clips + history API
    python server.py --mock     # also fakes Part A + Part B at /mock, so the UI runs with nothing else started

The live conversation does not pass through here: the browser connects straight to speech_service
(ws://localhost:8002/ws), which already routes Part A <-> Part B <-> Part C (see speech_service/README.md).
This server adds what the app itself needs:

    GET  /clips/<GLOSS>.mp4 | .json | index.json     avatar clips from ../sign_service/clips
    GET  /api/history                                saved conversations (newest first)
    POST /api/history      {title, summary, key_points, transcript, language, signs}
    GET  /api/history/{id}         DELETE /api/history/{id}
    GET  /api/phrases              PUT /api/phrases  [{"id","text","emotion"}]   customised phrase board
    GET  /api/health
    /mock/ws, /mock/health, /mock/quick_replies    stand-in for speech_service (only with --mock)
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLIPS_DIR = ROOT / "sign_service" / "clips"
DIST_DIR = HERE / "web" / "dist"
DB_PATH = HERE / "data" / "signbridge.db"
IST = timezone(timedelta(hours=5, minutes=30))
log = logging.getLogger("app")

DEFAULT_PHRASES = [
    {"id": "c_doctor", "text": "I need a doctor.", "emotion": "urgent"},
    {"id": "c_deaf", "text": "I am Deaf. Please be patient with me.", "emotion": "neutral"},
    {"id": "c_slow", "text": "Please look at the screen when you speak.", "emotion": "neutral"},
]


class HistoryIn(BaseModel):
    title: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    transcript: list[dict] = Field(default_factory=list)
    language: str = "en"
    signs: list[str] = Field(default_factory=list)


class Phrase(BaseModel):
    id: str
    text: str
    emotion: str = "neutral"


def now() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, title TEXT, summary TEXT,
        key_points TEXT, transcript TEXT, language TEXT, signs TEXT)""")
    con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    return con


def row_to_dict(r: sqlite3.Row, full: bool) -> dict:
    d = {"id": r["id"], "created_at": r["created_at"], "title": r["title"], "summary": r["summary"],
         "language": r["language"], "signs": json.loads(r["signs"] or "[]")}
    if full:
        d["key_points"] = json.loads(r["key_points"] or "[]")
        d["transcript"] = json.loads(r["transcript"] or "[]")
    else:
        d["messages"] = len(json.loads(r["transcript"] or "[]"))
    return d


def build_app(args) -> FastAPI:
    app = FastAPI(title="SignBridge app (Part C)")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        return {"ok": True, "clips": CLIPS_DIR.is_dir(), "web": DIST_DIR.is_dir(), "mock": args.mock}

    # ------------------------------------------------------------------ history
    @app.get("/api/history")
    def history_list():
        with closing(db()) as con:
            rows = con.execute("SELECT * FROM conversations ORDER BY id DESC LIMIT 200").fetchall()
        return [row_to_dict(r, full=False) for r in rows]

    @app.get("/api/history/{cid}")
    def history_get(cid: int):
        with closing(db()) as con:
            r = con.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
        if not r:
            raise HTTPException(404, "not found")
        return row_to_dict(r, full=True)

    @app.post("/api/history")
    def history_save(body: HistoryIn):
        title = body.title.strip() or f"Conversation {datetime.now(IST):%d %b %Y, %H:%M}"
        with closing(db()) as con, con:
            cur = con.execute(
                "INSERT INTO conversations (created_at, title, summary, key_points, transcript, language, signs)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now(), title, body.summary, json.dumps(body.key_points, ensure_ascii=False),
                 json.dumps(body.transcript, ensure_ascii=False), body.language,
                 json.dumps(body.signs)))
            cid = cur.lastrowid
        return history_get(cid)

    @app.delete("/api/history/{cid}")
    def history_delete(cid: int):
        with closing(db()) as con, con:
            con.execute("DELETE FROM conversations WHERE id = ?", (cid,))
        return {"ok": True}

    # ------------------------------------------------------------------ phrase board
    @app.get("/api/phrases")
    def phrases_get():
        with closing(db()) as con:
            r = con.execute("SELECT value FROM settings WHERE key = 'phrases'").fetchone()
        return json.loads(r["value"]) if r else DEFAULT_PHRASES

    @app.put("/api/phrases")
    def phrases_put(body: list[Phrase]):
        data = [p.model_dump() for p in body if p.text.strip()][:40]
        with closing(db()) as con, con:
            con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('phrases', ?)",
                        (json.dumps(data, ensure_ascii=False),))
        return data

    # ------------------------------------------------------------------ mock Part A + B
    if args.mock:
        from mock_hub import attach_mock
        attach_mock(app, CLIPS_DIR)
        log.info("mock speech_service at /mock (use http://localhost:%d/mock as the speech URL)", args.port)

    # ------------------------------------------------------------------ static files
    if CLIPS_DIR.is_dir():
        app.mount("/clips", StaticFiles(directory=CLIPS_DIR), name="clips")
    else:
        log.warning("no clips at %s - the avatar will only show gloss words", CLIPS_DIR)

    if DIST_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = (DIST_DIR / path).resolve()
            if path and f.is_file() and DIST_DIR in f.parents:
                return FileResponse(f)
            return FileResponse(DIST_DIR / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def no_build():
            return JSONResponse({"error": "web app not built: cd web; npm install; npm run build "
                                          "(or use `npm run dev` on port 5173)"}, status_code=503)
    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--mock", action="store_true", help="serve a fake speech_service at /mock")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    print(f"SignBridge app: http://localhost:{args.port}" + ("  (mock mode)" if args.mock else ""))
    uvicorn.run(build_app(args), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

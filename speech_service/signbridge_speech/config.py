"""Settings for speech_service, read from environment variables / speech_service/.env."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent            # .../speech_service
REPO = ROOT.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:                                       # python-dotenv is optional
    pass

SIGN_WS_URL = os.getenv("SIGN_WS_URL", "ws://localhost:8001/ws")
# AI providers, tried in this order; rules.py is always the last fallback.
LLM_PROVIDERS = [p.strip() for p in os.getenv("LLM_PROVIDERS", "groq,ollama").split(",") if p.strip()]
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")       # supports strict JSON schema on Groq
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")       # only used if "anthropic" is listed
CLAUDE_EFFORT = os.getenv("CLAUDE_EFFORT", "low")
USE_LLM = os.getenv("USE_LLM", "1") != "0"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")      # tiny / base / small / medium
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
CLIPS_DIR = Path(os.getenv("CLIPS_DIR", REPO / "sign_service" / "clips"))

# Words sign_service can RECOGNISE (signer -> hearing). YOU was dropped (confused with ME).
SIGN_VOCAB = ["HELLO", "HOW-ARE-YOU", "THANK-YOU", "ME", "DOCTOR", "HOSPITAL", "SICK", "HOT", "GOOD",
              "BAD", "MEDICINE", "TODAY", "TOMORROW", "YESTERDAY", "MOTHER", "FATHER", "FAMILY"]

LANG_NAMES = {"en": "English", "hi": "Hindi", "te": "Telugu"}
EMOTIONS = ["neutral", "question", "urgent", "happy"]


def avatar_vocab() -> dict[str, dict]:
    """Words the AVATAR can play (hearing -> signer): every gloss with a clip, including YOU."""
    try:
        return json.loads((CLIPS_DIR / "index.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {g: {"video": f"{g}.mp4"} for g in SIGN_VOCAB + ["YOU"]}

"""AI language layer with free providers, tried in order (LLM_PROVIDERS, default "groq,ollama"):

  groq       free API key from console.groq.com (GROQ_API_KEY), model openai/gpt-oss-120b, strict JSON schema
  ollama     local model on this PC (no key, works offline), default gemma3:4b
  anthropic  optional, only if ANTHROPIC_API_KEY is set and "anthropic" is listed

Every public function returns None when all providers fail, so the caller falls back to rules.py.
"""
from __future__ import annotations

import json
import logging
import os
import time

import httpx

from . import config

log = logging.getLogger("speech_service.llm")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_http: httpx.AsyncClient | None = None
_ollama_ok: tuple[float, bool] = (0.0, False)          # (checked_at, reachable)


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=3.0))
    return _http


def providers() -> list[str]:
    """Providers that are configured (not necessarily reachable right now)."""
    if not config.USE_LLM:
        return []
    out = []
    for p in config.LLM_PROVIDERS:
        if p == "groq" and os.getenv("GROQ_API_KEY"):
            out.append(p)
        elif p == "ollama":
            out.append(p)
        elif p == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
            out.append(p)
    return out


def available() -> bool:
    return bool(providers())


async def _ollama_reachable() -> bool:
    global _ollama_ok
    checked, ok = _ollama_ok
    if time.time() - checked < 30:
        return ok
    try:
        r = await _client().get(f"{config.OLLAMA_URL}/api/tags", timeout=2.0)
        ok = r.status_code == 200
    except httpx.HTTPError:
        ok = False
    _ollama_ok = (time.time(), ok)
    return ok


async def warm_up() -> None:
    """Load the Ollama model into GPU memory now, so the first real sentence isn't slow."""
    if "ollama" not in providers() or not await _ollama_reachable():
        return
    try:
        await _client().post(f"{config.OLLAMA_URL}/api/generate",
                             json={"model": config.OLLAMA_MODEL, "keep_alive": "30m"}, timeout=120.0)
        log.info("Ollama model %s loaded", config.OLLAMA_MODEL)
    except httpx.HTTPError as e:
        log.warning("Ollama warm-up failed: %s", e)


async def reachable() -> bool:
    """True if at least one provider can probably answer right now (cloud keys assumed online)."""
    p = providers()
    return any(x in p for x in ("groq", "anthropic")) or ("ollama" in p and await _ollama_reachable())


async def status() -> dict:
    return {"providers": providers(), "groq_model": config.GROQ_MODEL if "groq" in providers() else None,
            "ollama_model": config.OLLAMA_MODEL, "ollama_reachable": await _ollama_reachable()}


# ------------------------------------------------------------------------------ providers

async def _groq(system: str, user: str, schema: dict) -> dict | None:
    body = {
        "model": config.GROQ_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "signbridge", "strict": True, "schema": schema}},
        "temperature": 0,
        "max_completion_tokens": 2000,
    }
    r = await _client().post(GROQ_URL, json=body, timeout=15.0,
                             headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"})
    if r.status_code != 200:
        log.warning("Groq HTTP %s: %s", r.status_code, r.text[:200])
        return None
    return json.loads(r.json()["choices"][0]["message"]["content"])


async def _ollama(system: str, user: str, schema: dict) -> dict | None:
    if not await _ollama_reachable():
        return None
    body = {
        "model": config.OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,                               # Ollama structured outputs
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0},
    }
    r = await _client().post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=60.0)
    if r.status_code != 200:
        log.warning("Ollama HTTP %s: %s", r.status_code, r.text[:200])
        return None
    return json.loads(r.json()["message"]["content"])


async def _anthropic(system: str, user: str, schema: dict) -> dict | None:
    import anthropic
    client = anthropic.AsyncAnthropic(timeout=20.0, max_retries=1)
    resp = await client.beta.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=4000, system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": config.CLAUDE_EFFORT, "format": {"type": "json_schema", "schema": schema}},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    )
    if resp.stop_reason in ("refusal", "max_tokens"):
        return None
    return json.loads(next((b.text for b in resp.content if b.type == "text"), ""))


PROVIDERS = {"groq": _groq, "ollama": _ollama, "anthropic": _anthropic}


async def _call(system: str, user: str, schema: dict, validate) -> tuple[dict, str] | None:
    """Try each provider in order; return (validated result, provider name) or None."""
    for name in providers():
        t = time.time()
        try:
            out = await PROVIDERS[name](system, user, schema)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            log.warning("%s failed: %s: %s", name, type(e).__name__, e)
            continue
        except Exception as e:  # noqa: BLE001 - e.g. anthropic SDK errors
            log.warning("%s failed: %s: %s", name, type(e).__name__, e)
            continue
        out = validate(out) if isinstance(out, dict) else None
        if out:
            log.debug("%s answered in %.1fs", name, time.time() - t)
            return out, name
        log.warning("%s returned unusable output", name)
    return None


# ------------------------------------------------------------------------------ prompts

GLOSS_SYSTEM = """You are the voice of a Deaf patient in an Indian hospital who signs in Indian Sign Language (ISL).
A sign recogniser turns their signs into GLOSS: English words in ISL order, without grammar.
Turn the gloss into the short, natural sentence the patient means, in the first person, said to a doctor or nurse.

The recogniser only knows these 17 signs:
HELLO, HOW-ARE-YOU, THANK-YOU, ME (I/me/my), DOCTOR, HOSPITAL, SICK (ill/unwell), HOT (fever),
GOOD (fine/better/good), BAD (unwell/worse/bad), MEDICINE, TODAY, TOMORROW, YESTERDAY, MOTHER, FATHER, FAMILY.

Rules:
- "YESTERDAY TODAY" together means "since yesterday". Infer tense from time words.
- A missing subject means "I". ME HOT = "I have a fever" (not "I am hot").
- MEDICINE GOOD = the medicine is helping. ME DOCTOR = I need a doctor.
- emotion "question" = the signer asked a question; "urgent" = make it direct and urgent.
- You also get a DRAFT made by a grammar program. It is usually right about the meaning, only clumsy.
  Keep its meaning; just make it natural. Change the meaning only if the draft is clearly wrong for the gloss.
- Use the recent conversation ONLY to resolve very short answers (doctor asked "Since when?", gloss YESTERDAY -> "Since yesterday.").
  Do not carry earlier topics into the new sentence.
- Words with confidence below 0.6 may be misrecognised; prefer the reading that fits the conversation.
- Never add facts, feelings or worries that are not in the gloss. One or two short sentences.
- Only people/family words with "urgent" = asking for them to be called.

Reply with JSON only: {"sentence_en": English sentence, "sentence": the same sentence in the listener's
language (identical to sentence_en if the listener language is English; Devanagari for Hindi, Telugu script
for Telugu), "emotion": one of neutral, question, urgent, happy}.

Examples:
ME HOT YESTERDAY TODAY (neutral, English) -> {"sentence_en": "I've had a fever since yesterday.", "sentence": "I've had a fever since yesterday.", "emotion": "neutral"}
DOCTOR TOMORROW (question, Hindi) -> {"sentence_en": "Will the doctor come tomorrow?", "sentence": "क्या डॉक्टर कल आएंगे?", "emotion": "question"}
MOTHER FATHER (urgent, English) -> {"sentence_en": "Please call my mother and father!", "sentence": "Please call my mother and father!", "emotion": "urgent"}
DOCTOR YOU (question, English) -> {"sentence_en": "Are you the doctor?", "sentence": "Are you the doctor?", "emotion": "question"}"""

TEXT_SYSTEM_TMPL = """You help a hearing doctor or nurse in an Indian hospital talk to a Deaf patient. The patient
watches an avatar that can only play these ISL signs (glosses):
{vocab}

The hearing person's words may be English, Hindi, Telugu or a mix (maybe romanised, maybe with speech-to-text errors).
Reply with JSON only:
- "english": a short, clean English caption of what they said (translate if needed, keep the meaning exactly).
- "gloss": the ISL rendering using ONLY the allowed glosses above, in ISL order: greeting first, then time
  words, then subject, then the rest. Drop articles and helper verbs. 1-6 signs. ME = the speaker,
  YOU = the patient. HOT = fever/temperature, SICK = ill/pain. Empty list if nothing fits.
- "emotion": "question" for questions, "urgent" for emergencies or instructions needed right now,
  "happy" for good news or thanks, otherwise "neutral".

Examples:
"Did you take your medicine today?" -> {{"english": "Did you take your medicine today?", "gloss": ["TODAY", "YOU", "MEDICINE"], "emotion": "question"}}
"Aapko kal se bukhar hai?" -> {{"english": "Have you had a fever since yesterday?", "gloss": ["YESTERDAY", "TODAY", "YOU", "HOT"], "emotion": "question"}}"""


def _history_block(history: list[dict]) -> str:
    if not history:
        return "(start of conversation)"
    lines = []
    for h in history[-4:]:
        who = "Patient (signed)" if h.get("from") == "signer" else "Doctor/nurse (spoke)"
        lines.append(f"{who}: {h.get('sentence_en') or h.get('sentence') or h.get('content')}")
    return "\n".join(lines)


def _emotion(e) -> str:
    return e if e in config.EMOTIONS else "neutral"


# ------------------------------------------------------------------------------ public API

async def gloss_to_sentence(glosses: list[str], emotion: str, words: list[dict] | None,
                            listener_language: str, history: list[dict], draft: str = "") -> dict | None:
    """-> {"sentence_en", "sentence", "emotion", "provider"} or None."""
    if not available() or not glosses:
        return None
    lang = config.LANG_NAMES.get(listener_language, "English")
    conf = ", ".join(f"{w['gloss']}={w.get('confidence', 1):.2f}" for w in (words or []) if "gloss" in w)
    user = (f"Recent conversation:\n{_history_block(history)}\n\n"
            f"Gloss: {' '.join(glosses)}\nSigner emotion: {emotion}\n"
            + (f"Per-word confidence: {conf}\n" if conf else "")
            + (f"Draft: {draft}\n" if draft else "")
            + f"Listener language: {lang}")
    schema = {"type": "object",
              "properties": {"sentence_en": {"type": "string"}, "sentence": {"type": "string"},
                             "emotion": {"type": "string", "enum": config.EMOTIONS}},
              "required": ["sentence_en", "sentence", "emotion"], "additionalProperties": False}

    def validate(o: dict) -> dict | None:
        en = str(o.get("sentence_en", "")).strip()
        if not en:
            return None
        s = str(o.get("sentence", "")).strip() or en
        return {"sentence_en": en, "sentence": en if listener_language == "en" else s,
                "emotion": _emotion(o.get("emotion"))}

    res = await _call(GLOSS_SYSTEM, user, schema, validate)
    if not res:
        return None
    out, provider = res
    return {**out, "provider": provider}


async def text_to_gloss(text: str, language: str, allowed: list[str], history: list[dict]) -> dict | None:
    """-> {"english", "gloss": [...], "emotion", "provider"} or None."""
    if not available() or not text.strip():
        return None
    system = TEXT_SYSTEM_TMPL.format(vocab=", ".join(allowed))
    user = (f"Recent conversation:\n{_history_block(history)}\n\n"
            f"Hearing person said ({config.LANG_NAMES.get(language, 'unknown language')}): {text}")
    schema = {"type": "object",
              "properties": {"english": {"type": "string"},
                             "gloss": {"type": "array", "items": {"type": "string", "enum": allowed}},
                             "emotion": {"type": "string", "enum": config.EMOTIONS}},
              "required": ["english", "gloss", "emotion"], "additionalProperties": False}

    def validate(o: dict) -> dict | None:
        en = str(o.get("english", "")).strip()
        if not en:
            return None
        gloss = [str(g).upper() for g in (o.get("gloss") or []) if str(g).upper() in allowed]
        return {"english": en, "gloss": gloss, "emotion": _emotion(o.get("emotion"))}

    res = await _call(system, user, schema, validate)
    if not res:
        return None
    out, provider = res
    return {**out, "provider": provider}

"""Quick check of the AI layer (Groq / Ollama) without running the service.

    python scripts/try_llm.py
    python scripts/try_llm.py --providers ollama --ollama-model llama3.2:3b
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

GLOSSES = [(["ME", "HOT", "YESTERDAY", "TODAY"], "neutral", "en"), (["MEDICINE", "GOOD"], "neutral", "en"),
           (["MOTHER", "FATHER", "FAMILY"], "urgent", "en"), (["ME", "SICK", "TODAY"], "neutral", "hi"),
           (["DOCTOR", "TOMORROW"], "question", "te")]
TEXTS = [("Did you take your medicine yesterday?", "en"), ("Aapko kal se bukhar hai?", "hi"),
         ("మీకు జ్వరం ఉందా?", "te"), ("Your family is waiting outside, they will see you tomorrow.", "en")]


async def main(a):
    if a.providers:
        os.environ["LLM_PROVIDERS"] = a.providers
    if a.ollama_model:
        os.environ["OLLAMA_MODEL"] = a.ollama_model
    from signbridge_speech import config, llm
    print("status:", await llm.status(), "\n")
    allowed = list(config.avatar_vocab())
    for g, emo, lang in GLOSSES:
        t = time.time()
        r = await llm.gloss_to_sentence(g, emo, None, lang, [])
        print(f"{' '.join(g):<24} {emo:<8} {lang} -> {r}  ({time.time() - t:.1f}s)")
    print()
    for text, lang in TEXTS:
        t = time.time()
        r = await llm.text_to_gloss(text, lang, allowed, [])
        print(f"{text!r} -> {r}  ({time.time() - t:.1f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers")
    ap.add_argument("--ollama-model")
    asyncio.run(main(ap.parse_args()))

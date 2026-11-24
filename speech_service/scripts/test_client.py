"""Pretend to be Part C: connect to speech_service, print everything, and play the speaker's side.

    python scripts/test_client.py                 # ~60 s scripted hospital conversation
    python scripts/test_client.py --seconds 90 --quiet-partials
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from websockets.asyncio.client import connect

sys.stdout.reconfigure(encoding="utf-8")


def speak(text: str, lang: str) -> list[dict]:
    """A browser would send growing interim results, then the final text."""
    words = text.split()
    parts = [{"cmd": "partial", "content": " ".join(words[:k]), "language": lang}
             for k in range(2, len(words), 2)]
    return parts + [{"cmd": "text", "content": text, "language": lang}]


SCRIPT = [
    speak("Hello, how are you feeling today?", "en"),
    speak("Did you take your medicine yesterday?", "en"),
    [{"cmd": "quick_reply", "id": "s1"}],                    # tap the first smart suggestion
    speak("మీకు నిన్నటి నుండి జ్వరం ఉందా?", "te"),          # Telugu: have you had a fever since yesterday?
    [{"cmd": "quick_reply", "id": "family"}],                # phrase board
    speak("WHY ARE YOU LATE FOR YOUR APPOINTMENT AGAIN", "en"),
    speak("You need to go to the hospital immediately!", "en"),
    [{"cmd": "sos"}],
    [{"cmd": "summary"}],
]


def show(m: dict, quiet_partials: bool):
    t, f = m.get("type"), m.get("from")
    if t in ("gloss_partial", "speech_partial") and quiet_partials:
        return
    if t == "status":
        print(f"  [status] {m['content']}")
    elif t == "gloss_partial":
        print(f"  [signing...] {m['content']}")
    elif t == "speech_partial":
        print(f"  [speaking...] {m['content']}")
    elif t == "suggestions":
        print("  [suggestions] " + " | ".join(f"{s['id']}: {s['text']}" for s in m["suggestions"])
              + f"  ({m['source']})")
    elif t == "summary":
        print(f"SUMMARY ({m['source']}): {m['content']}")
        for p in m.get("key_points", []):
            print(f"   - {p}")
    elif f == "signer":
        print(f"SIGNER  {t:<6} {m['content'][:30]:<30} -> \"{m['sentence']}\"  ({m['emotion']}, {m.get('language')}, {m.get('source')})")
    elif f == "speaker":
        print(f"SPEAKER {t:<6} \"{m['content']}\" -> caption \"{m['sentence']}\" | avatar: {m['gloss'] or '-'}"
              f"  ({m['emotion']}, {m.get('source')})")
    else:
        print("  ", m)


async def main(args):
    async with connect(args.url) as ws:
        print(f"connected to {args.url}\n")

        async def sender():
            gap = args.seconds / (len(SCRIPT) + 1)
            for step in SCRIPT:
                await asyncio.sleep(gap)
                for cmd in step:
                    await ws.send(json.dumps(cmd, ensure_ascii=False))
                    await asyncio.sleep(0.3)

        async def receiver():
            async for raw in ws:
                show(json.loads(raw), args.quiet_partials)

        s = asyncio.create_task(sender())
        try:
            await asyncio.wait_for(receiver(), timeout=args.seconds)
        except asyncio.TimeoutError:
            pass
        s.cancel()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8002/ws")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--quiet-partials", action="store_true")
    asyncio.run(main(ap.parse_args()))

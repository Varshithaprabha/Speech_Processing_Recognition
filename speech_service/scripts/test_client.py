"""Pretend to be Part C: connect to speech_service, print everything, and play the hearing side.

    python scripts/test_client.py                 # listen for 30 s, send a few hearing-side lines
    python scripts/test_client.py --seconds 60 --quiet-partials
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from websockets.asyncio.client import connect

sys.stdout.reconfigure(encoding="utf-8")

HEARING_LINES = [
    {"cmd": "text", "content": "Hello, how are you feeling today?", "language": "en"},
    {"cmd": "text", "content": "Did you take your medicine yesterday?", "language": "en"},
    {"cmd": "text", "content": "Aapko kal se bukhar hai?", "language": "hi"},
    {"cmd": "quick_reply", "id": "water"},
    {"cmd": "text", "content": "You need to go to the hospital immediately!", "language": "en"},
    {"cmd": "sos"},
]


def show(m: dict, quiet_partials: bool):
    t = m.get("type")
    if t == "gloss_partial" and quiet_partials:
        return
    if t == "status":
        print(f"  [status] {m['content']}")
    elif t == "gloss_partial":
        print(f"  [signing...] {m['content']}")
    elif m.get("from") == "signer":
        print(f"SIGNER  {t:<11} {m['content']:<26} -> \"{m['sentence']}\"  ({m['emotion']}, {m.get('language')}, {m.get('source')})")
    elif m.get("from") == "hearing":
        print(f"HEARING {t:<11} \"{m['content']}\" -> caption \"{m['sentence']}\" | avatar: {m['gloss'] or '-'}"
              f"  ({m['emotion']}, {m.get('source')}, {len(m.get('clips', []))} clips)")
    else:
        print("  ", m)


async def main(args):
    async with connect(args.url) as ws:
        print(f"connected to {args.url}\n")

        async def sender():
            for line in HEARING_LINES:
                await asyncio.sleep(args.seconds / (len(HEARING_LINES) + 1))
                await ws.send(json.dumps(line, ensure_ascii=False))

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
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--quiet-partials", action="store_true")
    asyncio.run(main(ap.parse_args()))

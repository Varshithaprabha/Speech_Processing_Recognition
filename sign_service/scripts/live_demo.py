"""Standalone live test of the recogniser (no server): webcam window with skeleton,
current sign status, recognised words and finished sentences printed as JSON.

    python scripts/live_demo.py
    python scripts/live_demo.py --camera 1 --min-conf 0.5
    python scripts/live_demo.py --source some_video.mp4

Keys: SPACE finish sentence now | C clear | Q quit
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("GLOG_minloglevel", "2")
import cv2  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from signbridge_sign.landmarks import Landmarker, draw  # noqa: E402
from signbridge_sign.model import Predictor  # noqa: E402
from signbridge_sign.recognizer import ContinuousRecognizer, Settings  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--source", default=None)
    ap.add_argument("--min-conf", type=float, default=0.45)
    args = ap.parse_args()

    src = args.source or args.camera
    cap = cv2.VideoCapture(src, cv2.CAP_DSHOW) if isinstance(src, int) and os.name == "nt" else cv2.VideoCapture(src)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    rec = ContinuousRecognizer(Predictor(), Settings(min_conf=args.min_conf))
    lm = Landmarker()
    t0, sentence, last = time.time(), "", ""
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = time.time() - t0
        raw = lm.process(frame, int(t * 1000))
        msgs = rec.feed(raw, t)
        k = cv2.waitKey(1) & 0xFF
        if k == ord(" "):
            msgs += rec.flush()
        elif k == ord("c"):
            rec.reset()
        elif k in (ord("q"), 27):
            break
        for m in msgs:
            if m["type"] == "gloss":
                sentence = m["content"]
                print(json.dumps(m, ensure_ascii=False))
        if rec.last_word:
            last = f"last: {rec.last_word[0]} ({rec.last_word[1]:.0%})"

        view = cv2.flip(draw(frame, raw), 1)
        h = view.shape[0]
        col = (0, 0, 255) if rec.status == "signing" else (160, 160, 160)
        cv2.circle(view, (30, 30), 12, col, -1)
        cv2.putText(view, rec.status, (50, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
        cv2.putText(view, last, (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(view, " ".join(w for w, _ in rec.st.words), (20, h - 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
        cv2.putText(view, f"sent: {sentence}", (20, h - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (120, 255, 120), 2)
        cv2.imshow("SignBridge - live sign recognition (SPACE send, C clear, Q quit)", view)
    cap.release()
    lm.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

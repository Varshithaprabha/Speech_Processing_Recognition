"""Standalone live test of the recogniser (no server): webcam window with skeleton,
current sign status, recognised words and finished sentences printed as JSON.

    python scripts/live_demo.py
    python scripts/live_demo.py --camera 1 --min-conf 0.5
    python scripts/live_demo.py --source some_video.mp4

Keys (click the video window first): SPACE finish sentence now | C clear | Q quit

The blue line on the preview is the "rest line": a wrist below it counts as hands DOWN.
Drop both wrists below it between signs, and keep them there ~1.5 s to finish the sentence.

Every run is saved to reports/live/<time>.jsonl (messages, sign segments, key presses) and
reports/live/<time>.npz (landmarks per frame), so the session can be checked and replayed later.
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
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from signbridge_sign import config  # noqa: E402
from signbridge_sign.features import raised  # noqa: E402
from signbridge_sign.landmarks import POSE_SL, Landmarker, draw  # noqa: E402
from signbridge_sign.model import Predictor  # noqa: E402
from signbridge_sign.recognizer import ContinuousRecognizer, Settings  # noqa: E402

WIN = "SignBridge - live sign recognition (SPACE send, C clear, Q quit)"


def rest_line_y(raw: np.ndarray, rest_y: float) -> float | None:
    """y of the rest line in frame-height units (None when the shoulders aren't seen)."""
    pose = raw[POSE_SL].reshape(33, 4)
    ls, rs = pose[11, :2], pose[12, :2]
    width = float(np.linalg.norm(ls - rs))
    if np.isnan(width) or width < 1e-3:
        return None
    return float((ls[1] + rs[1]) / 2 + rest_y * width)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--source", default=None)
    ap.add_argument("--min-conf", type=float, default=0.45)
    ap.add_argument("--rest-y", type=float, default=None, help="rest line, shoulder-widths below shoulders")
    args = ap.parse_args()

    src = args.source or args.camera
    cap = cv2.VideoCapture(src, cv2.CAP_DSHOW) if isinstance(src, int) and os.name == "nt" else cv2.VideoCapture(src)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    settings = Settings(min_conf=args.min_conf)
    if args.rest_y is not None:
        settings.rest_y = args.rest_y
    rec = ContinuousRecognizer(Predictor(), settings)
    lm = Landmarker()

    out = config.REPORTS / "live"
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log = open(out / f"{stamp}.jsonl", "w", encoding="utf-8", buffering=1)   # line-buffered

    def write(t, obj):
        log.write(json.dumps({"t": round(t, 3), **obj}, ensure_ascii=False) + "\n")

    write(0.0, {"event": "start", "rest_y": settings.rest_y, "min_conf": settings.min_conf,
                "sentence_gap": settings.sentence_gap, "source": str(src)})
    raws, times = [], []
    t0, sentence, last, status, segs = time.time(), "", "", "idle", 0
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = time.time() - t0
            raw = lm.process(frame, int(t * 1000))
            raws.append(raw)
            times.append(t)
            msgs = rec.feed(raw, t)
            k = cv2.waitKey(1) & 0xFF
            key = {ord(" "): "flush", ord("c"): "clear", ord("q"): "quit", 27: "quit"}.get(k)
            if key:
                write(t, {"key": key})
            if key == "flush":
                msgs += rec.flush()
            elif key == "clear":
                rec.reset()
            elif key == "quit":
                break
            if rec.segments != segs:
                segs = rec.segments
                write(t, {"segment": rec.last_segment})
            if rec.status != status:
                status = rec.status
                write(t, {"status": status})
            for m in msgs:
                write(t, m)
                if m["type"] == "gloss":
                    sentence = m["content"]
                    print(json.dumps(m, ensure_ascii=False))
            if rec.last_word:
                last = f"last: {rec.last_word[0]} ({rec.last_word[1]:.0%})"

            h = frame.shape[0]
            view = draw(frame, raw)
            ry = rest_line_y(raw, settings.rest_y)
            up = bool(raised(raw[None], settings.rest_y)[0])
            if ry is not None:
                cv2.line(view, (0, int(ry * h)), (view.shape[1], int(ry * h)), (255, 160, 0), 2)
            view = cv2.flip(view, 1)
            col = (0, 0, 255) if rec.status == "signing" else (160, 160, 160)
            cv2.circle(view, (30, 30), 12, col, -1)
            cv2.putText(view, rec.status, (50, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
            cv2.putText(view, "hands UP" if up else "hands DOWN", (view.shape[1] - 220, 38),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255) if up else (0, 220, 0), 2)
            cv2.putText(view, last, (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.putText(view, " ".join(w for w, _ in rec.st.words), (20, h - 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
            cv2.putText(view, f"sent: {sentence}", (20, h - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (120, 255, 120), 2)
            cv2.imshow(WIN, view)
            if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:      # closed with the X
                write(t, {"key": "window_closed"})
                break
    except KeyboardInterrupt:
        write(time.time() - t0, {"key": "ctrl_c"})
    finally:
        t = time.time() - t0
        for m in rec.flush():
            write(t, m)
            if m["type"] == "gloss":
                print(json.dumps(m, ensure_ascii=False))
        write(t, {"event": "end", "frames": len(raws)})
        log.close()
        if raws:
            np.savez_compressed(out / f"{stamp}.npz", raw=np.stack(raws).astype(np.float32), t=np.array(times))
        print(f"Saved session log: {out / stamp}.jsonl / .npz")
        cap.release()
        lm.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

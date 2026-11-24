"""Record webcam sign clips for fine-tuning (each teammate, 3-5 clips per word).

    python scripts/record_signs.py --signer varsh
    python scripts/record_signs.py --signer roshni --clips 4 --words HELLO,ME,DOCTOR
    python scripts/record_signs.py --signer varsh --camera 1

For every word the window shows the INCLUDE reference video (left) so people who do
not know ISL can copy the sign, and your camera with the detected skeleton (right).

Keys:  SPACE  record one clip (3-2-1 countdown, then ~2.5 s; press SPACE again to stop early)
       R      delete the last clip of this word      N / P  next / previous word
       Q/ESC  quit (everything recorded so far is kept)

Tips: start and end each clip with hands DOWN; sit at your normal laptop distance with
your upper body and both hands in frame; vary position/lighting slightly between clips.

Saves data/webcam_videos/<signer>/<GLOSS>/<n>.mp4 and data/keypoints/webcam/<signer>/<GLOSS>/<n>.npy
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from signbridge_sign import config  # noqa: E402
from signbridge_sign.landmarks import Landmarker, draw  # noqa: E402

H = 480


def reference_frames(gloss: str, max_frames: int = 90) -> list[np.ndarray]:
    """Frames of one INCLUDE video of this gloss (shown as a guide)."""
    from signbridge_sign.include_meta import load_metadata
    label = next((w["include_label"] for w in config.load_vocab() if w["gloss"] == gloss), None)
    clip = config.CLIPS_DIR / f"{gloss}.mp4"
    paths = [clip] if clip.exists() else []
    try:
        meta = load_metadata()
        paths += [config.VIDEO_DIR / p for p in meta[meta.label == label].video_path]
    except Exception:  # noqa: BLE001
        pass
    for p in paths:
        if p.exists():
            cap = cv2.VideoCapture(str(p))
            frames = []
            while len(frames) < max_frames:
                ok, f = cap.read()
                if not ok:
                    break
                frames.append(cv2.resize(f, (int(f.shape[1] * H / f.shape[0]), H)))
            cap.release()
            if frames:
                return frames[::2] if len(frames) > 60 else frames
    return []


def existing(signer: str, gloss: str) -> list[Path]:
    return sorted((config.KP_DIR / "webcam" / signer / gloss).glob("*.npy"), key=lambda p: int(p.stem))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signer", required=True, help="your name, e.g. varsh")
    ap.add_argument("--clips", type=int, default=5, help="target clips per word")
    ap.add_argument("--words", default="", help="comma-separated subset of glosses")
    ap.add_argument("--seconds", type=float, default=2.5)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--no-video", action="store_true", help="save only landmarks (no .mp4 copy)")
    args = ap.parse_args()

    signer = args.signer.strip().lower()
    words = config.glosses()
    if args.words:
        want = [w.strip().upper() for w in args.words.split(",")]
        words = [w for w in words if w in want]

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    if not cap.isOpened():
        sys.exit(f"Cannot open camera {args.camera}")
    lm = Landmarker()
    wi = next((i for i, w in enumerate(words) if len(existing(signer, w)) < args.clips), 0)
    ref, ref_for, ri = [], None, 0
    state, t_state, rec_frames, rec_kp = "ready", 0.0, [], []
    t0 = time.time()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        now = time.time()
        gloss = words[wi]
        if ref_for != gloss:
            ref, ref_for, ri = reference_frames(gloss), gloss, 0
        raw = lm.process(frame, int((now - t0) * 1000))

        if state == "countdown" and now - t_state >= 3:
            state, t_state, rec_frames, rec_kp = "recording", now, [], []
        if state == "recording":
            rec_frames.append(frame.copy())
            rec_kp.append(raw)
            if now - t_state >= args.seconds:
                state = "save"

        if state == "save":
            n = max([int(p.stem) for p in existing(signer, gloss)], default=-1) + 1
            kd = config.KP_DIR / "webcam" / signer / gloss
            vd = config.WEBCAM_VIDEO_DIR / signer / gloss
            kd.mkdir(parents=True, exist_ok=True)
            if not args.no_video:
                vd.mkdir(parents=True, exist_ok=True)
            np.save(kd / f"{n}.npy", np.stack(rec_kp).astype(np.float32))
            fps = len(rec_frames) / max(1e-3, now - t_state)
            if not args.no_video:                     # small copy, only for re-extraction later
                h, w = rec_frames[0].shape[:2]
                size = (640, int(h * 640 / w) // 2 * 2)
                vw = cv2.VideoWriter(str(vd / f"{n}.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
                for f in rec_frames:
                    vw.write(cv2.resize(f, size))
                vw.release()
            hands = np.mean([not (np.isnan(k[132]) and np.isnan(k[195])) for k in rec_kp])
            print(f"saved {signer}/{gloss}/{n}  ({len(rec_kp)} frames, {fps:.0f} fps, hands visible {hands:.0%})")
            state = "ready"
            if len(existing(signer, gloss)) >= args.clips and wi < len(words) - 1:
                wi += 1

        # ------------------------------------------------------------ UI
        view = cv2.flip(draw(frame.copy(), raw), 1)          # mirror for the user only
        view = cv2.resize(view, (int(view.shape[1] * H / view.shape[0]), H))
        if ref:
            r = ref[ri % len(ref)].copy()
            ri += 1
            cv2.putText(r, "reference (INCLUDE)", (10, H - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            view = np.hstack([r, view])
        done = len(existing(signer, gloss))
        bar = np.zeros((70, view.shape[1], 3), np.uint8)
        cv2.putText(bar, f"[{wi + 1}/{len(words)}] {gloss}   clips {done}/{args.clips}   signer: {signer}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        hint = {"ready": "SPACE record | R undo | N/P next/prev | Q quit",
                "countdown": f"get ready... {3 - int(now - t_state)}",
                "recording": "RECORDING - sign now (SPACE to stop)"}.get(state, "")
        cv2.putText(bar, hint, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 255) if state == "recording" else (180, 255, 180), 2)
        if state == "recording":
            cv2.circle(view, (view.shape[1] - 30, 30), 12, (0, 0, 255), -1)
        cv2.imshow("SignBridge - record signs", np.vstack([bar, view]))

        k = cv2.waitKey(1) & 0xFF
        if k in (ord("q"), 27):
            break
        if k == ord(" "):
            if state == "ready":
                state, t_state = "countdown", now
            elif state == "recording" and len(rec_kp) > 5:
                state = "save"
        elif state == "ready" and k == ord("n"):
            wi = min(wi + 1, len(words) - 1)
        elif state == "ready" and k == ord("p"):
            wi = max(wi - 1, 0)
        elif state == "ready" and k == ord("r"):
            ex = existing(signer, gloss)
            if ex:
                ex[-1].unlink()
                (config.WEBCAM_VIDEO_DIR / signer / gloss / f"{ex[-1].stem}.mp4").unlink(missing_ok=True)
                print(f"deleted {signer}/{gloss}/{ex[-1].stem}")

    cap.release()
    lm.close()
    cv2.destroyAllWindows()
    total = sum(len(existing(signer, w)) for w in words)
    print(f"{signer}: {total} clips recorded. Next: python scripts/train.py")


if __name__ == "__main__":
    main()

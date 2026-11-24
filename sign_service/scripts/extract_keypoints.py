"""Extract MediaPipe landmarks from videos -> .npy (T, 258) per video.

    python scripts/extract_keypoints.py                 # INCLUDE videos for vocab words
    python scripts/extract_keypoints.py --webcam        # re-extract recorded webcam clips
    python scripts/extract_keypoints.py --workers 6

Outputs
    data/keypoints/include/<GLOSS>/<split>__<video>.npy
    data/keypoints/webcam/<signer>/<GLOSS>/<clip>.npy
Already-extracted files are skipped, so it is safe to re-run while downloads continue.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from signbridge_sign import config  # noqa: E402

def _work(job):
    src, dst = job
    from signbridge_sign.landmarks import video_to_keypoints
    t = time.time()
    try:
        kp = video_to_keypoints(Path(src))     # fresh landmarker per video (no tracking carry-over)
    except Exception as e:  # noqa: BLE001
        return src, f"ERROR {e}"
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    np.save(dst, kp.astype(np.float32))
    hands = (~np.isnan(kp[:, 132]) | ~np.isnan(kp[:, 195])).mean() if len(kp) else 0
    return src, f"{len(kp)} frames, hands in {hands:.0%}, {time.time() - t:.1f}s"


def include_jobs():
    from signbridge_sign.include_meta import load_metadata
    vocab = {w["include_label"]: w["gloss"] for w in config.load_vocab()}
    meta = load_metadata()
    meta = meta[meta.label.isin(vocab)]
    jobs = []
    for r in meta.itertuples():
        src = config.VIDEO_DIR / r.video_path
        if not src.exists():
            continue
        dst = config.KP_DIR / "include" / vocab[r.label] / f"{r.split}__{Path(r.video_path).stem}.npy"
        if not dst.exists():
            jobs.append((str(src), str(dst)))
    return jobs, len(meta)


def webcam_jobs():
    jobs = []
    for src in config.WEBCAM_VIDEO_DIR.glob("*/*/*.mp4"):
        signer, gloss = src.parent.parent.name, src.parent.name
        dst = config.KP_DIR / "webcam" / signer / gloss / (src.stem + ".npy")
        if not dst.exists():
            jobs.append((str(src), str(dst)))
    return jobs, len(jobs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--webcam", action="store_true")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    args = ap.parse_args()

    jobs, total = webcam_jobs() if args.webcam else include_jobs()
    print(f"{len(jobs)} videos to process ({total} in vocab), {args.workers} workers")
    if not jobs:
        return
    t0 = time.time()
    with Pool(args.workers) as pool:
        for i, (src, msg) in enumerate(pool.imap_unordered(_work, jobs), 1):
            eta = (time.time() - t0) / i * (len(jobs) - i)
            print(f"[{i}/{len(jobs)} eta {eta / 60:.1f} min] {Path(src).parent.name}/{Path(src).name}: {msg}",
                  flush=True)
    print("Done. Next: python scripts/train.py")


if __name__ == "__main__":
    main()

"""Small per-gloss sign clips for Part C's avatar / sign player.

For each gloss we keep ONE short, trimmed, 480p H.264 clip (~100-300 KB) plus a JSON of
2-D landmarks (for a skeleton avatar), instead of the 10-15 MB studio originals.

    clips/<GLOSS>.mp4    browser-playable video of the sign
    clips/<GLOSS>.json   {"fps": 15, "frames": [{"pose": [[x,y]...], "left": [...]|null, "right": [...]|null}]}
    clips/index.json     {gloss: {"video": "...mp4", "landmarks": "...json", "duration": s}}
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

from . import config
from .features import raised
from .landmarks import LH_SL, POSE_SL, RH_SL

KP_FPS = 15.0


def _active_range(kp: np.ndarray, margin: int = 3) -> tuple[float, float]:
    hp = raised(kp)
    if hp.sum() < 3:
        return 0.0, len(kp) / KP_FPS
    idx = np.where(hp)[0]
    return max(0, idx[0] - margin) / KP_FPS, min(len(kp), idx[-1] + 1 + margin) / KP_FPS


def _landmark_json(kp: np.ndarray, t0: float, t1: float, aspect: float) -> dict:
    """x, y in [0, 1] of the clip frame (keypoints store x in frame-height units)."""
    seg = kp[int(t0 * KP_FPS):int(t1 * KP_FPS)].copy()
    T = len(seg)
    for sl, k in ((POSE_SL, 4), (LH_SL, 3), (RH_SL, 3)):
        part = seg[:, sl].reshape(T, -1, k)
        part[:, :, 0] /= aspect
        seg[:, sl] = part.reshape(T, -1)
    frames = []
    for r in seg:
        pose = r[POSE_SL].reshape(33, 4)[:25, :2]
        f = {"pose": None if np.isnan(pose[0, 0]) else np.round(pose, 4).tolist()}
        for name, sl in (("left", LH_SL), ("right", RH_SL)):
            h = r[sl].reshape(21, 3)[:, :2]
            f[name] = None if np.isnan(h[0, 0]) else np.round(h, 4).tolist()
        frames.append(f)
    return {"fps": KP_FPS, "aspect": round(aspect, 4), "frames": frames}


def make_clip(video: Path, kp: np.ndarray, gloss: str, out_dir: Path = config.CLIPS_DIR,
              update_index: bool = True) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    t0, t1 = _active_range(kp)
    cap = cv2.VideoCapture(str(video))
    aspect = (cap.get(cv2.CAP_PROP_FRAME_WIDTH) / cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 16 / 9
    cap.release()
    ffmpeg = shutil.which("ffmpeg")
    out = out_dir / f"{gloss}.mp4"
    if ffmpeg:
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{t0:.2f}", "-to", f"{t1:.2f}",
                        "-i", str(video), "-an", "-vf", "scale=-2:480,fps=25", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        str(out)], check=True)
    else:                                               # no ffmpeg: VP8 webm via OpenCV
        out = out_dir / f"{gloss}.webm"
        cap = cv2.VideoCapture(str(video))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
        w = None
        while cap.get(cv2.CAP_PROP_POS_MSEC) <= t1 * 1000:
            ok, f = cap.read()
            if not ok:
                break
            f = cv2.resize(f, (int(f.shape[1] * 480 / f.shape[0]) // 2 * 2, 480))
            if w is None:
                w = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"VP80"), fps, (f.shape[1], f.shape[0]))
            w.write(f)
        cap.release()
        if w:
            w.release()
    (out_dir / f"{gloss}.json").write_text(json.dumps(_landmark_json(kp, t0, t1, aspect)))
    if update_index:
        _update_index(out_dir, gloss, out.name, round(t1 - t0, 2))
    return out


def _update_index(out_dir: Path, gloss: str, video_name: str, duration: float):
    idx_path = out_dir / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {}
    idx[gloss] = {"video": video_name, "landmarks": f"{gloss}.json", "duration": duration}
    idx_path.write_text(json.dumps(dict(sorted(idx.items())), indent=2))


def has_clip(gloss: str, out_dir: Path = config.CLIPS_DIR) -> bool:
    return (out_dir / f"{gloss}.json").exists()

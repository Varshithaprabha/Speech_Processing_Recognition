"""MediaPipe Tasks (HolisticLandmarker) wrapper.

mediapipe >= 0.10.30 no longer ships `mp.solutions.holistic`, so AI4Bharat's
generate_keypoints.py does not run on current versions. This module does the same
job with the Tasks API and returns one raw vector per frame:

    pose  33 x (x, y, z, visibility)  -> 132
    left  21 x (x, y, z)              ->  63
    right 21 x (x, y, z)              ->  63
                                         ---
                                         258   (NaN where a part is not detected)

"left"/"right" are the SIGNER's hands (MediaPipe's convention), not image sides.

Coordinates: x and y are both in units of the ORIGINAL frame height (x = px / H,
y = py / H), so distances are not distorted by the aspect ratio (16:9 studio vs 4:3
webcam). To draw: pixel = (x * H, y * H). Divide x by W/H to get the usual [0, 1] x.

Signer crop: hands are small in wide shots, and MediaPipe loses them in ~35% of signing
frames. After the first frame we run the landmarker on a smoothed crop around the
signer's upper body (from the previous pose), which roughly halves hand-tracking loss.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

from . import config

RAW_DIM = 258
POSE_SL = slice(0, 132)
LH_SL = slice(132, 195)
RH_SL = slice(195, 258)


def ensure_model(path: Path = config.HOLISTIC_MODEL, url: str = config.HOLISTIC_URL) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {path.name} ...")
        urllib.request.urlretrieve(url, path)
    return path


def _as_list(lms):
    """Holistic returns a flat landmark list; other tasks return list-of-lists."""
    if not lms:
        return None
    if isinstance(lms[0], (list, tuple)):
        return lms[0] if lms[0] else None
    return lms


def _pts(lms, n: int, with_vis: bool, box) -> np.ndarray:
    """Landmarks of a crop -> array in original-frame height units. box = (x0, y0, cw, ch, H)."""
    k = 4 if with_vis else 3
    lms = _as_list(lms)
    if lms is None or len(lms) < n:
        return np.full(n * k, np.nan, np.float32)
    x0, y0, cw, ch, H = box
    out = np.empty((n, k), np.float32)
    for i in range(n):
        p = lms[i]
        out[i, 0] = (x0 + p.x * cw) / H
        out[i, 1] = (y0 + p.y * ch) / H
        out[i, 2] = p.z * cw / H
        if with_vis:
            v = getattr(p, "visibility", None)
            out[i, 3] = 1.0 if v is None else v
    return out.reshape(-1)


class Landmarker:
    """Frame-by-frame holistic landmarker (VIDEO running mode, so tracking is used)."""

    def __init__(self, model_path: Path | None = None, crop: bool = True, hand_fallback: bool = True):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        opts = vision.HolisticLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ensure_model(model_path or config.HOLISTIC_MODEL))),
            running_mode=vision.RunningMode.VIDEO,
            min_pose_detection_confidence=0.5,
            min_hand_landmarks_confidence=0.5,
        )
        self._lm = vision.HolisticLandmarker.create_from_options(opts)
        self._last_ts = -1
        self.last_result = None
        self.crop = crop
        self._box = None
        self._miss = 0
        self._hand = None
        if hand_fallback:
            hopts = vision.HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(ensure_model(config.HAND_MODEL, config.HAND_URL))),
                running_mode=vision.RunningMode.IMAGE, num_hands=2, min_hand_detection_confidence=0.3,
                min_hand_presence_confidence=0.3)
            self._hand = vision.HandLandmarker.create_from_options(hopts)
        self.fallback_hits = 0

    def _crop_box(self, W: int, H: int):
        """Square view (x0, y0, side) in original pixels; may extend past the frame (padded).
        Full frame (letterboxed) until a signer is found, then a smoothed upper-body box."""
        b = self._box
        if not self.crop or b is None:
            S = max(W, H)
            return (W - S) // 2, (H - S) // 2, S
        cx, cy, sw = b
        S = int(np.clip(sw * 4.2, 0.35 * H, max(W, H)))
        return int(cx - S / 2), int(cy - 0.42 * S), S

    @staticmethod
    def _square(frame, x0, y0, S, out):
        """Cut the square view (zero padding outside the frame) and resize to out x out."""
        H, W = frame.shape[:2]
        canvas = np.zeros((S, S, 3), np.uint8)
        fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(W, x0 + S), min(H, y0 + S)
        if fx1 > fx0 and fy1 > fy0:
            canvas[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0] = frame[fy0:fy1, fx0:fx1]
        return cv2.resize(canvas, (out, out), interpolation=cv2.INTER_AREA)

    def _update_box(self, raw: np.ndarray, H: int):
        pose = raw[POSE_SL].reshape(33, 4)
        ls, rs = pose[11, :2] * H, pose[12, :2] * H          # pixels
        if np.isnan(ls).any() or np.isnan(rs).any():
            self._miss += 1
            if self._miss > 5:                               # lost the signer: go back to full frame
                self._box = None
            return
        self._miss = 0
        new = np.array([(ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2, np.linalg.norm(ls - rs)])
        self._box = new if self._box is None else 0.8 * self._box + 0.2 * new

    def process(self, frame_bgr: np.ndarray, timestamp_ms: int) -> np.ndarray:
        H, W = frame_bgr.shape[:2]
        x0, y0, S = self._crop_box(W, H)
        img = self._square(frame_bgr, x0, y0, S, config.PROC_WIDTH)   # always the same size
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        ts = max(int(timestamp_ms), self._last_ts + 1)       # must be strictly increasing
        self._last_ts = ts
        r = self._lm.detect_for_video(self._mp.Image(image_format=self._mp.ImageFormat.SRGB,
                                                     data=np.ascontiguousarray(rgb)), ts)
        self.last_result = r
        box = (x0, y0, S, S, H)
        raw = np.concatenate([
            _pts(r.pose_landmarks, 33, True, box),
            _pts(r.left_hand_landmarks, 21, False, box),
            _pts(r.right_hand_landmarks, 21, False, box),
        ])
        if self._hand is not None:
            self._hand_fallback(frame_bgr, raw)
        self._update_box(raw, H)
        return raw

    def _hand_fallback(self, frame_bgr: np.ndarray, raw: np.ndarray):
        """Holistic often loses a hand near the face/body. If the pose shows where that wrist
        is, run the dedicated hand model on a close crop around it."""
        H = frame_bgr.shape[0]
        pose = raw[POSE_SL].reshape(33, 4)
        sw = np.linalg.norm(pose[11, :2] - pose[12, :2])
        if np.isnan(sw) or sw <= 0:
            return
        rest = (pose[11, 1] + pose[12, 1]) / 2 + 1.5 * sw          # well below the signing space
        for sl, (wi, ii) in ((LH_SL, (15, 19)), (RH_SL, (16, 20))):    # wrist, index knuckle (pose)
            if not np.isnan(raw[sl][0]) or pose[wi, 3] < 0.5 or pose[wi, 1] > rest:
                continue                                    # hand found, unseen, or resting: skip (saves ~40 ms)
            wrist, idx = pose[wi, :2], pose[ii, :2]
            centre = wrist + (idx - wrist) * 1.5 if not np.isnan(idx).any() else wrist
            S = int(sw * 1.6 * H)
            x0, y0 = int(centre[0] * H - S / 2), int(centre[1] * H - S / 2)
            img = cv2.cvtColor(self._square(frame_bgr, x0, y0, S, 256), cv2.COLOR_BGR2RGB)
            res = self._hand.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB,
                                                   data=np.ascontiguousarray(img)))
            best, best_d = None, 1e9
            for lms in res.hand_landmarks or []:
                pts = _pts([lms], 21, False, (x0, y0, S, S, H)).reshape(21, 3)
                d = np.linalg.norm(pts[0, :2] - wrist)
                if d < best_d:
                    best, best_d = pts, d
            if best is not None and best_d < sw * 0.6:      # must sit on this arm's wrist
                raw[sl] = best.reshape(-1)
                self.fallback_hits += 1

    def close(self):
        self._lm.close()
        if self._hand is not None:
            self._hand.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def iter_video_frames(path: Path, target_fps: float = 15.0) -> Iterator[tuple[np.ndarray, int]]:
    """Yield (frame, timestamp_ms), subsampled to ~target_fps."""
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, round(fps / target_fps))
    i = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i % step == 0:
                yield frame, int(i * 1000 / fps)
            i += 1
    finally:
        cap.release()


def video_to_keypoints(path: Path, landmarker: Landmarker | None = None, target_fps: float = 15.0) -> np.ndarray:
    own = landmarker is None
    lm = landmarker or Landmarker()
    try:
        rows = [lm.process(f, ts) for f, ts in iter_video_frames(path, target_fps)]
    finally:
        if own:
            lm.close()
    return np.stack(rows) if rows else np.zeros((0, RAW_DIM), np.float32)


# ---------------------------------------------------------------- drawing (demo / preview)
_HAND_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
               (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)]
_POSE_EDGES = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24)]


def draw(frame: np.ndarray, raw: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]

    def P(arr, i, k):
        x, y = arr[i * k], arr[i * k + 1]
        return None if np.isnan(x) else (int(x * h), int(y * h))

    pose = raw[POSE_SL]
    for a, b in _POSE_EDGES:
        pa, pb = P(pose, a, 4), P(pose, b, 4)
        if pa and pb:
            cv2.line(frame, pa, pb, (200, 200, 200), 2)
    for sl, col in ((LH_SL, (80, 200, 80)), (RH_SL, (80, 120, 255))):
        hand = raw[sl]
        for a, b in _HAND_EDGES:
            pa, pb = P(hand, a, 3), P(hand, b, 3)
            if pa and pb:
                cv2.line(frame, pa, pb, col, 2)
    return frame

"""Raw landmarks (T, 258) -> normalised model features (SEQ_LEN, FEAT_DIM).

Why this normalisation: INCLUDE is filmed in a studio (1080p, signer centred) while the
live demo uses a laptop webcam (different distance, framing, angle). Expressing every
point relative to the signer's shoulders (centre + width) removes most of that gap.

Per frame features:
  body  13 upper-body pose points, shoulder-normalised (x, y)        26
  hands 2 x 21 hand points, shoulder-normalised (x, y)               84  (where the hand is)
  shape 2 x 21 hand points relative to wrist / hand size (x, y)      84  (hand shape)
  flags left/right hand detected                                      2
  vel   frame-to-frame velocity of body+hands                       110
                                                                    ----
                                                                     306
"""
from __future__ import annotations

import numpy as np

from .config import SEQ_LEN
from .landmarks import LH_SL, POSE_SL, RH_SL

# nose, eyes(inner L/R), ears, mouth L/R, shoulders, elbows, wrists
BODY_IDX = [0, 2, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
FEAT_DIM = 26 + 84 + 84 + 2 + 110


def _split(raw: np.ndarray):
    T = raw.shape[0]
    pose = raw[:, POSE_SL].reshape(T, 33, 4)[:, :, :2]
    lh = raw[:, LH_SL].reshape(T, 21, 3)[:, :, :2]
    rh = raw[:, RH_SL].reshape(T, 21, 3)[:, :, :2]
    return pose, lh, rh


def hands_present(raw: np.ndarray) -> np.ndarray:
    """(T,) bool: at least one hand detected."""
    return ~np.isnan(raw[:, LH_SL][:, 0]) | ~np.isnan(raw[:, RH_SL][:, 0])


# A wrist more than REST_Y shoulder-widths below the shoulder line counts as "resting".
# Measured on INCLUDE: resting wrists sit at 1.5-1.9, signing wrists at -0.2 to 1.2.
REST_Y = 1.3


def raised(raw: np.ndarray, rest_y: float = REST_Y) -> np.ndarray:
    """(T,) bool: at least one wrist raised above the rest line (pose wrists, so it still
    works when the hand landmarks drop out)."""
    raw = np.atleast_2d(raw)
    pose = raw[:, POSE_SL].reshape(len(raw), 33, 4)
    centre_y = (pose[:, 11, 1] + pose[:, 12, 1]) / 2
    width = np.linalg.norm(pose[:, 11, :2] - pose[:, 12, :2], axis=1)
    out = np.zeros(len(raw), bool)
    for wi in (15, 16):
        wy = (pose[:, wi, 1] - centre_y) / width
        out |= (wy < rest_y) & (pose[:, wi, 3] >= 0.5)
    return np.nan_to_num(out).astype(bool)


def _ffill(a: np.ndarray, max_gap: int = 4) -> np.ndarray:
    """Forward-fill short gaps of NaN frames (hand tracking flicker)."""
    a = a.copy()
    T = a.shape[0]
    missing = np.isnan(a.reshape(T, -1)[:, 0])
    last = -10 ** 9
    for t in range(T):
        if not missing[t]:
            last = t
        elif t - last <= max_gap:
            a[t] = a[last]
    return a


def trim_to_activity(raw: np.ndarray, margin: int = 2) -> np.ndarray:
    """Drop leading/trailing frames where the signer's hands are at rest."""
    act = raised(raw)
    if act.sum() < 3:
        return raw
    idx = np.where(act)[0]
    return raw[max(0, idx[0] - margin): idx[-1] + 1 + margin]


def resample(x: np.ndarray, n: int = SEQ_LEN) -> np.ndarray:
    T = x.shape[0]
    if T == 0:
        return np.zeros((n,) + x.shape[1:], x.dtype)
    idx = np.linspace(0, T - 1, n).round().astype(int)
    return x[idx]


def frame_features(raw: np.ndarray) -> np.ndarray:
    """(T, 258) raw -> (T, FEAT_DIM) normalised features. NaNs become 0."""
    raw = raw.astype(np.float32)
    pose, lh, rh = _split(raw)
    lh, rh = _ffill(lh), _ffill(rh)
    T = raw.shape[0]

    ls, rs = pose[:, 11], pose[:, 12]
    centre = (ls + rs) / 2                                     # (T, 2)
    width = np.linalg.norm(ls - rs, axis=1)                    # (T,)
    # if pose is missing in a frame, fall back to the clip median
    ok = ~np.isnan(width) & (width > 1e-3)
    med_c = np.nanmedian(centre[ok], axis=0) if ok.any() else np.array([0.5, 0.5], np.float32)
    med_w = float(np.nanmedian(width[ok])) if ok.any() else 0.25
    centre[~ok] = med_c
    width[~ok] = med_w
    c, w = centre[:, None, :], width[:, None, None]

    body = (pose[:, BODY_IDX] - c) / w
    lhn, rhn = (lh - c) / w, (rh - c) / w

    def shape(h):
        wrist = h[:, :1]
        size = np.linalg.norm(h[:, 9] - h[:, 0], axis=1)[:, None, None]   # wrist -> middle MCP
        size = np.where(np.isnan(size) | (size < 1e-4), 1.0, size)
        return (h - wrist) / size

    flags = np.stack([~np.isnan(lh[:, 0, 0]), ~np.isnan(rh[:, 0, 0])], 1).astype(np.float32)
    pos = np.concatenate([body.reshape(T, -1), lhn.reshape(T, -1), rhn.reshape(T, -1)], 1)
    pos = np.nan_to_num(pos)
    vel = np.diff(pos, axis=0, prepend=pos[:1])
    feats = np.concatenate([pos[:, :26 + 84], np.nan_to_num(shape(lh)).reshape(T, -1),
                            np.nan_to_num(shape(rh)).reshape(T, -1), flags, vel], 1)
    # pos[:, :110] is body+hands; keep the column order documented above
    return np.clip(feats, -10, 10).astype(np.float32)


def clip_features(raw: np.ndarray, trim: bool = True) -> np.ndarray:
    """Whole clip -> (SEQ_LEN, FEAT_DIM) ready for the classifier."""
    if trim:
        raw = trim_to_activity(raw)
    return resample(frame_features(raw))


# ------------------------------------------------------------------ augmentation (raw space)
def mirror(raw: np.ndarray) -> np.ndarray:
    """Left-right mirror: flip x and swap the signer's hands / body sides."""
    out = raw.copy()
    T = raw.shape[0]
    pose = out[:, POSE_SL].reshape(T, 33, 4)
    cx = np.nanmedian((pose[:, 11, 0] + pose[:, 12, 0]) / 2)      # reflect around the body midline
    if np.isnan(cx):
        cx = 0.5
    pose[:, :, 0] = 2 * cx - pose[:, :, 0]
    swap = [(1, 4), (2, 5), (3, 6), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16), (17, 18), (19, 20),
            (21, 22), (23, 24), (25, 26), (27, 28), (29, 30), (31, 32)]
    for a, b in swap:
        pose[:, [a, b]] = pose[:, [b, a]]
    lh = raw[:, LH_SL].reshape(T, 21, 3).copy()
    rh = raw[:, RH_SL].reshape(T, 21, 3).copy()
    lh[:, :, 0], rh[:, :, 0] = 2 * cx - lh[:, :, 0], 2 * cx - rh[:, :, 0]
    out[:, POSE_SL] = pose.reshape(T, -1)
    out[:, LH_SL] = rh.reshape(T, -1)
    out[:, RH_SL] = lh.reshape(T, -1)
    return out


def augment(raw: np.ndarray, rng: np.random.Generator, p_mirror: float = 0.0) -> np.ndarray:
    """Random affine (scale/rotate/shift), temporal crop/speed and frame drop, in raw space."""
    T = raw.shape[0]
    out = raw.copy()
    if p_mirror and rng.random() < p_mirror:
        out = mirror(out)
    # temporal: random crop of 80-100% and speed change
    if T > 8:
        keep = int(T * rng.uniform(0.8, 1.0))
        s = rng.integers(0, T - keep + 1)
        out = out[s:s + keep]
        n = max(4, int(len(out) * rng.uniform(0.8, 1.25)))
        out = out[np.linspace(0, len(out) - 1, n).round().astype(int)]
    # spatial affine on x, y (around image centre)
    ang = np.deg2rad(rng.uniform(-12, 12))
    sc = rng.uniform(0.85, 1.15)
    sx = sc * rng.uniform(0.92, 1.08)
    R = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]]) * [[sx], [sc]]
    shift = rng.uniform(-0.08, 0.08, 2)
    Tn = out.shape[0]
    for sl, k in ((POSE_SL, 4), (LH_SL, 3), (RH_SL, 3)):
        part = out[:, sl].reshape(Tn, -1, k)
        xy = part[:, :, :2] - 0.5
        part[:, :, :2] = xy @ R.T + 0.5 + shift
        out[:, sl] = part.reshape(Tn, -1)
    # hand dropout: simulate tracking loss on a few frames
    if rng.random() < 0.3:
        drop = rng.random(Tn) < 0.1
        sl = LH_SL if rng.random() < 0.5 else RH_SL
        out[drop, sl] = np.nan
    # jitter
    out += rng.normal(0, 0.003, out.shape).astype(np.float32)
    return out.astype(np.float32)

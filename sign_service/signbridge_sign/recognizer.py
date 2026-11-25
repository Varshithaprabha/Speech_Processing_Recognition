"""Continuous signing -> gloss sequence.

Segmentation rules (simple and robust enough for a live demo):
  * A hand is "active" when its wrist (body pose, always tracked) is raised above the
    rest line (less than REST_Y shoulder-widths below the shoulders).
  * A sign STARTS after a few active frames.
  * A sign ENDS when the hands drop for END_GAP seconds, or the segment exceeds MAX_SIGN
    seconds. (Optional: Settings(hold=0.6) also ends a sign when the hands stay still,
    but that cuts held signs such as ME, so it is off by default.)
  * The segment is classified; words below MIN_CONF are discarded.
  * A SENTENCE ends after SENTENCE_GAP seconds with no signing (or on flush()).

Tip for the demo: drop your hands briefly (below the chest) between signs, and keep
them down for ~1.5 s to finish the sentence.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .features import REST_Y, raised
from .landmarks import POSE_SL
from .messages import make_message
from .model import Predictor


@dataclass
class Settings:
    rest_y: float = REST_Y       # wrist this many shoulder-widths below shoulders = resting
    start_frames: int = 3
    end_gap: float = 0.35        # s of no active hands -> sign ends
    hold: float | None = None    # s of still hands -> sign ends (None = off; held signs like ME get cut)
    hold_speed: float = 0.04     # shoulder-widths/frame considered "still"
    min_sign: float = 0.35       # s, shorter segments are ignored
    max_sign: float = 3.5        # s
    min_conf: float = 0.45
    sentence_gap: float = 1.5    # s idle -> sentence finished
    dedupe: bool = True          # drop immediate repeats of the same word


@dataclass
class _State:
    frames: list = field(default_factory=list)
    times: list = field(default_factory=list)
    signing: bool = False
    active_run: int = 0
    last_active_t: float = 0.0
    still_since: float | None = None
    words: list = field(default_factory=list)     # [(gloss, conf)]
    last_sign_end: float = 0.0


def _hand_points(raw: np.ndarray) -> np.ndarray | None:
    """Shoulder-normalised pose wrist + index knuckle points (always tracked) for motion."""
    pose = raw[POSE_SL].reshape(33, 4)
    ls, rs = pose[11, :2], pose[12, :2]
    width = np.linalg.norm(ls - rs)
    if np.isnan(width) or width < 1e-3:
        return None
    return (pose[[15, 16, 19, 20], :2] - (ls + rs) / 2) / width


class ContinuousRecognizer:
    def __init__(self, predictor: Predictor, settings: Settings | None = None):
        self.p = predictor
        self.s = settings or Settings()
        self.st = _State()
        self._prev_pts = None
        self.status = "idle"                 # idle | signing
        self.last_word: tuple[str, float] | None = None
        self.segments = 0                    # number of closed sign segments (for logging)
        self.last_segment: dict | None = None

    def reset(self):
        self.st = _State()
        self._prev_pts = None
        self.status = "idle"

    # ------------------------------------------------------------------ main entry
    def feed(self, raw: np.ndarray, t: float) -> list[dict]:
        """Feed one frame of raw landmarks at time t (seconds). Returns messages to send."""
        s, st, out = self.s, self.st, []
        active = bool(raised(raw[None], s.rest_y)[0])
        pts = _hand_points(raw)

        speed = None
        if pts is not None and self._prev_pts is not None and pts.shape == self._prev_pts.shape:
            speed = float(np.abs(pts - self._prev_pts).mean())
        self._prev_pts = pts

        if active:
            st.active_run += 1
            st.last_active_t = t
        else:
            st.active_run = 0

        if not st.signing:
            st.frames.append(raw)               # keep a short pre-roll
            st.times.append(t)
            st.frames, st.times = st.frames[-4:], st.times[-4:]
            if st.active_run >= s.start_frames:
                st.signing, st.still_since = True, None
                self.status = "signing"
            elif st.words and t - max(st.last_active_t, st.last_sign_end) > s.sentence_gap:
                out.append(self._finish_sentence())
            return out

        # currently signing
        st.frames.append(raw)
        st.times.append(t)
        dur = t - st.times[0]
        if speed is not None and speed < s.hold_speed:
            st.still_since = st.still_since or t
        else:
            st.still_since = None

        ended = (t - st.last_active_t > s.end_gap
                 or (s.hold is not None and st.still_since is not None and t - st.still_since > s.hold and dur > s.min_sign + s.hold)
                 or dur > s.max_sign)
        if ended:
            msg = self._close_sign(t)
            if msg:
                out.append(msg)
        return out

    def flush(self) -> list[dict]:
        """Force-finish the current sign and sentence (e.g. user pressed 'send')."""
        out = []
        if self.st.signing:
            m = self._close_sign(self.st.times[-1] if self.st.times else 0.0)
            if m:
                out.append(m)
        if self.st.words:
            out.append(self._finish_sentence())
        return out

    # ------------------------------------------------------------------ helpers
    def _close_sign(self, t: float) -> dict | None:
        st, s = self.st, self.s
        frames, times = st.frames, st.times
        st.frames, st.times, st.signing, st.still_since = [], [], False, None
        st.last_sign_end = t
        self.status = "idle"
        self.segments += 1
        dur = (times[-1] - times[0]) if times else 0.0
        seg = {"start": round(times[0], 2) if times else None, "dur": round(dur, 2)}
        self.last_segment = seg
        if not times or dur < s.min_sign:
            seg["result"] = "too_short"
            return None
        raw = np.stack(frames)
        top = self.p.predict_raw(raw, top_k=3)
        gloss, conf = top[0]
        seg["top"] = [[g, round(c, 3)] for g, c in top]
        self.last_word = (gloss, conf)
        if conf < s.min_conf:
            seg["result"] = "low_conf"
            return None
        if s.dedupe and st.words and st.words[-1][0] == gloss:
            seg["result"] = "repeat"
            return None
        seg["result"] = "word"
        st.words.append((gloss, conf))
        return make_message("gloss_partial", [w for w, _ in st.words], conf,
                            words=[{"gloss": g, "confidence": round(c, 3)} for g, c in st.words],
                            alternatives=[{"gloss": g, "confidence": round(c, 3)} for g, c in top[1:]])

    def _finish_sentence(self) -> dict:
        words = self.st.words
        self.st.words = []
        conf = float(np.mean([c for _, c in words]))
        return make_message("gloss", [w for w, _ in words], conf,
                            words=[{"gloss": g, "confidence": round(c, 3)} for g, c in words])

"""Shared paths and constants for Part A (sign_service)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # .../sign_service
DATA = ROOT / "data"
META_DIR = DATA / "meta"
VIDEO_DIR = DATA / "include_videos"                   # raw INCLUDE videos (only chosen words)
WEBCAM_VIDEO_DIR = DATA / "webcam_videos"              # clips recorded with record_signs.py
KP_DIR = DATA / "keypoints"                            # extracted landmark sequences (.npy)
MODELS = ROOT / "models"
MP_MODELS = MODELS / "mediapipe"
CLASSIFIER_PATH = MODELS / "sign_classifier.pt"
REPORTS = ROOT / "reports"
CLIPS_DIR = ROOT / "clips"                             # per-gloss clips for Part C's avatar

VOCAB_PATH = ROOT / "vocab.json"

ZENODO_RECORD = "4010759"
HF_DATASET = "ai4bharat/INCLUDE"

HOLISTIC_URL = ("https://storage.googleapis.com/mediapipe-models/holistic_landmarker/"
                "holistic_landmarker/float16/latest/holistic_landmarker.task")
HOLISTIC_MODEL = MP_MODELS / "holistic_landmarker.task"
HAND_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
            "hand_landmarker/float16/latest/hand_landmarker.task")
HAND_MODEL = MP_MODELS / "hand_landmarker.task"

# Frames fed to the classifier per sign (every clip is resampled to this length).
SEQ_LEN = 32
# Side of the square signer crop fed to MediaPipe (pixels).
PROC_WIDTH = 640


def load_vocab() -> list[dict]:
    return json.loads(VOCAB_PATH.read_text(encoding="utf-8"))["words"]


def glosses() -> list[str]:
    """Words the classifier recognises (vocab entries with "recognize": false are skipped)."""
    return [w["gloss"] for w in load_vocab() if w.get("recognize", True)]


def all_glosses() -> list[str]:
    """Every word with an avatar clip, including ones that are not recognised."""
    return [w["gloss"] for w in load_vocab()]

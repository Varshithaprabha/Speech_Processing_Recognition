"""Small BiGRU + attention-pooling classifier over landmark sequences."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from torch import nn

from . import config
from .features import FEAT_DIM, clip_features


class SignClassifier(nn.Module):
    def __init__(self, n_classes: int, feat_dim: int = FEAT_DIM, hidden: int = 192, dropout: float = 0.35):
        super().__init__()
        self.inp = nn.Sequential(nn.Linear(feat_dim, 256), nn.LayerNorm(256), nn.GELU(), nn.Dropout(dropout))
        self.gru = nn.GRU(256, hidden, num_layers=2, batch_first=True, bidirectional=True, dropout=dropout)
        self.att = nn.Linear(2 * hidden, 1)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(2 * hidden, n_classes))

    def forward(self, x):                       # x: (B, T, F)
        h, _ = self.gru(self.inp(x))
        a = torch.softmax(self.att(h).squeeze(-1), dim=1)
        pooled = (h * a.unsqueeze(-1)).sum(1)
        return self.head(pooled)


def save(model: SignClassifier, classes: list[str], path: Path = config.CLASSIFIER_PATH, **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state": model.state_dict(), "classes": classes, "seq_len": config.SEQ_LEN,
                "feat_dim": FEAT_DIM, **extra}, path)


class Predictor:
    """Loads the trained classifier and predicts a gloss for one clip of raw landmarks."""

    def __init__(self, path: Path = config.CLASSIFIER_PATH):
        ck = torch.load(path, map_location="cpu", weights_only=False)
        self.classes: list[str] = ck["classes"]
        self.model = SignClassifier(len(self.classes), ck["feat_dim"])
        self.model.load_state_dict(ck["state"])
        self.model.eval()
        self.meta = {k: v for k, v in ck.items() if k != "state"}

    @torch.no_grad()
    def predict_raw(self, raw: np.ndarray, top_k: int = 3) -> list[tuple[str, float]]:
        x = torch.from_numpy(clip_features(raw)).unsqueeze(0)
        p = torch.softmax(self.model(x), -1)[0].numpy()
        order = np.argsort(-p)[:top_k]
        return [(self.classes[i], float(p[i])) for i in order]

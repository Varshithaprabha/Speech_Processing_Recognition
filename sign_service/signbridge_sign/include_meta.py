"""INCLUDE metadata from the Hugging Face dataset card (ai4bharat/INCLUDE).

Note: the HF parquet files merge the INCLUDE and INCLUDE-50 split lists, so ~25% of
videos appear twice, sometimes once as train and once as test. Using those splits would
leak test videos into training. We therefore de-duplicate by video path and assign our
own deterministic split per word (~70% train / 15% val / 15% test).
"""
from __future__ import annotations

import zlib

import pandas as pd

from . import config


def _raw() -> pd.DataFrame:
    cache = config.META_DIR / "include_meta_raw.csv"
    if cache.exists():
        return pd.read_csv(cache)
    from huggingface_hub import hf_hub_download

    frames = []
    for split in ("train", "val", "test"):
        p = hf_hub_download(config.HF_DATASET, f"data/{split}-00000-of-00001.parquet",
                            repo_type="dataset", local_dir=config.META_DIR)
        frames.append(pd.read_parquet(p).assign(hf_split=split))
    df = pd.concat(frames, ignore_index=True)
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache, index=False)
    return df


def _split_for(group: pd.DataFrame) -> pd.Series:
    # order by a stable hash so the split does not depend on file numbering
    order = group.video_path.map(lambda p: zlib.crc32(p.encode())).rank(method="first").astype(int) - 1
    n = len(group)
    n_test = max(1, round(n * 0.15))
    n_val = max(1, round(n * 0.15))
    return order.map(lambda i: "test" if i < n_test else ("val" if i < n_test + n_val else "train"))


def load_metadata() -> pd.DataFrame:
    """Columns: parent_label, label, video_path, include_50, split (deduplicated)."""
    df = _raw()
    df = (df.groupby("video_path", as_index=False)
            .agg(parent_label=("parent_label", "first"), label=("label", "first"),
                 include_50=("include_50", "max")))
    df["split"] = df.groupby("label", group_keys=False)[["video_path"]].apply(_split_for)
    return df

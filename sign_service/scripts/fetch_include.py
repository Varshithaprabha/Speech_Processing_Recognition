"""Download ONLY the INCLUDE videos for the words in vocab.json.

INCLUDE is ~55 GB on Zenodo, split into ~1-1.8 GB zip parts per category. Instead of
downloading whole parts, this script reads each zip's central directory with HTTP range
requests and pulls out just the member files we need (~10-15 MB per video).

    python scripts/fetch_include.py --list            # show which parts/videos are needed + size
    python scripts/fetch_include.py                   # download all splits for every vocab word
    python scripts/fetch_include.py --max-per-word 12 # cap videos per word (faster)
    python scripts/fetch_include.py --keep-videos     # keep raw videos (needs ~5 GB)

Storage: by default each video is downloaded, its landmarks are extracted to
data/keypoints/include/<GLOSS>/<split>__<video>.npy (~40 KB), one short 480p clip per word
is saved to clips/ for the avatar (~200 KB), and the raw video (~14 MB) is deleted.
Peak disk use is a few videos at a time; the final dataset is ~15 MB + ~5 MB of clips.
Safe to stop and re-run: finished videos are skipped.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from signbridge_sign import config  # noqa: E402
from signbridge_sign.include_meta import load_metadata  # noqa: E402

API = f"https://zenodo.org/api/records/{config.ZENODO_RECORD}"


class HttpRangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests (enough for zipfile)."""

    def __init__(self, url: str, size: int, session: requests.Session, block: int = 1 << 20):
        self.url, self.size, self.s, self.block = url, size, session, block
        self.pos = 0
        self._cache: dict[int, bytes] = {}

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos

    def _get(self, start: int, end: int) -> bytes:
        for attempt in range(5):
            try:
                r = self.s.get(self.url, headers={"Range": f"bytes={start}-{end}"}, timeout=60)
                if r.status_code == 206:
                    return r.content
                raise IOError(f"HTTP {r.status_code}")
            except Exception as e:  # noqa: BLE001
                if attempt == 4:
                    raise
                print(f"   retry ({e})")
                time.sleep(2 * (attempt + 1))
        raise AssertionError

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = min(n, self.size - self.pos)
        if n <= 0:
            return b""
        if n > self.block:                         # large read (a video): fetch directly
            data = self._get(self.pos, self.pos + n - 1)
        else:                                      # small read (headers): block cache
            b0 = self.pos // self.block
            b1 = (self.pos + n - 1) // self.block
            parts = []
            for b in range(b0, b1 + 1):
                if b not in self._cache:
                    s = b * self.block
                    self._cache[b] = self._get(s, min(s + self.block, self.size) - 1)
                parts.append(self._cache[b])
            buf = b"".join(parts)
            o = self.pos - b0 * self.block
            data = buf[o:o + n]
        self.pos += len(data)
        return data

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)


def norm(p: str) -> str:
    """Normalise a path for matching zip members to metadata video_path."""
    return p.replace("\\", "/").strip("/").lower()


def zip_index(files: list[dict], session, categories: set[str], cache_path: Path) -> dict:
    """{part_name: [member names]} for the given categories (cached to disk)."""
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    for f in files:
        key = f["key"]
        if not key.endswith(".zip") or key.rsplit("_", 1)[0] not in categories or key in cache:
            continue
        print(f"Reading index of {key} ...")
        rf = HttpRangeFile(f["links"]["self"], f["size"], session)
        with zipfile.ZipFile(io.BufferedReader(rf, buffer_size=1 << 16)) as z:
            cache[key] = [i.filename for i in z.infolist() if not i.is_dir()]
        cache_path.write_text(json.dumps(cache))
    return cache


def process_video(video: str, kp_out: str, gloss: str, want_clip: bool, vp: str):
    """Worker process: landmarks -> .npy, optional avatar clip, then delete the video."""
    import os
    os.environ.setdefault("GLOG_minloglevel", "2")
    import numpy as np
    from signbridge_sign.clips import make_clip
    from signbridge_sign.landmarks import video_to_keypoints

    kp = video_to_keypoints(Path(video))
    Path(kp_out).parent.mkdir(parents=True, exist_ok=True)
    np.save(kp_out, kp.astype(np.float32))
    hands = float((~np.isnan(kp[:, 132]) | ~np.isnan(kp[:, 195])).mean()) if len(kp) else 0.0
    clip = None
    if want_clip and hands >= 0.4:
        out = make_clip(Path(video), kp, gloss, update_index=False)
        clip = (out.name, round(len(kp) / 15.0, 2))
    Path(video).unlink(missing_ok=True)
    return vp, f"{len(kp)} frames, hands {hands:.0%}", clip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="only show what would be downloaded")
    ap.add_argument("--max-per-word", type=int, default=0, help="cap videos per word (0 = all)")
    ap.add_argument("--splits", default="train,val,test")
    ap.add_argument("--threads", type=int, default=4, help="parallel downloads")
    ap.add_argument("--workers", type=int, default=4, help="parallel landmark-extraction processes")
    ap.add_argument("--keep-videos", action="store_true",
                    help="keep the raw videos (~14 MB each) instead of deleting them after extraction")
    args = ap.parse_args()

    vocab = config.load_vocab()
    meta = load_metadata()
    labels = {w["include_label"]: w for w in vocab}
    meta = meta[meta.label.isin(labels) & meta.split.isin(args.splits.split(","))]
    if args.max_per_word:
        meta = (meta.sort_values("split", key=lambda s: s.map({"train": 0, "val": 1, "test": 2}))
                .groupby("label", group_keys=False).apply(lambda g: g.head(args.max_per_word)))
    wanted = {norm(p): p for p in meta.video_path}
    cats = {w["category"] for w in vocab}
    print(f"{len(wanted)} videos for {len(labels)} words in categories: {', '.join(sorted(cats))}")

    s = requests.Session()
    files = requests.get(API, timeout=60).json()["files"]
    by_key = {f["key"]: f for f in files}
    index = zip_index(files, s, cats, config.META_DIR / "zip_index.json")

    # match members -> (part, member) by path suffix "<category>/<label>/<file>"
    plan = defaultdict(list)
    for part, members in index.items():
        for m in members:
            nm = norm(m)
            for wn in list(wanted):
                if nm.endswith(wn):
                    plan[part].append((m, wanted.pop(wn)))
                    break
    if wanted:
        print(f"WARNING: {len(wanted)} videos not found in any zip, e.g. {list(wanted)[:3]}")

    total = 0
    for part, items in sorted(plan.items()):
        print(f"  {part}: {len(items)} videos")
        total += len(items)
    print(f"Total {total} videos.")
    if args.list:
        return

    rows = {r.video_path: r for r in meta.itertuples()}
    gloss_of = {w["include_label"]: w["gloss"] for w in vocab}

    def kp_path(vp: str) -> Path:
        r = rows[vp]
        return config.KP_DIR / "include" / gloss_of[r.label] / f"{r.split}__{Path(vp).stem}.npy"

    def done_already(vp: str) -> bool:
        return kp_path(vp).exists() if not args.keep_videos else (config.VIDEO_DIR / vp).exists()

    jobs = [(part, m, vp) for part, items in sorted(plan.items()) for m, vp in items if not done_already(vp)]
    print(f"{len(jobs)} still to do, {args.threads} parallel downloads"
          + ("" if args.keep_videos else f", {args.workers} landmark workers (videos deleted after extraction)"))
    if not jobs:
        print("Nothing to do.")
        return

    local = threading.local()

    def open_zip(part: str) -> zipfile.ZipFile:
        """One ZipFile per (thread, part); reading the central directory is ~1 MB."""
        zs = local.__dict__.setdefault("zips", {})
        if part not in zs:
            f = by_key[part]
            sess = local.__dict__.setdefault("session", requests.Session())
            zs[part] = zipfile.ZipFile(io.BufferedReader(
                HttpRangeFile(f["links"]["self"], f["size"], sess), buffer_size=1 << 16))
        return zs[part]

    def fetch(job):
        part, m, vp = job
        out = config.VIDEO_DIR / vp
        if out.exists():                      # downloaded by an earlier run, just process it
            return vp, out.stat().st_size
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + f".{threading.get_ident()}.part")
        with open_zip(part).open(m) as src, open(tmp, "wb") as fh:
            while chunk := src.read(1 << 22):
                fh.write(chunk)
        tmp.replace(out)
        return vp, out.stat().st_size

    from signbridge_sign.clips import _update_index, has_clip
    clip_busy: set[str] = set()
    pool = None if args.keep_videos else ProcessPoolExecutor(args.workers)
    pending = []
    done = 0

    def on_processed(fut):
        nonlocal done
        done += 1
        try:
            vp, msg, clip = fut.result()
        except Exception as e:  # noqa: BLE001
            print(f"  [{done}/{len(jobs)}] FAILED extraction: {e}", flush=True)
            return
        g = gloss_of[rows[vp].label]
        clip_busy.discard(g)
        if clip:
            _update_index(config.CLIPS_DIR, g, clip[0], clip[1])
            msg += f", saved clip {clip[0]}"
        print(f"  [{done}/{len(jobs)}] {vp}: {msg}", flush=True)

    with ThreadPoolExecutor(args.threads) as ex:
        futs = [ex.submit(fetch, j) for j in jobs]
        for fut in as_completed(futs):
            try:
                vp, size = fut.result()
            except Exception as e:  # noqa: BLE001
                done += 1
                print(f"  [{done}/{len(jobs)}] FAILED download: {e} (re-run to retry)", flush=True)
                continue
            if pool is None:
                done += 1
                print(f"  [{done}/{len(jobs)}] {vp} ({size / 1e6:.1f} MB)", flush=True)
                continue
            g = gloss_of[rows[vp].label]
            want_clip = not has_clip(g) and g not in clip_busy
            if want_clip:
                clip_busy.add(g)
            pf = pool.submit(process_video, str(config.VIDEO_DIR / vp), str(kp_path(vp)), g, want_clip, vp)
            pending.append(pf)
            # report finished extractions as we go
            for p in [p for p in pending if p.done()]:
                pending.remove(p)
                on_processed(p)
    if pool:
        for p in as_completed(pending):
            on_processed(p)
        pool.shutdown()
        missing = [w["gloss"] for w in vocab if not has_clip(w["gloss"])]
        if missing:
            print(f"No avatar clip yet for {missing} (all their videos had poor hand tracking?)")
        kb = sum(f.stat().st_size for f in config.KP_DIR.rglob("*.npy")) / 1e6
        print(f"Keypoints on disk: {kb:.1f} MB; clips in {config.CLIPS_DIR}")
    print("Done. Next: python scripts/train.py" if not args.keep_videos
          else "Done. Next: python scripts/extract_keypoints.py")


if __name__ == "__main__":
    main()

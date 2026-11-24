"""Train the sign classifier on INCLUDE keypoints (+ webcam clips if recorded).

    python scripts/train.py                         # train on everything available
    python scripts/train.py --only HELLO,ME,DOCTOR  # restrict vocabulary (e.g. best 10)
    python scripts/train.py --epochs 120

Splits
    INCLUDE: our deterministic train/val/test split (see include_meta.py)
    webcam:  per signer & word, every 4th clip is test, the rest train
             (--holdout-signer NAME instead tests on one person never seen in training)

Writes models/sign_classifier.pt and reports/ (accuracy, per-word accuracy,
confusion matrix PNG). Report these numbers in the project report.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from signbridge_sign import config  # noqa: E402
from signbridge_sign.features import augment, clip_features  # noqa: E402
from signbridge_sign.model import SignClassifier, save  # noqa: E402


def load_samples(classes: list[str], holdout_signer: str | None):
    """Returns list of (raw, class_idx, split, source)."""
    out = []
    for ci, g in enumerate(classes):
        for f in sorted((config.KP_DIR / "include" / g).glob("*.npy")):
            split = f.stem.split("__")[0]
            out.append((np.load(f), ci, split, "include"))
        for signer_dir in sorted((config.KP_DIR / "webcam").glob("*")):
            files = sorted((signer_dir / g).glob("*.npy"))
            for i, f in enumerate(files):
                if holdout_signer:
                    split = "test" if signer_dir.name == holdout_signer else ("val" if i % 5 == 4 else "train")
                else:
                    split = "test" if i % 4 == 3 else "train"
                out.append((np.load(f), ci, split, "webcam"))
    return [s for s in out if len(s[0]) >= 4]


def batches(samples, bs, rng, train: bool, p_mirror: float):
    idx = rng.permutation(len(samples)) if train else np.arange(len(samples))
    for i in range(0, len(idx), bs):
        chunk = [samples[j] for j in idx[i:i + bs]]
        xs = [clip_features(augment(s[0], rng, p_mirror) if train else s[0]) for s in chunk]
        yield torch.from_numpy(np.stack(xs)), torch.tensor([s[1] for s in chunk])


@torch.no_grad()
def predict(model, samples):
    model.eval()
    if not samples:
        return np.zeros((0,), int), np.zeros((0, 1))
    x = torch.from_numpy(np.stack([clip_features(s[0]) for s in samples]))
    p = torch.softmax(model(x), -1).numpy()
    return p.argmax(1), p


def evaluate(model, samples, classes, name, report_dir: Path):
    if not samples:
        return None
    y = np.array([s[1] for s in samples])
    pred, prob = predict(model, samples)
    acc = float((pred == y).mean())
    top3 = float(np.mean([y[i] in np.argsort(-prob[i])[:3] for i in range(len(y))]))
    cm = np.zeros((len(classes), len(classes)), int)
    for a, b in zip(y, pred):
        cm[a, b] += 1
    per = {classes[i]: (float(cm[i, i] / cm[i].sum()) if cm[i].sum() else None) for i in range(len(classes))}
    _plot_cm(cm, classes, f"{name}: acc {acc:.1%} (n={len(y)})", report_dir / f"confusion_{name}.png")
    print(f"  {name:14s} acc {acc:6.1%}  top-3 {top3:6.1%}  (n={len(y)})")
    return {"accuracy": acc, "top3": top3, "n": len(y), "per_word": per, "confusion": cm.tolist()}


def _plot_cm(cm, classes, title, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n = len(classes)
    fig, ax = plt.subplots(figsize=(0.45 * n + 3, 0.45 * n + 2.5))
    norm = cm / np.maximum(cm.sum(1, keepdims=True), 1)
    ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(n), classes, rotation=90, fontsize=8)
    ax.set_yticks(range(n), classes, fontsize=8)
    for i in range(n):
        for j in range(n):
            if cm[i, j]:
                ax.text(j, i, cm[i, j], ha="center", va="center", fontsize=7,
                        color="white" if norm[i, j] > 0.5 else "black")
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated glosses to keep")
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--webcam-weight", type=float, default=3.0, help="oversample webcam clips")
    ap.add_argument("--mirror", type=float, default=0.15, help="prob. of left/right mirror augmentation")
    ap.add_argument("--holdout-signer", default=None)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    classes = config.glosses()
    if args.only:
        keep = [g.strip().upper() for g in args.only.split(",") if g.strip()]
        classes = [g for g in classes if g in keep]
    samples = load_samples(classes, args.holdout_signer)
    if not samples:
        sys.exit("No keypoints found. Run fetch_include.py and extract_keypoints.py first.")

    train = [s for s in samples if s[2] == "train"]
    val = [s for s in samples if s[2] == "val"]
    test = [s for s in samples if s[2] == "test"]
    n_web = sum(s[3] == "webcam" for s in train)
    if n_web and args.webcam_weight > 1:      # webcam clips matter most for the live demo
        train = train + [s for s in train if s[3] == "webcam"] * (int(args.webcam_weight) - 1)
    counts = np.bincount([s[1] for s in samples], minlength=len(classes))
    missing = [c for c, n in zip(classes, counts) if n == 0]
    if missing:
        print(f"WARNING: no data for {missing}; they will never be predicted.")
    print(f"{len(classes)} classes | train {len(train)} (webcam {n_web}) | val {len(val)} | test {len(test)}")

    model = SignClassifier(len(classes))
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, epochs=args.epochs,
                                                steps_per_epoch=max(1, -(-len(train) // args.bs)))
    lossf = nn.CrossEntropyLoss(label_smoothing=0.1)
    best, best_state, t0 = -1.0, None, time.time()
    sel = val if val else test
    for ep in range(1, args.epochs + 1):
        model.train()
        tot = 0.0
        for x, y in batches(train, args.bs, rng, True, args.mirror):
            opt.zero_grad()
            loss = lossf(model(x), y)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += loss.item() * len(y)
        if ep % 5 == 0 or ep == args.epochs:
            y = np.array([s[1] for s in sel])
            acc = float((predict(model, sel)[0] == y).mean()) if len(sel) else 0.0
            if acc >= best:
                best, best_state = acc, {k: v.clone() for k, v in model.state_dict().items()}
            print(f"epoch {ep:3d}  loss {tot / len(train):.3f}  val acc {acc:.1%}  ({time.time() - t0:.0f}s)")

    model.load_state_dict(best_state)
    report_dir = config.REPORTS
    report_dir.mkdir(parents=True, exist_ok=True)
    print("\nResults (best checkpoint by validation accuracy):")
    res = {"classes": classes, "epochs": args.epochs, "train_size": len(train)}
    for name, subset in [("val", val), ("test_all", test),
                         ("test_include", [s for s in test if s[3] == "include"]),
                         ("test_webcam", [s for s in test if s[3] == "webcam"])]:
        r = evaluate(model, subset, classes, name, report_dir)
        if r:
            res[name] = r
    key = "test_webcam" if "test_webcam" in res else "test_all"
    if key in res:
        print(f"\nPer-word accuracy on {key} (worst first) - drop the weakest if the demo is shaky:")
        for g, a in sorted(res[key]["per_word"].items(), key=lambda kv: (kv[1] is None, kv[1] or 0)):
            print(f"  {g:12s} {'-' if a is None else f'{a:.0%}'}")
    (report_dir / "metrics.json").write_text(json.dumps(res, indent=2))
    save(model, classes, metrics={k: v["accuracy"] for k, v in res.items() if isinstance(v, dict)})
    print(f"\nSaved {config.CLASSIFIER_PATH} and reports in {report_dir}")


if __name__ == "__main__":
    main()

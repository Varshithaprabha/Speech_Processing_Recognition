# sign_service: Part A (Vision & Sign Recognition)

Turns a webcam feed of someone signing in Indian Sign Language (ISL) into gloss messages in the
shared format (section 6). The rest of SignBridge (Part B, Part C) only needs to connect to
`ws://<host>:8001/ws`.

```
camera ─► MediaPipe Holistic (pose + both hands) ─► shoulder-normalised features
       ─► segmenter (hands up/down, pauses) ─► BiGRU classifier ─► {"type":"gloss","content":"ME SICK TODAY",...}
```

## Vocabulary (17 recognised words + 1 avatar-only, in `vocab.json`)

HELLO, HOW-ARE-YOU, THANK-YOU, ME, DOCTOR, HOSPITAL, SICK, HOT, GOOD, BAD, MEDICINE,
TODAY, TOMORROW, YESTERDAY, MOTHER, FATHER, FAMILY

**YOU** is not recognised: it was confused with ME in every test (both are pointing signs; the camera can't
reliably tell "towards the camera" from "towards yourself"). Its clip is kept in `clips/` so the avatar can
still sign YOU to the Deaf user.

These were chosen for the hospital demo. INCLUDE-50 has no medical words, so we use the full INCLUDE
set (263 words). Example sentences: `HELLO` · `ME SICK YESTERDAY TODAY` · `ME HOT` (fever) ·
`DOCTOR HOSPITAL?` · `MEDICINE GOOD` · `MOTHER FATHER FAMILY` · `THANK-YOU`.
To change words, edit `vocab.json` (use labels from `data/meta/include_meta_raw.csv`) and re-run the steps.

## Setup

Python 3.11+ (tested with 3.14). You also need `ffmpeg` on PATH for the avatar clips (optional).

```powershell
pip install -r requirements.txt
```

## Storage

You do **not** need the 55 GB INCLUDE dataset. `fetch_include.py` reads the Zenodo zip indexes and
uses HTTP range requests to download only the ~336 videos for our 18 words. Then, for each video, it:

1. extracts landmarks to a `.npy` file (~40 KB),
2. keeps one short 480p clip per word for the avatar in `clips/` (~150 KB),
3. deletes the raw 14 MB video.

| | Size |
|---|---|
| Whole INCLUDE | ~55 GB |
| Raw videos for our words (`--keep-videos`) | ~4.7 GB |
| **What stays on disk (default)** | **~15 MB of keypoints + ~3 MB of clips** |
| Peak during download | ~100 MB |
| Webcam clips (3 people × 18 words × 5) | ~10 MB of keypoints + ~100 MB of small mp4s (`--no-video` skips the mp4s) |

## Steps

| When | Command | What it does |
|---|---|---|
| Tonight | `python scripts/fetch_include.py` | Downloads, extracts and deletes as described above (~1 h, resumable) |
| Day 1 | `python scripts/train.py` | First model on INCLUDE only. Writes `models/sign_classifier.pt` and `reports/` |
| Day 1 | `python scripts/record_signs.py --signer varsh` | Each teammate records 5 clips per word. The window plays the INCLUDE reference next to your camera |
| Day 2 | `python scripts/train.py` | Retrain with webcam clips included (they're oversampled ×3) |
| Day 2 | `python scripts/live_demo.py` | Live test in an OpenCV window |
| Day 2+ | `python service.py` | The deliverable: WebSocket service on port 8001 |
| Day 3 | `python scripts/train.py --only HELLO,ME,...` | If accuracy is shaky, keep only the best ~10 words (the per-word table printed by `train.py` shows which) |

Until the model is ready, Roshni and Indrasena can integrate against **`python service.py --mock`**. It
sends a scripted hospital conversation every 8 s, and `{"cmd":"flush"}` triggers the next sentence
immediately.

## Talking to sign_service (for Part B / Part C)

`ws://localhost:8001/ws`. Messages from server:

```json
{"from":"signer","type":"gloss","content":"ME SICK TODAY","sentence":"","language":"en",
 "emotion":"neutral","confidence":0.83,"timestamp":"2026-11-24T10:15:02+05:30",
 "words":[{"gloss":"ME","confidence":0.91},{"gloss":"SICK","confidence":0.77},{"gloss":"TODAY","confidence":0.81}]}
```

| type | meaning | who uses it |
|---|---|---|
| `gloss` | finished signed sentence; `sentence` is empty, so Part B fills it | Part B → sentence + TTS |
| `gloss_partial` | words so far (live feedback, includes `alternatives`) | Part C: show "signing: ME SICK…" |
| `status` | `content` = `signing` / `idle` / `camera_error` | Part C: indicator |

Extra keys (`words`, `alternatives`) are additions to the shared format and are safe to ignore.
`gloss_partial` and `status` are new `type` values, so confirm them with the team in the Day 1 check-in.

Client → server (optional): `{"cmd":"flush"}` (finish the sentence now, e.g. a "Send" button),
`{"cmd":"reset"}`, `{"cmd":"pause"}`, `{"cmd":"resume"}`.

Other endpoints:
- `GET /video_feed`: MJPEG camera preview with skeleton → `<img src="http://localhost:8001/video_feed">`
- `GET /health`, `GET /vocab`
- `POST /predict` (form field `file` = video of one sign) → `{gloss, confidence, top3}`
- `POST /predict_sequence` → the `gloss` message for a video of several signs

**Avatar clips for Part C:** `clips/index.json` maps each gloss to `<GLOSS>.mp4` (browser-playable
H.264) and `<GLOSS>.json` (2-D pose + hand landmarks per frame at 15 fps, for a skeleton avatar).
To play a gloss sequence, play the clips one after another.

## How to sign so it works

- Sit at your normal laptop distance, with your upper body and both hands in frame.
- **Drop your hands briefly (below chest level) between signs.** The segmenter tracks the body-pose
  wrists, so it works even when MediaPipe loses the hand itself.
- Lower your hands for about 1.5 s to finish the sentence (or send `flush`).
- Tuning lives in `signbridge_sign/recognizer.py` → `Settings` (`rest_y`, `min_conf`, `sentence_gap`, …).

## Files

```
vocab.json                    chosen words ↔ INCLUDE labels
service.py                    FastAPI WebSocket service (deliverable)
scripts/fetch_include.py      selective download → keypoints → delete
scripts/extract_keypoints.py  (re)extract keypoints from kept videos / webcam mp4s
scripts/record_signs.py       webcam recorder with INCLUDE reference video
scripts/train.py              training + accuracy, top-3, confusion matrices → reports/
scripts/live_demo.py          live OpenCV test
signbridge_sign/              landmarks, features, model, recognizer, clips, messages
```

## Notes for the report

- **Landmarks:** MediaPipe Holistic (Tasks API). mediapipe ≥ 0.10.30 removed `mp.solutions`, so
  AI4Bharat's `generate_keypoints.py` and pretrained model can't be used as-is. We wrote our own
  extractor and a smaller model.
- **Features (306 per frame):** 13 upper-body points + 2×21 hand points normalised by shoulder centre
  and width (studio→webcam invariance), wrist-relative hand shape, hand-present flags, and velocities.
  Each clip is trimmed to the hand-active frames and resampled to 32 frames.
- **Model:** Linear → 2-layer BiGRU (192) → attention pooling → softmax. Augmentation: rotation,
  scale, shift, temporal crop and speed change, hand dropout, jitter, and occasional left/right mirroring.
- **Split:** the Hugging Face metadata lists ~25 % of videos twice, sometimes in both train and test.
  We de-duplicate and use a fixed 70/15/15 split per word (`include_meta.py`). Webcam: every 4th clip
  is test, or use `--holdout-signer` to test on a person the model never saw.
- **Dataset:** INCLUDE, CC BY-NC-SA 4.0. Cite: A. Sridhar, R. G. Ganesan, P. Kumar, M. Khapra,
  "INCLUDE: A Large Scale Dataset for Indian Sign Language Recognition", ACM Multimedia 2020.
- **Future work:** fingerspelling, facial expression → emotion, TF.js export for offline/in-browser use.

# SignBridge: Two-Way Communication Assistant

SignBridge lets a Deaf or hard-of-hearing person and a hearing person have a natural conversation, even
if neither knows the other's language. A webcam recognises Indian Sign Language (ISL) signs and turns
them into a spoken sentence. The hearing person's speech, in English, Hindi or Telugu, is shown as
captions with a tone tag and played back as ISL sign clips by an on-screen avatar. Quick-reply phrases
and an emergency SOS mode cover moments when signing isn't practical.

| Part | Folder | Owner |
|---|---|---|
| A: Vision & Sign Recognition | [`sign_service/`](sign_service/) | Varsh |
| B: Speech, Language & AI | [`speech_service/`](speech_service/) | Roshni |
| C: App, Avatar & Integration | [`app/`](app/) | Indrasena Reddy |

Run the whole thing:

```powershell
cd sign_service; python service.py                  # Part A, port 8001 (--mock without a camera)
cd speech_service; docker compose up -d --build     # Part B, port 8002
cd app; .venv\Scripts\python server.py              # Part C, open http://localhost:8000
```

First-time setup for each part is in its README. To try the app alone: `python server.py --mock`, then
http://localhost:8000/?mock.

All parts exchange the same JSON message over WebSocket:

```json
{"from": "signer", "type": "gloss", "content": "ME SICK TODAY", "sentence": "",
 "language": "en", "emotion": "neutral", "confidence": 0.89, "timestamp": "2026-11-24T10:15:02+05:30"}
```

Sign data: INCLUDE dataset (AI4Bharat), CC BY-NC-SA 4.0, used for non-commercial academic work.
Sridhar et al., "INCLUDE: A Large Scale Dataset for Indian Sign Language Recognition", ACM Multimedia 2020.

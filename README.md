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
| C: App, Avatar & Integration | _to be added_ | Indrasena Reddy |

All parts exchange the same JSON message over WebSocket:

```json
{"from": "signer", "type": "gloss", "content": "ME SICK TODAY", "sentence": "",
 "language": "en", "emotion": "neutral", "confidence": 0.89, "timestamp": "2026-11-24T10:15:02+05:30"}
```

Sign data: INCLUDE dataset (AI4Bharat), CC BY-NC-SA 4.0, used for non-commercial academic work.
Sridhar et al., "INCLUDE: A Large Scale Dataset for Indian Sign Language Recognition", ACM Multimedia 2020.

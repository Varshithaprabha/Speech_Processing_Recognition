# app: Part C (App, Avatar & Integration)

The SignBridge app: a web app (React + Tailwind) and a small FastAPI backend (port 8000). The
hearing person and the Deaf user share one screen: each has their own half, with the conversation in the middle.
Report section for Part C: [REPORT.md](REPORT.md).

```
 browser (http://localhost:8000)
   ├── WebSocket ws://localhost:8002/ws ──► speech_service (Part B) ──► sign_service (Part A, :8001)
   │      section-6 messages both ways; Part B forwards Part A's gloss / gloss_partial / status
   ├── <img> http://localhost:8001/video_feed            camera preview with skeleton (Part A)
   ├── GET  :8002/tts, POST :8002/speech(_partial)        voice out / Whisper speech-to-text (Part B)
   └── app backend :8000  /clips/*  /api/history  /api/phrases  (+ /mock when started with --mock)
```

## Project doc requirements (section 5, Part C) → where they are

| Requirement | Status | Where |
|---|---|---|
| Backend skeleton that routes messages between A, B and the UI | ✅ | Part B's `/ws` is the message hub (it already connects to Part A). `server.py` serves the app, the sign clips, history and phrases, and has a `--mock` hub that fakes A + B |
| Conversation UI: split view, captions with tone tags, mode switch | ✅ | `App.jsx`, `SignerPanel.jsx` (reply by **Sign / Tap / Type**), `SpeakerPanel.jsx` (**Speak / Type**, en/hi/te), `Timeline.jsx`, `ToneTag.jsx` |
| Signing avatar that plays ISL gloss sequences from recorded clips | ✅ | `Avatar.jsx`: plays each sign's INCLUDE clip in order (**Video**), or a 2-D figure drawn from the clip's landmarks (**Figure**). Replay and tap-a-sign |
| Phrase board + quick-reply chips, customisable phrases | ✅ | `PhraseBoard.jsx` (Part B's phrases, translated by Part B) + "My phrases" (add/remove/reorder, saved in SQLite); smart reply chips `s1`–`s4` |
| Emergency SOS mode | ✅ | `SosOverlay.jsx`: one tap, flashing full screen, emergency sentence in the listener's language, big preset phrases, location shown on screen |
| Accessibility: large text, high contrast, vibration/flash alerts | ✅ | Settings → Accessibility. Urgent/angry captions and SOS flash the screen and vibrate. Keyboard focus rings; reduced motion respected |
| Conversation history, export | ✅ | "End & save" asks Part B for the summary and saves it with the transcript (`/api/history`, SQLite). Export: .txt, .json, print/PDF |
| Settings: language, voice, avatar speed | ✅ | Settings drawer (kept in localStorage) |
| Stretch: learn-as-you-talk | ✅ | In a saved conversation: the 5 signs used most, tap to watch |
| Stretch: mobile build | ✅ (responsive web) | Under 1024 px wide the three panels become tabs. Offline packaging is future work |

## Run it

Needs Node 20+ and Python 3.10+.

```powershell
cd app
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd web; npm install; npm run build; cd ..
.venv\Scripts\python server.py            # http://localhost:8000
```

Start the other two parts as usual (see their READMEs):

```powershell
cd speech_service; docker compose up -d --build     # Part B, port 8002 (needs GROQ_API_KEY in .env)
cd sign_service; python service.py                  # Part A, port 8001 (or --mock without a camera)
```

**UI only, nothing else running:** `.venv\Scripts\python server.py --mock`, then open
http://localhost:8000/?mock. The mock speaks the same messages as Part B: typed speech gets tone tags, avatar
signs and smart replies, and **Send signs** plays the next line of a scripted patient conversation. (No AI, no
Whisper, voice comes from the browser.)

**Developing the UI:** run `server.py` (for `/clips`, `/api`, `/mock`), then `cd web; npm run dev` and open
http://localhost:5173 (hot reload; Vite proxies to port 8000).

**Another device on the same Wi-Fi** (e.g. a tablet facing the patient): open `http://<laptop-ip>:8000` and set
the service URLs in Settings → Connections. Browsers only allow the microphone on `localhost` or `https`, so
use the laptop for speaking, or Type mode on the tablet.

## Using it (demo, section 8)

1. Hearing person (right): pick **తెలుగు**, tap 🎙️ and speak. The Deaf user (left) sees the caption with its tone
   tag (⚠️ Urgent), the avatar signs it, and smart replies appear.
2. Deaf user signs **ME HOT**, then drops their hands (or taps **Send signs**). The right side shows
   "I have a fever." in Telugu and reads it aloud.
3. Deaf user: **Tap** → "Please call my family." Or 🆘 **SOS** for an emergency.
4. **End & save**: summary + transcript go to History, with export and the signs to practise.

Speech recognition: **Browser** (Web Speech API; Chrome/Edge, instant live captions) or **Whisper** (records
and sends the audio to Part B; better for Telugu and works in Firefox). Voice: **Server** (Part B's `/tts`,
styled by tone) or **Browser** (`speechSynthesis`). If the server voice fails, the browser voice is used.

## Messages

The app uses exactly the commands and messages in [speech_service/README.md](../speech_service/README.md).
Sent: `text`, `partial`, `quick_reply`, `sos`, `summary`, `new_conversation`, `set_language`, `flush`, `reset`,
`pause`, `resume`. Received: everything in Part B's table. Typed text and "My phrases" from the Deaf user have
no command in Part B, so the app shows and speaks them itself (in English) and keeps them in its own transcript.

## Files

```
server.py                  FastAPI: built app, /clips, /api/history, /api/phrases (SQLite in data/)
mock_hub.py                fake Part A + B on /mock/ws for UI work
web/src/App.jsx            state, message routing, End & save, layout
web/src/lib/bridge.js      WebSocket to Part B (auto-reconnect) + /health polling
web/src/lib/voice.js       text-to-speech queue, browser / Whisper speech-to-text, vibration
web/src/lib/api.js         backend calls, clip index, export (.txt / .json / print)
web/src/lib/settings.js    settings + defaults (localStorage)
web/src/components/        SignerPanel, SpeakerPanel, Timeline, Avatar, PhraseBoard, ToneTag,
                           SosOverlay, SettingsDrawer, HistoryDrawer, Drawer
```

# speech_service: Part B (Speech, Language & AI)

Sits between Part A (`sign_service`, port 8001) and Part C (the app). It is the speech service and the
language service in one FastAPI process on port 8002. **Part C only needs to connect to
`ws://localhost:8002/ws`.** Report section for Part B: [REPORT.md](REPORT.md).

```
Signer:   sign_service ──gloss "ME HOT YESTERDAY TODAY"──► AI / rules ──► "I've had a fever since yesterday." ──► Part C (+ TTS)
Speaker:  Part C mic ──audio──► Whisper (en/hi/te) ──► AI / rules ──► caption + tone tag + gloss [YESTERDAY TODAY YOU HOT] + clips ──► avatar
                                    └─► live partial captions                      └─► smart reply suggestions for the signer
```

## Project doc requirements (section 5, Part B) → where they are

| Requirement | Status | How |
|---|---|---|
| Speech-to-text in English, Hindi, Telugu | ✅ | Groq Whisper large-v3 (free), local Whisper fallback; or browser STT via `{"cmd":"text"}` |
| Streaming partial captions | ✅ | `speech_partial` messages: `POST /speech_partial` (audio) or `{"cmd":"partial"}` (browser interim results) |
| Tone/emotion tag | ✅ from text (sprint plan, section 7) | AI + rules: neutral, happy, angry, urgent, question. Shouting (CAPS, "!!") → angry |
| Text-to-speech | ✅ | `GET /tts` (edge-tts en-IN/hi-IN/te-IN voices, faster for urgent); or browser speechSynthesis |
| ISL gloss → natural sentence | ✅ | in the listener's language, using recent conversation |
| Sentence → ISL gloss for the avatar | ✅ | only signs with clips in `sign_service/clips`, plus the clip list |
| Translation between languages | ✅ | captions in English, signer's sentences in the speaker's language |
| Smart quick replies from the last few messages | ✅ | `suggestions` message after every speaker line, in the speaker's language; tap with `{"cmd":"quick_reply","id":"s1"}` |
| Conversation auto-summary (stretch) | ✅ | `GET /summary` or `{"cmd":"summary"}`; transcript for export via `GET /transcript` |
| Tone from the voice audio, emotion-matched TTS, sound alerts | ➖ future work | cut in the sprint plan (section 7) |

## AI providers (all free)

Tried in order, each falling back to the next (`source` in every message says which one answered):

1. **Groq**: free key from https://console.groq.com/keys (no card). Text: `openai/gpt-oss-120b` with strict
   JSON output and low reasoning effort. Speech: `whisper-large-v3` (live captions: `-turbo`). Best quality,
   needs internet. Free-tier limits (e.g. 8,000 tokens/min) apply. On a rate-limit error, Groq is skipped for
   the wait time it asks for, so replies keep coming from the next provider.
2. **Ollama**: local, no key, works offline. Install https://ollama.com, then `ollama pull gemma3:4b`
   (~3.3 GB; good Hindi, weaker Telugu; ~1 s per reply on a laptop GPU).
3. **Rules** (`signbridge_speech/rules.py`): always available, English templates + en/hi/te keywords.

Speech-to-text falls back from Groq Whisper to local Whisper (`small`), which is much weaker for Telugu.

**Safety (it's a hospital):**
- Signer side: the rules' draft is the meaning the AI must keep. If the AI's sentence mentions something
  that wasn't signed (e.g. "fever" for SICK), it retries without history, then uses the draft. The emotion
  from sign_service (the face) is kept.
- Speaker side: captions come only from what was said (no conversation history), and garbled speech is
  marked `"unclear": true` instead of being guessed. Avatar signs are checked against words actually said.
  Urgent/angry wording is never missed.

Check it with `python scripts/try_llm.py`. To use paid Claude instead, set `LLM_PROVIDERS=anthropic,ollama`
and `ANTHROPIC_API_KEY`.

## Setup and run

```powershell
copy .env.example .env        # paste your free GROQ_API_KEY into .env (never commit it)
ollama pull gemma3:4b         # local fallback model (optional)
```

**Docker (recommended on Windows with Smart App Control,** which blocks Whisper's/PyTorch's native
libraries):

```powershell
cd speech_service
docker compose up -d --build     # first run downloads ~1 GB incl. the local Whisper model (kept in a volume)
docker compose logs -f
docker compose down
```

The container reaches sign_service at `host.docker.internal:8001`, Ollama at `host.docker.internal:11434`
and reads `../sign_service/clips` read-only. After editing `.env`: `docker compose up -d`. After changing
code: `docker compose up -d --build`.

**Part A on another laptop** (e.g. where Windows blocks MediaPipe on this one): run `python service.py`
there, then put `SIGN_WS_URL=ws://<that-laptop-ip>:8001/ws` in this `.env` and run `docker compose up -d`.
`/health` shows `"sign_service": true` once connected. In the app, set Settings → Connections → sign
service to `http://<that-laptop-ip>:8001` for the camera preview. Both laptops must be on the same network,
and that laptop's firewall must allow port 8001.

**Without Docker:** `pip install -r requirements.txt` then `python service.py`
(flags: `--no-llm`, `--no-sign`, `--preload-whisper`).

**Test with the mock signer:**

```powershell
cd ..\sign_service; python service.py --mock          # terminal 1
python scripts/test_client.py --quiet-partials         # terminal 2 (pretends to be Part C)
```

## Messages Part C receives on `/ws` (section 6 format)

Every message has `from, type, content, sentence, language, emotion, confidence, timestamp`, plus the
extras below.

| from | type | content | sentence | extras |
|---|---|---|---|---|
| signer | `gloss` | `ME HOT YESTERDAY TODAY` | sentence to show/speak, in the speaker's language | `sentence_en`, `source`, `words` |
| signer | `gloss_partial`, `status` | forwarded unchanged from sign_service | | |
| signer | `text` | phrase in English | phrase in the speaker's language | `kind`: `quick_reply` / `suggestion` |
| signer | `alert` | `SOS` | emergency message | `kind`: `sos`, emotion `urgent` |
| speaker | `speech_partial` | words so far | same | live caption, no AI |
| speaker | `text` | what was said (original language) | English caption | `gloss` (avatar order), `clips` [{gloss, video, landmarks, duration}], `unclear`, `input` |
| system | `suggestions` | | | `suggestions`: [{id `s1`..`s4`, text_en, text}] |
| system | `summary` | summary | summary | `key_points`, `transcript` |
| system | `status` | `sign_service_disconnected` | | |

`emotion`: `neutral`, `happy`, `angry`, `urgent`, `question`. `source`: `groq`, `ollama`, `rules`, …
`clips[].video` is a filename in `sign_service/clips/`. The avatar can also play **YOU**: the recogniser
dropped it, but its clip still exists.

## Sending to speech_service

On `/ws` (JSON):
- `{"cmd":"partial","content":"Do you have","language":"en"}`: live caption (browser STT interim result)
- `{"cmd":"text","content":"Aapko kal se bukhar hai?","language":"hi"}`: speaker's final words (typed or browser STT)
- `{"cmd":"quick_reply","id":"water"}` (phrase board, ids: `GET /quick_replies`) or `"id":"s2"` (smart suggestion)
- `{"cmd":"sos"}`, `{"cmd":"summary"}`, `{"cmd":"new_conversation"}`
- `{"cmd":"set_language","language":"te"}`: language the speaker wants to hear (also set from their speech)
- `{"cmd":"flush"|"reset"|"pause"|"resume"}`: forwarded to sign_service

HTTP:
- `POST /speech`: multipart `file` (any audio: webm/ogg/mp3/m4a/wav) + optional `language` → final `text` message (also broadcast)
- `POST /speech_partial`: same, for audio still being recorded → `speech_partial` (~0.5 s)
- `POST /text` `{"content","language"}`, `POST /gloss` `{"content","emotion"}` (testing)
- `GET /tts?text=...&language=hi&emotion=urgent` → MP3. If it fails, use the browser's `speechSynthesis`.
- `GET /suggestions`, `GET /summary`, `GET /transcript`, `GET /quick_replies`, `GET /health`

## Measured (Docker on a laptop, Groq free tier)

- Speech → caption + tone + avatar signs: 1.3–2.5 s (en/hi/te). Live partial caption: ~0.5 s.
- Gloss → sentence: 0.5–1.2 s. TTS: ~1.5 s per sentence.
- Telugu demo line "దయచేసి వెంటనే డాక్టర్ దగ్గరకు వెళ్ళండి" → "Go to the doctor immediately." (urgent).

## Files

```
service.py                     FastAPI service (deliverable), port 8002
signbridge_speech/pipeline.py  both directions, smart replies, summary, phrase board, SOS
signbridge_speech/llm.py       Groq / Ollama (/ Claude) prompts, structured JSON output
signbridge_speech/rules.py     offline fallback: gloss→sentence, en/hi/te keywords→gloss, tone, replies
signbridge_speech/asr.py       speech-to-text: Groq Whisper, local Whisper; decodes any audio format
signbridge_speech/tts.py       edge-tts voices (en-IN, hi-IN, te-IN)
scripts/test_client.py         fake Part C for testing
scripts/try_llm.py             test the AI layer without running the service
```

# speech_service: Part B (Speech, Language & AI)

Sits between Part A (`sign_service`, port 8001) and Part C (the app). **Part C only needs to connect to
`ws://localhost:8002/ws`.**

```
Signer:   sign_service ──gloss "ME HOT YESTERDAY TODAY"──► AI / rules ──► "I've had a fever since yesterday." ──► Part C (+ TTS)
Hearing:  Part C mic ──audio──► Whisper (en/hi/te) ──► AI / rules ──► caption + tone + gloss [YESTERDAY TODAY YOU HOT] + clips ──► avatar
```

## AI providers (all free)

Tried in order, each falling back to the next (`source` in every message says which one answered):

1. **Groq**: free key from https://console.groq.com/keys (no card). Model `openai/gpt-oss-120b`, strict JSON
   output. Best quality and Hindi/Telugu. Needs internet. The free tier allows roughly 30 requests/min and 1,000/day.
2. **Ollama**: local, no key, works offline. Install https://ollama.com, then `ollama pull gemma3:4b`
   (~3.3 GB; good Hindi, weaker Telugu; ~1 s per reply on a laptop GPU).
3. **Rules** (`signbridge_speech/rules.py`): always available, English templates + en/hi/te keywords.

Safety: the AI only polishes meaning, it can't add to it. The rules' draft is given to the AI as the
meaning to keep. If the AI's sentence mentions something the patient didn't sign (e.g. "fever" for SICK),
the service retries once without history, then uses the draft. On the hearing side, avatar signs are
checked against words that were actually said. The emotion from sign_service (the face) is kept.

Check it with `python scripts/try_llm.py`. To use paid Claude instead, set `LLM_PROVIDERS=anthropic,ollama`
and `ANTHROPIC_API_KEY`.

## Setup

```powershell
pip install -r requirements.txt
copy .env.example .env        # paste your free GROQ_API_KEY into .env (optional)
ollama pull gemma3:4b         # local model (optional)
```

## Run

```powershell
# terminal 1 (Part A, fake signer)
cd ..\sign_service; python service.py --mock
# terminal 2 (Part B)
python service.py
# terminal 3 (pretend to be Part C)
python scripts/test_client.py --quiet-partials
```

Flags: `--no-llm` (rules only), `--no-sign` (don't connect to sign_service), `--preload-whisper`.

## Messages Part C receives on `/ws`

| from | type | content | sentence | extra |
|---|---|---|---|---|
| signer | `gloss` | `ME HOT YESTERDAY TODAY` | sentence to show/speak, in the listener's language | `sentence_en`, `source` (llm/rules), `words` |
| signer | `gloss_partial`, `status` | forwarded unchanged from sign_service | | |
| signer | `quick_reply` | reply id | the phrase | `sentence_en` |
| signer | `sos` | `SOS` | emergency message | emotion `urgent` |
| hearing | `speech` / `text` | what was said (original language) | English caption | `gloss` (avatar sequence), `clips` [{gloss, video, landmarks, duration}] |
| system | `status` | `sign_service_disconnected` | | |

`emotion` (the tone tag) is one of `neutral`, `question`, `urgent`, `happy`.
`clips[].video` is a filename in `sign_service/clips/`. The avatar can also play **YOU**: the recogniser
dropped it, but its clip still exists.

## Sending to speech_service

On `/ws` (JSON):
- `{"cmd":"text","content":"Aapko kal se bukhar hai?","language":"hi"}`: the hearing person's words (typed, or from browser speech recognition)
- `{"cmd":"quick_reply","id":"water"}` (ids: `GET /quick_replies`), `{"cmd":"sos"}`
- `{"cmd":"set_language","language":"te"}`: language the hearing person wants to hear (also set automatically from their speech)
- `{"cmd":"flush"|"reset"|"pause"|"resume"}`: forwarded to sign_service

HTTP:
- `POST /speech`: multipart `file` (audio; **16-bit WAV** is safest) + optional `language` → hearing message (also broadcast)
- `POST /text` `{"content","language"}`, `POST /gloss` `{"content","emotion"}` (for testing)
- `GET /tts?text=...&language=hi&emotion=urgent` → MP3 (edge-tts, online). If it fails, use the browser's `speechSynthesis`.
- `GET /health`: shows the AI providers (and whether Ollama is reachable), Whisper and sign_service

## Run in Docker (recommended on Windows with Smart App Control)

Windows **Smart App Control** blocks Whisper's native libraries (ctranslate2, PyAV; also PyTorch), so on
such PCs run Part B in a Linux container. sign_service keeps running on Windows as usual.

```powershell
# Docker Desktop must be running
cd speech_service
docker compose up -d --build     # first run downloads ~1 GB incl. the Whisper "small" model (kept in a volume)
docker compose logs -f           # watch it
docker compose down              # stop (the downloaded model is kept)
```

- Same port (8002) and same API as running it directly. The container reaches sign_service at
  `host.docker.internal:8001` and reads `../sign_service/clips` read-only.
- `.env` (GROQ_API_KEY) is picked up if present. The container talks to Ollama on Windows via `host.docker.internal:11434`; after editing it, run `docker compose up -d` again.
- After changing Part B's code, run `docker compose up -d --build`.
- Speed (CPU, `small`): about 1.5–2 s per short sentence. Use `WHISPER_MODEL=base` in `.env` for faster, less accurate results.

Without Docker, the service still runs directly with Python. If Whisper can't load, `/speech` returns
503 (see `/health`) and Part C can send text from browser speech recognition instead.

## Files

```
service.py                     FastAPI service (deliverable), port 8002
signbridge_speech/pipeline.py  both directions, conversation memory, quick replies, SOS
signbridge_speech/llm.py       Groq / Ollama (/ Claude) prompts, structured JSON output
scripts/try_llm.py             test the AI layer without running the service
signbridge_speech/rules.py     offline fallback: gloss→sentence, en/hi/te keywords→gloss, tone
signbridge_speech/asr.py       Whisper speech-to-text (WAV decoded without PyAV)
signbridge_speech/tts.py       edge-tts voices (en-IN, hi-IN, te-IN)
scripts/test_client.py         fake Part C for testing
```

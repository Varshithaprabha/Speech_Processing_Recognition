# Part C: App, Avatar & Integration (report section)

## What it does

Part C is what both users see. One screen is split in three: the Deaf user's half (signing avatar, captions,
reply by sign / tap / type), the conversation in the middle, and the hearing person's half (the signed sentence in
their language, read aloud, and a microphone). It is a React web app served by a small FastAPI backend.

## Design decisions

- **One connection.** Part B already connects to Part A and forwards its messages, so the app opens a single
  WebSocket (`ws://localhost:8002/ws`) and never talks to two services in different formats. The only direct link
  to Part A is the MJPEG camera preview. The app reconnects automatically and shows which parts are up.
- **Avatar from recorded clips, two styles.** Each gloss has a short INCLUDE clip (`sign_service/clips`). The
  avatar plays them in order at an adjustable speed. The **Figure** style draws a 2-D signer from the same clip's
  MediaPipe landmarks (pose + 21 points per hand, 15 fps) on a canvas. It is lighter, looks the same for every
  sign, and is the first step toward a 3-D avatar. A missing clip shows the word instead of stopping the sentence.
- **Tone is never colour alone.** Every tag has an emoji and a word (⚠️ Urgent, ❓ Question…), so it works in high
  contrast and for colour-blind users. Urgent or angry speech also flashes the screen edge and vibrates.
- **Fastest reply first.** Smart replies sit right under the caption in every mode. Unclear speech (`unclear: true`
  from Part B) shows a large "?" with a one-tap "Ask them to repeat".
- **Fallbacks for a live demo.** Server voice → browser voice. Browser speech recognition → Whisper (or the other
  way round, chosen in Settings). Backend down → phrases kept on the device, conversation downloaded as text instead
  of saved. `server.py --mock` runs the whole UI with no other service, which is how Part C was built before
  integration day (sprint rule: "work against mock messages").
- **Privacy.** SOS location is shown on the screen only, never sent. History is a local SQLite file.

## Accessibility

Three text sizes (the whole layout scales), high-contrast theme (black / yellow / cyan), flash and vibration
alerts (each can be turned off), visible keyboard focus, `aria-live` captions, reduced motion respected, and a
responsive layout that turns the three panels into tabs on phones and tablets.

## Tested

- Against Part B (`speech_service`, rules mode) + Part A (`sign_service --mock`): typed and spoken English,
  Telugu text, tone tags, avatar clips, smart replies, phrase board, Send signs, SOS, summary → history.
- Against `server.py --mock`: every screen, both avatar styles, high contrast + large text, mobile layout (375 px).

## Limitations and future work

- Typed text and custom phrases from the Deaf user are spoken in English: Part B has no command to translate
  them yet (`{"cmd":"signer_text"}` would fix this).
- 3-D avatar, offline packaging (PWA + on-device models), and a native mobile build.
- Microphone access on another device needs HTTPS.

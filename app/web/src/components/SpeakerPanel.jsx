import { useEffect, useRef, useState } from 'react'
import { LANGS } from '../lib/settings'
import { browserSttSupported, startBrowserStt, startWhisperStt } from '../lib/voice'
import ToneTag from './ToneTag'

const PLACEHOLDER = {
  en: 'Type what you want to say…',
  hi: 'जो कहना है वह लिखें…',
  te: 'మీరు చెప్పాలనుకున్నది టైప్ చేయండి…',
}

/** Right half: what the hearing person sees (the signer's sentence, spoken aloud) and how they talk. */
export default function SpeakerPanel({ settings, update, lastSigner, signingPartial, speaking, send, onSpeak, onError }) {
  const [mode, setMode] = useState('speak')
  const [text, setText] = useState('')
  const [listening, setListening] = useState(false)
  const [busy, setBusy] = useState(false)
  const rec = useRef(null)
  const lastPartial = useRef(0)
  const lang = settings.language
  const engine = settings.sttEngine === 'browser' && !browserSttSupported() ? 'whisper' : settings.sttEngine

  useEffect(() => () => rec.current?.stop(), [])

  const setLang = (l) => {
    update({ language: l })
    send({ cmd: 'set_language', language: l })
  }

  const toggleMic = async () => {
    if (listening) {
      rec.current?.stop()
      return
    }
    try {
      setListening(true)
      if (engine === 'browser') {
        rec.current = startBrowserStt({
          language: lang,
          onPartial: (t) => {
            const now = Date.now()
            if (now - lastPartial.current > 250) {
              lastPartial.current = now
              send({ cmd: 'partial', content: t, language: lang })
            }
          },
          onFinal: (t, conf) => t && send({ cmd: 'text', content: t, language: lang, confidence: conf, input: 'speech' }),
          onError: (e) => onError(`Speech recognition: ${e}`),
          onEnd: () => setListening(false),
        })
      } else {
        rec.current = await startWhisperStt({
          base: settings.speechUrl,
          language: lang,
          onBusy: setBusy,
          onError: (e) => onError(`Whisper: ${e}`),
          onEnd: () => setListening(false),
        })
      }
    } catch (e) {
      setListening(false)
      onError(`Microphone: ${e.message || e}`)
    }
  }

  const submit = (e) => {
    e.preventDefault()
    if (!text.trim()) return
    send({ cmd: 'text', content: text.trim(), language: lang, input: 'text' })
    setText('')
  }

  return (
    <section className="panel flex min-h-0 flex-1 flex-col overflow-hidden" aria-label="Hearing person">
      <header className="flex items-center justify-between border-b border-line bg-speaker-soft px-4 py-2.5">
        <h2 className="flex items-center gap-2 font-bold">
          <span aria-hidden>🗣️</span> Hearing person
        </h2>
        <div className="flex rounded-xl border border-line bg-surface p-0.5" role="radiogroup" aria-label="Language">
          {Object.entries(LANGS).map(([k, v]) => (
            <button
              key={k}
              role="radio"
              aria-checked={lang === k}
              onClick={() => setLang(k)}
              className={`rounded-lg px-2.5 py-0.5 text-sm font-semibold ${
                lang === k ? 'bg-speaker text-white' : 'text-muted hover:text-ink'
              }`}
              title={v.name}
            >
              {v.native}
            </button>
          ))}
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
        {/* what the Deaf user said */}
        <div className="rounded-xl border border-line bg-sunken p-4" aria-live="assertive">
          <div className="mb-1 flex items-center justify-between">
            <span className="label">They said {speaking && <span className="blink">🔊</span>}</span>
            {lastSigner && <ToneTag emotion={lastSigner.emotion} size="lg" />}
          </div>
          {signingPartial ? (
            <p className="text-lg text-muted">
              <span className="blink">✋</span> signing… <b className="tracking-wide">{signingPartial}</b>
            </p>
          ) : lastSigner ? (
            <>
              <p className={`text-3xl leading-tight font-semibold ${lastSigner.type === 'alert' ? 'text-danger' : ''}`}>
                {lastSigner.sentence || lastSigner.content}
              </p>
              {lastSigner.sentence_en && lastSigner.sentence_en !== lastSigner.sentence && (
                <p className="mt-1 text-muted">{lastSigner.sentence_en}</p>
              )}
              <button className="btn mt-3" onClick={() => onSpeak(lastSigner)}>
                🔊 Say it again
              </button>
            </>
          ) : (
            <p className="text-muted">The Deaf user’s signs will appear here as a sentence and be read aloud.</p>
          )}
        </div>

        <div className="mt-auto flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="label">Reply by</span>
            <div role="tablist" className="flex rounded-xl border border-line bg-sunken p-0.5">
              {[
                ['speak', '🎙️ Speak'],
                ['type', '⌨️ Type'],
              ].map(([id, label]) => (
                <button
                  key={id}
                  role="tab"
                  aria-selected={mode === id}
                  onClick={() => setMode(id)}
                  className={`rounded-lg px-3 py-1 text-sm font-semibold ${
                    mode === id ? 'bg-speaker text-white' : 'text-muted hover:text-ink'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {mode === 'speak' ? (
            <div className="flex flex-col items-center gap-2 py-2">
              <button
                onClick={toggleMic}
                disabled={busy}
                className={`grid h-24 w-24 place-items-center rounded-full text-4xl text-white shadow-lg transition ${
                  listening ? 'recording bg-danger' : 'bg-speaker hover:brightness-110'
                } disabled:opacity-50`}
                aria-pressed={listening}
                aria-label={listening ? 'Stop listening' : 'Start speaking'}
              >
                {busy ? '…' : listening ? '■' : '🎙️'}
              </button>
              <div className="text-center text-sm text-muted">
                {busy
                  ? 'Transcribing…'
                  : listening
                    ? `Listening in ${LANGS[lang].name}… tap to stop`
                    : `Tap and speak in ${LANGS[lang].name}`}
                <div className="text-xs">
                  {engine === 'browser' ? 'Browser speech recognition' : 'Whisper (speech_service)'}
                </div>
              </div>
            </div>
          ) : (
            <form onSubmit={submit} className="flex gap-2">
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={PLACEHOLDER[lang]}
                lang={LANGS[lang].bcp}
                className="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-3 text-lg"
              />
              <button className="btn btn-speaker" disabled={!text.trim()}>
                Send
              </button>
            </form>
          )}
        </div>
      </div>
    </section>
  )
}

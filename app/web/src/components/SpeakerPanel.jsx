import { useEffect, useRef, useState } from 'react'
import { LANGS } from '../lib/settings'
import { browserSttSupported, startBrowserStt, startWhisperStt } from '../lib/voice'
import Icon from './Icon'
import ToneTag from './ToneTag'
import Wave from './Wave'
import Words from './Words'

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
    <section className="panel side-speaker flex min-h-0 flex-1 flex-col overflow-hidden" aria-label="Hearing person">
      <span className="panel-edge" aria-hidden />
      <header className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4 pb-2">
        <h2 className="flex items-center gap-2.5 text-lg font-bold">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-speaker-soft text-speaker ring-1 ring-speaker/40" aria-hidden>
            <Icon name="voice" className="h-4.5 w-4.5" />
          </span>
          Hearing person
        </h2>
        <div className="seg seg-speaker" role="radiogroup" aria-label="Language">
          {Object.entries(LANGS).map(([k, v]) => (
            <button key={k} role="radio" aria-checked={lang === k} onClick={() => setLang(k)} title={v.name}>
              {v.native}
            </button>
          ))}
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 pb-5">
        {/* what the Deaf user said */}
        <div className="screen flex min-h-[11rem] flex-col p-5" aria-live="assertive">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="label flex items-center gap-2">
              They said
              <Wave live={speaking} bars={10} className="h-3.5 text-accent" label={speaking ? 'Speaking aloud' : undefined} />
            </span>
            {lastSigner && !signingPartial && <ToneTag emotion={lastSigner.emotion} size="lg" />}
          </div>
          {signingPartial ? (
            <p className="flex items-center gap-3 text-lg text-muted">
              <Wave live bars={6} className="h-5 text-accent" />
              signing… <b className="font-mono tracking-wide text-accent">{signingPartial}</b>
            </p>
          ) : lastSigner ? (
            <>
              <p
                className={`font-display text-3xl leading-tight font-semibold lg:text-[2.35rem] ${
                  lastSigner.type === 'alert' ? 'text-danger' : ''
                }`}
              >
                <Words key={lastSigner.id} text={lastSigner.sentence || lastSigner.content} step={70} />
              </p>
              {lastSigner.sentence_en && lastSigner.sentence_en !== lastSigner.sentence && (
                <p className="mt-2 text-muted">{lastSigner.sentence_en}</p>
              )}
              <button className="btn mt-4 self-start" onClick={() => onSpeak(lastSigner)}>
                <Icon name="volume" className="h-4 w-4 text-accent" /> Say it again
              </button>
            </>
          ) : (
            <p className="my-auto text-muted">The Deaf user’s signs will appear here as a sentence and be read aloud.</p>
          )}
        </div>

        <div className="mt-auto flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="label">Reply by</span>
            <div role="tablist" className="seg seg-speaker">
              {[
                ['speak', 'Speak', 'mic'],
                ['type', 'Type', 'keyboard'],
              ].map(([id, label, icon]) => (
                <button
                  key={id}
                  role="tab"
                  aria-selected={mode === id}
                  onClick={() => setMode(id)}
                  className="inline-flex items-center gap-1.5"
                >
                  <Icon name={icon} className="h-3.5 w-3.5" /> {label}
                </button>
              ))}
            </div>
          </div>

          {mode === 'speak' ? (
            <div className="flex flex-col items-center gap-3 py-3">
              <button
                onClick={toggleMic}
                disabled={busy}
                className={`grid h-24 w-24 place-items-center rounded-full text-4xl transition disabled:opacity-50 ${
                  listening
                    ? 'recording bg-danger text-white'
                    : 'mic-idle bg-speaker text-speaker-ink hover:scale-105'
                }`}
                aria-pressed={listening}
                aria-label={listening ? 'Stop listening' : 'Start speaking'}
              >
                {busy ? '…' : <Icon name={listening ? 'stop' : 'mic'} className="h-10 w-10" strokeWidth={2.2} />}
              </button>
              <Wave
                live={listening || busy}
                bars={28}
                className={`h-8 ${listening ? 'text-danger' : 'text-speaker'}`}
              />
              <div className="text-center text-sm text-muted">
                {busy
                  ? 'Transcribing…'
                  : listening
                    ? `Listening in ${LANGS[lang].name}… tap to stop`
                    : `Tap and speak in ${LANGS[lang].name}`}
                <div className="label mt-1 !text-[0.62rem]">
                  {engine === 'browser' ? 'Browser speech recognition' : 'Whisper (speech_service)'}
                </div>
              </div>
            </div>
          ) : (
            <form onSubmit={submit} className="side-speaker flex gap-2">
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={PLACEHOLDER[lang]}
                lang={LANGS[lang].bcp}
                className="field min-w-0 flex-1 px-3 py-3 text-lg"
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

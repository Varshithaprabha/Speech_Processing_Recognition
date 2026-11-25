import { useEffect, useRef } from 'react'
import ToneTag from './ToneTag'
import Wave from './Wave'

const time = (ts) => {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

const KIND = {
  quick_reply: 'Phrase board',
  suggestion: 'Quick reply',
  custom: 'My phrase',
  typed: 'Typed',
  sos: 'SOS',
}

/** Chat-style conversation display: Deaf user on the left (jade), hearing person on the right (amber). */
export default function Timeline({ items, speakerPartial, signingPartial, onReplaySigns, onSpeak }) {
  const end = useRef(null)
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [items.length, speakerPartial, signingPartial])

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4" role="log" aria-live="polite">
      {items.length === 0 && !speakerPartial && !signingPartial && (
        <div className="m-auto max-w-xs text-center text-sm text-muted">
          <div className="mb-2 text-3xl" aria-hidden>
            🤝
          </div>
          The conversation appears here. Sign, tap a phrase, speak or type to begin.
        </div>
      )}
      {items.map((m) => (m.from === 'signer' ? <SignerBubble key={m.id} m={m} onSpeak={onSpeak} /> : (
        <SpeakerBubble key={m.id} m={m} onReplaySigns={onReplaySigns} />
      )))}
      {signingPartial && (
        <div className="msg-in flex max-w-[85%] items-center gap-2 self-start rounded-2xl rounded-bl-sm border border-dashed border-accent bg-accent-soft px-3 py-2 text-sm">
          <Wave live bars={5} className="h-4 text-accent" />
          <span className="text-muted">signing</span> <b className="font-mono tracking-wide text-accent">{signingPartial}…</b>
        </div>
      )}
      {speakerPartial && (
        <div className="msg-in flex max-w-[85%] items-center gap-2 self-end rounded-2xl rounded-br-sm border border-dashed border-speaker bg-speaker-soft px-3 py-2 text-sm italic">
          <Wave live bars={5} className="h-4 text-speaker" />
          {speakerPartial}…
        </div>
      )}
      <div ref={end} />
    </div>
  )
}

function SignerBubble({ m, onSpeak }) {
  const alert = m.type === 'alert'
  const showGloss = m.type === 'gloss' && m.content
  const showEn = m.sentence_en && m.sentence_en !== m.sentence
  return (
    <div className="msg-in flex max-w-[88%] flex-col items-start gap-1 self-start">
      <div className="flex items-center gap-2 font-mono text-[0.7rem] text-muted">
        <b className="text-accent">Deaf user</b>
        <span>{m.type === 'gloss' ? 'signed' : KIND[m.kind] || m.type}</span>
        <span>· {time(m.timestamp)}</span>
      </div>
      <div
        className={`rounded-2xl rounded-tl-sm px-4 py-2.5 ${
          alert ? 'bg-danger text-white shadow-[0_0_24px_rgba(255,90,78,0.4)]' : 'border border-accent/35 bg-accent-soft text-ink'
        }`}
      >
        <div className="text-[1.05rem] leading-snug font-medium">{m.sentence || m.content}</div>
        {showEn && <div className="mt-0.5 text-sm opacity-75">{m.sentence_en}</div>}
        {showGloss && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {m.content.split(/\s+/).map((g, i) => (
              <span key={i} className="gloss">
                {g}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2">
        <ToneTag emotion={m.emotion} hideNeutral />
        {typeof m.confidence === 'number' && m.type === 'gloss' && (
          <span className="font-mono text-[0.7rem] text-muted">{Math.round(m.confidence * 100)}% sure</span>
        )}
        <button className="text-xs text-muted underline-offset-2 hover:underline" onClick={() => onSpeak(m)}>
          🔊 say again
        </button>
      </div>
    </div>
  )
}

function SpeakerBubble({ m, onReplaySigns }) {
  const showOriginal = m.content && m.sentence && m.content !== m.sentence
  return (
    <div className="msg-in flex max-w-[88%] flex-col items-end gap-1 self-end">
      <div className="flex items-center gap-2 font-mono text-[0.7rem] text-muted">
        <span>{time(m.timestamp)} ·</span>
        <span>{m.input === 'text' ? 'typed' : 'spoke'}</span>
        <b className="text-speaker">Hearing person</b>
      </div>
      <div className="rounded-2xl rounded-tr-sm border border-speaker/35 bg-speaker-soft px-4 py-2.5 text-ink">
        <div className="text-[1.05rem] leading-snug font-medium">
          {m.sentence || m.content}
          {m.unclear && (
            <span className="ml-2 rounded-full bg-speaker px-2 text-sm font-bold text-speaker-ink" title="Unclear speech">
              ?
            </span>
          )}
        </div>
        {showOriginal && <div className="mt-0.5 text-sm opacity-75">{m.content}</div>}
      </div>
      <div className="flex items-center gap-2">
        {m.clips?.length > 0 && (
          <button
            className="text-xs text-muted underline-offset-2 hover:underline"
            onClick={() => onReplaySigns(m)}
            title="Play the signs again"
          >
            ▶ {m.clips.map((c) => c.gloss).join(' ')}
          </button>
        )}
        <ToneTag emotion={m.emotion} hideNeutral />
      </div>
    </div>
  )
}

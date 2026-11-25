import { useState } from 'react'
import Avatar from './Avatar'
import Icon from './Icon'
import PhraseBoard from './PhraseBoard'
import ToneTag from './ToneTag'
import Wave from './Wave'
import Words from './Words'

const MODES = [
  { id: 'sign', label: 'Sign', icon: 'hand' },
  { id: 'tap', label: 'Tap', icon: 'tap' },
  { id: 'type', label: 'Type', icon: 'keyboard' },
]

/** Left half: what the Deaf user sees (avatar + captions) and how they reply (sign / tap / type). */
export default function SignerPanel({
  settings,
  avatarSeq,
  lastSpeaker,
  speakerPartial,
  signing,
  signConnected,
  suggestions,
  quick,
  custom,
  onSaveCustom,
  send,
  onLocalSay,
}) {
  const [mode, setMode] = useState('sign')
  const [typed, setTyped] = useState('')
  const [paused, setPaused] = useState(false)
  const [camFailed, setCamFailed] = useState(false)

  const submitTyped = (e) => {
    e.preventDefault()
    if (!typed.trim()) return
    onLocalSay(typed.trim(), 'typed')
    setTyped('')
  }

  return (
    <section className="panel side-signer flex min-h-0 flex-1 flex-col overflow-hidden" aria-label="Deaf user">
      <span className="panel-edge" aria-hidden />
      <header className="flex items-center justify-between gap-3 px-5 pt-4 pb-2">
        <h2 className="flex items-center gap-2.5 text-lg font-bold">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-accent-soft text-accent ring-1 ring-accent/40" aria-hidden>
            <Icon name="hand" className="h-4.5 w-4.5" />
          </span>
          <span className="grad-text-signer">Deaf user</span>
        </h2>
        <span className="label">sees signs &amp; captions</span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 pb-5">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
          <Avatar
            sequence={avatarSeq}
            mode={settings.avatarMode}
            speed={settings.avatarSpeed}
            autoPlay={settings.autoPlayAvatar}
          />

          {/* big caption of what the hearing person said */}
          <div className="screen flex flex-col p-4" aria-live="polite">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="label flex items-center gap-2">
                They said
                <Wave live={!!speakerPartial} bars={10} className="h-3.5 text-speaker" />
              </span>
              {lastSpeaker && !speakerPartial && <ToneTag emotion={lastSpeaker.emotion} size="lg" />}
            </div>
            {speakerPartial ? (
              <p className="font-display text-xl leading-snug text-muted italic">{speakerPartial}…</p>
            ) : lastSpeaker ? (
              <>
                <p className="font-display text-2xl leading-snug font-semibold lg:text-[1.75rem]">
                  <Words key={lastSpeaker.id} text={lastSpeaker.sentence || lastSpeaker.content} />
                  {lastSpeaker.unclear && (
                    <span
                      className="ml-2 inline-grid h-8 w-8 place-items-center rounded-full bg-speaker align-middle text-lg font-black text-speaker-ink"
                      title="Unclear speech"
                    >
                      ?
                    </span>
                  )}
                </p>
                {lastSpeaker.content !== lastSpeaker.sentence && (
                  <p className="mt-1.5 text-base text-muted">{lastSpeaker.content}</p>
                )}
                {lastSpeaker.unclear && (
                  <button className="btn mt-3 self-start" onClick={() => send({ cmd: 'quick_reply', id: 'repeat' })}>
                    🔁 Ask them to repeat
                  </button>
                )}
              </>
            ) : (
              <p className="my-auto text-muted">Waiting for the hearing person…</p>
            )}
          </div>
        </div>

        {/* smart quick replies: always visible, they're the fastest way to answer */}
        {suggestions.length > 0 && (
          <div>
            <div className="label mb-2">Quick replies</div>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s, i) => (
                <button
                  key={s.id}
                  className="chip msg-in !border-accent/45 text-[0.95rem]"
                  style={{ animationDelay: `${i * 70}ms` }}
                  onClick={() => send({ cmd: 'quick_reply', id: s.id })}
                  title={s.text !== s.text_en ? s.text : undefined}
                >
                  {s.text_en || s.text}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* reply mode */}
        <div className="mt-auto">
          <div className="mb-2.5 flex items-center justify-between">
            <span className="label">Reply by</span>
            <div role="tablist" className="seg seg-signer">
              {MODES.map((m) => (
                <button
                  key={m.id}
                  role="tab"
                  aria-selected={mode === m.id}
                  onClick={() => setMode(m.id)}
                  className="inline-flex items-center gap-1.5"
                >
                  <Icon name={m.icon} className="h-3.5 w-3.5" /> {m.label}
                </button>
              ))}
            </div>
          </div>

          {mode === 'sign' && (
            <div className="flex flex-col gap-2.5">
              {settings.showCamera && (
                <div className="relative aspect-video overflow-hidden rounded-2xl border border-line bg-sunken">
                  {signConnected && !camFailed ? (
                    <img
                      src={`${settings.signUrl.replace(/\/$/, '')}/video_feed`}
                      alt="Camera preview with hand tracking"
                      className="h-full w-full object-contain"
                      onError={() => {
                        setCamFailed(true)
                        setTimeout(() => setCamFailed(false), 5000) // try again later
                      }}
                    />
                  ) : (
                    <div className="grid h-full place-items-center px-6 text-center text-sm text-muted">
                      {signConnected
                        ? `No camera preview from ${settings.signUrl}/video_feed (mock mode or camera off).`
                        : 'Camera service (sign_service, port 8001) is not connected.'}
                    </div>
                  )}
                  <SigningBadge status={signing.status} paused={paused} />
                </div>
              )}
              <div
                className={`flex min-h-[2.9rem] items-center gap-3 rounded-xl border border-dashed px-3 py-2 transition-colors ${
                  signing.partial ? 'border-accent bg-accent-soft' : 'border-line-strong'
                }`}
              >
                <Wave live={!!signing.partial} bars={8} className="h-5 shrink-0 text-accent" />
                {signing.partial ? (
                  <span>
                    <span className="text-muted">signing </span>
                    <b className="font-mono text-lg tracking-wide text-accent">{signing.partial}…</b>
                  </span>
                ) : (
                  <span className="text-sm text-muted">
                    Sign with your hands in view. Drop your hands for a moment between signs.
                  </span>
                )}
              </div>
              <div className="grid grid-cols-[1fr_auto_auto] gap-2">
                <button className="btn btn-accent !py-3 text-base" onClick={() => send({ cmd: 'flush' })}>
                  ✅ Send signs
                </button>
                <button className="btn" onClick={() => send({ cmd: 'reset' })} title="Clear the signs so far">
                  ✖ Clear
                </button>
                <button
                  className="btn"
                  onClick={() => {
                    send({ cmd: paused ? 'resume' : 'pause' })
                    setPaused(!paused)
                  }}
                >
                  {paused ? '▶ Resume' : '⏸ Pause'}
                </button>
              </div>
            </div>
          )}

          {mode === 'tap' && (
            <PhraseBoard
              quick={quick}
              custom={custom}
              onQuick={(id) => send({ cmd: 'quick_reply', id })}
              onCustom={(p) => onLocalSay(p.text, 'custom', p.emotion)}
              onSaveCustom={onSaveCustom}
            />
          )}

          {mode === 'type' && (
            <form onSubmit={submitTyped} className="flex flex-col gap-2">
              <textarea
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) submitTyped(e)
                }}
                rows={3}
                placeholder="Type a message. It will be spoken aloud."
                className="field resize-none p-3 text-lg"
              />
              <button className="btn btn-accent !py-2.5" disabled={!typed.trim()}>
                <Icon name="volume" /> Speak it
              </button>
            </form>
          )}
        </div>
      </div>
    </section>
  )
}

function SigningBadge({ status, paused }) {
  const s = paused
    ? ['⏸ paused', 'bg-raised text-muted border-line-strong']
    : status === 'signing'
      ? ['● signing', 'bg-accent text-accent-ink border-accent shadow-[0_0_14px_var(--accent-glow)]']
      : status === 'camera_error'
        ? ['camera error', 'bg-danger text-white border-danger']
        : ['ready', 'bg-black/60 text-ink border-line-strong']
  return (
    <span
      className={`absolute top-2.5 left-2.5 rounded-full border px-2.5 py-0.5 font-mono text-[0.7rem] font-semibold tracking-wide backdrop-blur ${s[1]}`}
    >
      {s[0]}
    </span>
  )
}

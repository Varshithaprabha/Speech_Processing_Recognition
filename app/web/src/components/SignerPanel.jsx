import { useState } from 'react'
import Avatar from './Avatar'
import PhraseBoard from './PhraseBoard'
import ToneTag from './ToneTag'

const MODES = [
  { id: 'sign', label: 'Sign', icon: '✋' },
  { id: 'tap', label: 'Tap', icon: '👆' },
  { id: 'type', label: 'Type', icon: '⌨️' },
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
    <section className="panel flex min-h-0 flex-1 flex-col overflow-hidden" aria-label="Deaf user">
      <header className="flex items-center justify-between border-b border-line bg-accent-soft px-4 py-2.5">
        <h2 className="flex items-center gap-2 font-bold">
          <span aria-hidden>🧏</span> Deaf user
        </h2>
        <span className="text-xs text-muted">sees signs &amp; captions</span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
        <Avatar
          sequence={avatarSeq}
          mode={settings.avatarMode}
          speed={settings.avatarSpeed}
          autoPlay={settings.autoPlayAvatar}
        />

        {/* big caption of what the hearing person said */}
        <div className="rounded-xl border border-line bg-sunken p-3" aria-live="polite">
          <div className="mb-1 flex items-center justify-between">
            <span className="label">They said</span>
            {lastSpeaker && <ToneTag emotion={lastSpeaker.emotion} size="lg" />}
          </div>
          {speakerPartial ? (
            <p className="text-xl leading-snug text-muted italic">{speakerPartial}…</p>
          ) : lastSpeaker ? (
            <>
              <p className="text-2xl leading-snug font-semibold">
                {lastSpeaker.sentence || lastSpeaker.content}
                {lastSpeaker.unclear && (
                  <span className="ml-2 rounded-full bg-amber-300 px-2.5 text-xl font-black text-black">?</span>
                )}
              </p>
              {lastSpeaker.content !== lastSpeaker.sentence && (
                <p className="mt-1 text-base text-muted">{lastSpeaker.content}</p>
              )}
              {lastSpeaker.unclear && (
                <button className="btn mt-2" onClick={() => send({ cmd: 'quick_reply', id: 'repeat' })}>
                  🔁 Ask them to repeat
                </button>
              )}
            </>
          ) : (
            <p className="text-muted">Waiting for the hearing person…</p>
          )}
        </div>

        {/* smart quick replies: always visible, they're the fastest way to answer */}
        {suggestions.length > 0 && (
          <div>
            <div className="label mb-1.5">Quick replies</div>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <button
                  key={s.id}
                  className="chip !border-accent/50 !bg-accent-soft text-[0.95rem]"
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
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="label">Reply by</span>
            <div role="tablist" className="flex rounded-xl border border-line bg-sunken p-0.5">
              {MODES.map((m) => (
                <button
                  key={m.id}
                  role="tab"
                  aria-selected={mode === m.id}
                  onClick={() => setMode(m.id)}
                  className={`rounded-lg px-3 py-1 text-sm font-semibold ${
                    mode === m.id ? 'bg-accent text-accent-ink' : 'text-muted hover:text-ink'
                  }`}
                >
                  <span aria-hidden>{m.icon}</span> {m.label}
                </button>
              ))}
            </div>
          </div>

          {mode === 'sign' && (
            <div className="flex flex-col gap-2">
              {settings.showCamera && (
                <div className="relative aspect-video overflow-hidden rounded-xl bg-slate-900">
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
                    <div className="grid h-full place-items-center px-6 text-center text-sm text-slate-400">
                      {signConnected
                        ? `No camera preview from ${settings.signUrl}/video_feed (mock mode or camera off).`
                        : 'Camera service (sign_service, port 8001) is not connected.'}
                    </div>
                  )}
                  <SigningBadge status={signing.status} paused={paused} />
                </div>
              )}
              <div className="min-h-[2.75rem] rounded-xl border border-dashed border-accent/60 px-3 py-2">
                {signing.partial ? (
                  <span>
                    <span className="text-muted">signing: </span>
                    <b className="text-lg tracking-wide">{signing.partial}…</b>
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
                className="w-full resize-none rounded-xl border border-line bg-surface p-3 text-lg"
              />
              <button className="btn btn-accent !py-2.5" disabled={!typed.trim()}>
                🔊 Speak it
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
    ? ['⏸ paused', 'bg-slate-600']
    : status === 'signing'
      ? ['● signing', 'bg-emerald-600']
      : status === 'camera_error'
        ? ['camera error', 'bg-red-600']
        : ['ready', 'bg-slate-700/80']
  return (
    <span className={`absolute top-2 left-2 rounded-full px-2.5 py-0.5 text-xs font-bold text-white ${s[1]}`}>
      {s[0]}
    </span>
  )
}

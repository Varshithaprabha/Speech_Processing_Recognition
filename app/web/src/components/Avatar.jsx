import { useEffect, useRef, useState } from 'react'
import { clipUrl } from '../lib/api'

/**
 * Signing avatar: plays an ISL gloss sequence as one clip per sign (sign_service/clips).
 *   video    - the INCLUDE reference clip of each sign
 *   skeleton - a 2-D figure drawn from the clip's landmark JSON (pose + both hands, 15 fps)
 * `sequence` = {id, clips: [{gloss, video, landmarks}]}; a new id starts it from the first sign.
 */
export default function Avatar({ sequence, mode = 'video', speed = 1, autoPlay = true, compact = false }) {
  const clips = sequence?.clips || []
  const [idx, setIdx] = useState(-1) // -1 = idle
  const [run, setRun] = useState(0) // bump to restart the same clip

  useEffect(() => {
    setIdx(autoPlay && clips.length ? 0 : -1)
    setRun((r) => r + 1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequence?.id])

  const next = () => setIdx((i) => (i + 1 < clips.length ? i + 1 : -1))
  const play = (from = 0) => {
    setIdx(from)
    setRun((r) => r + 1)
  }
  const current = idx >= 0 ? clips[idx] : null
  const lastShown = current || clips[clips.length - 1]

  return (
    <div className="flex flex-col gap-2">
      <div
        className={`relative overflow-hidden rounded-2xl border bg-sunken transition-shadow ${
          current ? 'border-accent/60 shadow-[0_0_28px_-6px_var(--accent-glow)]' : 'border-line'
        } ${compact ? 'aspect-video' : 'aspect-[4/3]'}`}
        aria-label={current ? `Avatar signing ${current.gloss}` : 'Signing avatar'}
      >
        {current ? (
          mode === 'skeleton' && current.landmarks ? (
            <Skeleton key={`${run}-${idx}`} file={current.landmarks} speed={speed} onEnd={next} />
          ) : (
            <ClipVideo key={`${run}-${idx}`} file={current.video} speed={speed} onEnd={next} />
          )
        ) : (
          <div className="absolute inset-0 grid place-items-center text-center text-muted">
            <div>
              <div className="text-5xl opacity-80 grayscale-[30%]" aria-hidden>
                🧏
              </div>
              <div className="mt-2 text-sm">
                {clips.length ? 'Tap ▶ to sign again' : 'Signs for the hearing person’s words appear here'}
              </div>
            </div>
          </div>
        )}
        {current && (
          <div key={`${run}-${idx}`} className="msg-in absolute bottom-3 left-1/2 -translate-x-1/2 rounded-lg border border-accent/50 bg-black/70 px-3 py-1 font-mono text-lg font-semibold tracking-wider text-accent backdrop-blur">
            {current.gloss}
          </div>
        )}
      </div>
      {clips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <button className="btn !px-2.5 !py-1" onClick={() => play(0)} title="Play all signs again">
            ▶ <span className="sr-only">Replay</span>
          </button>
          {clips.map((c, i) => (
            <button
              key={i}
              onClick={() => play(i)}
              className={`rounded-md border px-2 py-0.5 font-mono text-[0.7rem] font-semibold tracking-wide transition ${
                i === idx
                  ? 'border-accent bg-accent text-accent-ink shadow-[0_0_12px_var(--accent-glow)]'
                  : 'border-line-strong bg-sunken text-ink hover:border-accent'
              }`}
            >
              {c.gloss}
            </button>
          ))}
          {!current && lastShown && <span className="ml-auto text-xs text-muted">{clips.length} signs</span>}
        </div>
      )}
    </div>
  )
}

function ClipVideo({ file, speed, onEnd }) {
  const ref = useRef(null)
  const endRef = useRef(onEnd)
  endRef.current = onEnd
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (!failed) return
    const t = setTimeout(() => endRef.current(), 1200 / speed) // no clip: show the word briefly, move on
    return () => clearTimeout(t)
  }, [failed, speed])
  return failed ? (
    <div className="absolute inset-0 grid place-items-center text-muted">clip unavailable</div>
  ) : (
    <video
      ref={ref}
      className="absolute inset-0 h-full w-full object-contain"
      src={clipUrl(file)}
      autoPlay
      muted
      playsInline
      onLoadedMetadata={() => ref.current && (ref.current.playbackRate = speed)}
      onEnded={onEnd}
      onError={() => setFailed(true)}
    />
  )
}

/* ------------------------------------------------------------------ 2-D skeleton avatar */
const HAND = [
  [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17],
]
const cache = new Map()
const loadLandmarks = (file) => {
  if (!cache.has(file)) cache.set(file, fetch(clipUrl(file)).then((r) => (r.ok ? r.json() : null)).catch(() => null))
  return cache.get(file)
}

function Skeleton({ file, speed, onEnd: onEndProp }) {
  const canvas = useRef(null)
  const endRef = useRef(onEndProp)
  endRef.current = onEndProp
  useEffect(() => {
    const onEnd = () => endRef.current()
    let raf = 0
    let alive = true
    loadLandmarks(file).then((data) => {
      if (!alive) return
      if (!data?.frames?.length) return void setTimeout(onEnd, 800)
      const cv = canvas.current
      const ctx = cv.getContext('2d')
      const fps = (data.fps || 15) * speed
      const t0 = performance.now()
      const last = { pose: null, left: null, right: null }
      const draw = (now) => {
        if (!alive) return
        const i = Math.floor(((now - t0) / 1000) * fps)
        if (i >= data.frames.length) return onEnd()
        const f = data.frames[i]
        for (const k of ['pose', 'left', 'right']) if (f[k]) last[k] = f[k]
        paint(ctx, cv, data.aspect || 16 / 9, last)
        raf = requestAnimationFrame(draw)
      }
      raf = requestAnimationFrame(draw)
    })
    return () => {
      alive = false
      cancelAnimationFrame(raf)
    }
  }, [file, speed])
  return <canvas ref={canvas} width={640} height={480} className="absolute inset-0 h-full w-full" />
}

function paint(ctx, cv, aspect, { pose, left, right }) {
  const W = cv.width
  const H = cv.height
  ctx.fillStyle = '#0c1210'
  ctx.fillRect(0, 0, W, H)
  if (!pose) return
  // fit the clip frame (aspect) into the canvas, centred on the shoulders
  const fh = H * 1.25
  const fw = fh * aspect
  const sc = (W * 0.38) / Math.max(0.12, Math.abs(pose[11][0] - pose[12][0]) * fw) // shoulders ≈ half width
  const s = Math.min(sc, 3)
  const cx = ((pose[11][0] + pose[12][0]) / 2) * fw
  const cy = ((pose[11][1] + pose[12][1]) / 2) * fh
  const P = ([x, y]) => [(x * fw - cx) * s + W / 2, (y * fh - cy) * s + H * 0.52]
  const sw = Math.hypot(...[0, 1].map((k) => P(pose[11])[k] - P(pose[12])[k]))

  const line = (a, b, w, c) => {
    ctx.strokeStyle = c
    ctx.lineWidth = w
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(...a)
    ctx.lineTo(...b)
    ctx.stroke()
  }
  const [ls, rs] = [P(pose[11]), P(pose[12])]
  // torso
  ctx.fillStyle = '#22302b'
  ctx.beginPath()
  ctx.moveTo(ls[0] + sw * 0.08, ls[1])
  ctx.lineTo(rs[0] - sw * 0.08, rs[1])
  ctx.lineTo(rs[0] + sw * 0.05, H + 10)
  ctx.lineTo(ls[0] - sw * 0.05, H + 10)
  ctx.closePath()
  ctx.fill()
  // neck + head
  const nose = P(pose[0])
  const mid = [(ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2]
  line(mid, [nose[0], nose[1] + sw * 0.25], sw * 0.18, '#e2b48f')
  ctx.fillStyle = '#f1c7a3'
  ctx.beginPath()
  ctx.ellipse(nose[0], nose[1] - sw * 0.05, sw * 0.27, sw * 0.33, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = '#0c1210'
  for (const e of [2, 5]) {
    const p = P(pose[e])
    ctx.beginPath()
    ctx.arc(p[0], p[1], sw * 0.025, 0, Math.PI * 2)
    ctx.fill()
  }
  const m1 = P(pose[9])
  const m2 = P(pose[10])
  line(m1, m2, sw * 0.02, '#9a3412')
  // arms
  const arm = sw * 0.13
  for (const [a, b, c] of [[11, 13, 15], [12, 14, 16]]) {
    line(P(pose[a]), P(pose[b]), arm, '#2f4139')
    line(P(pose[b]), P(pose[c]), arm * 0.85, '#e2b48f')
  }
  // hands: detailed when tracked, else a simple palm at the wrist
  for (const [hand, wrist, col] of [[left, 15, '#3fe0a5'], [right, 16, '#ffb547']]) {
    if (hand) {
      const pts = hand.map(P)
      for (const [a, b] of HAND) line(pts[a], pts[b], sw * 0.035, col)
      ctx.fillStyle = '#ffffff'
      for (const p of pts) {
        ctx.beginPath()
        ctx.arc(p[0], p[1], sw * 0.018, 0, Math.PI * 2)
        ctx.fill()
      }
    } else {
      const w = P(pose[wrist])
      ctx.fillStyle = col
      ctx.beginPath()
      ctx.arc(w[0], w[1], sw * 0.08, 0, Math.PI * 2)
      ctx.fill()
    }
  }
}

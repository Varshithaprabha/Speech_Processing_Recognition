// A caption that appears word by word (blur + rise). Give it a `key` that changes with each new
// message so the animation replays. Screen readers get the whole text at once.
export default function Words({ text = '', step = 55, className = '' }) {
  const words = String(text).split(/(\s+)/)
  let n = 0
  return (
    <span className={className} aria-label={text}>
      {words.map((w, i) =>
        /^\s+$/.test(w) ? (
          w
        ) : (
          <span key={i} className="word" style={{ animationDelay: `${Math.min(n++ * step, 1400)}ms` }} aria-hidden>
            {w}
          </span>
        ),
      )}
    </span>
  )
}

// Animated waveform bars (CSS only). `live` = someone is speaking / signing / the voice is playing;
// otherwise a gentle idle ripple. Colour comes from `currentColor`, so set it with a text-* class.
const SHAPE = [0.35, 0.6, 0.9, 0.55, 1, 0.7, 0.45, 0.85, 0.5, 0.75, 0.4, 0.65, 0.95, 0.5, 0.3, 0.6]

export default function Wave({ live = false, bars = 12, className = 'h-5', label }) {
  return (
    <span className={`wave ${live ? 'live' : ''} ${className}`} role={label ? 'img' : undefined} aria-label={label}
      aria-hidden={label ? undefined : true}>
      {Array.from({ length: bars }, (_, i) => (
        <i
          key={i}
          style={{
            animationDelay: `${(i * 0.11) % 0.9}s`,
            animationDuration: live ? `${0.7 + SHAPE.at(i % SHAPE.length) * 0.5}s` : undefined,
            height: `${40 + SHAPE.at(i % SHAPE.length) * 60}%`,
          }}
        />
      ))}
    </span>
  )
}

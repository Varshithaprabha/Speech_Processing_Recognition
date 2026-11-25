// Tone tag shown on captions (section 3, enhancement 5). Colour + emoji + word, never colour alone.
// Colours come from the theme (index.css: .tone-*); "urgent" also pulses.
export const TONES = {
  neutral: { emoji: '💬', label: 'Neutral' },
  happy: { emoji: '😊', label: 'Happy' },
  angry: { emoji: '😠', label: 'Angry' },
  urgent: { emoji: '⚠️', label: 'Urgent' },
  question: { emoji: '❓', label: 'Question' },
}

export default function ToneTag({ emotion = 'neutral', size = 'sm', hideNeutral = false }) {
  const key = TONES[emotion] ? emotion : 'neutral'
  const t = TONES[key]
  if (hideNeutral && key === 'neutral') return null
  const big = size === 'lg'
  return (
    <span
      className={`tone tone-${key} inline-flex items-center gap-1 rounded-full border font-semibold ${
        big ? 'px-3 py-1 text-sm' : 'px-2 py-0.5 text-xs'
      }`}
      title={`Tone: ${t.label}`}
    >
      <span aria-hidden>{t.emoji}</span>
      {t.label}
    </span>
  )
}

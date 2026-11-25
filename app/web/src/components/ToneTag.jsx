// Tone tag shown on captions (section 3, enhancement 5). Colour + emoji + word, never colour alone.
export const TONES = {
  neutral: { emoji: '💬', label: 'Neutral', cls: 'bg-slate-100 text-slate-700 border-slate-300' },
  happy: { emoji: '😊', label: 'Happy', cls: 'bg-emerald-100 text-emerald-800 border-emerald-300' },
  angry: { emoji: '😠', label: 'Angry', cls: 'bg-rose-100 text-rose-800 border-rose-300' },
  urgent: { emoji: '⚠️', label: 'Urgent', cls: 'bg-orange-100 text-orange-900 border-orange-400' },
  question: { emoji: '❓', label: 'Question', cls: 'bg-sky-100 text-sky-800 border-sky-300' },
}

export default function ToneTag({ emotion = 'neutral', size = 'sm', hideNeutral = false }) {
  const t = TONES[emotion] || TONES.neutral
  if (hideNeutral && emotion === 'neutral') return null
  const big = size === 'lg'
  return (
    <span
      className={`tone inline-flex items-center gap-1 rounded-full border font-semibold ${t.cls} ${
        big ? 'px-3 py-1 text-sm' : 'px-2 py-0.5 text-xs'
      }`}
      title={`Tone: ${t.label}`}
    >
      <span aria-hidden>{t.emoji}</span>
      {t.label}
    </span>
  )
}

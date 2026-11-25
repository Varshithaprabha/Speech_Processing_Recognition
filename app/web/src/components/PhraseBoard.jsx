import { useState } from 'react'

const EMO_ICON = { urgent: '⚠️', question: '❓', happy: '😊', angry: '😠', neutral: '' }

/** Phrase board: speech_service's built-in phrases (translated by Part B) + the user's own phrases. */
export default function PhraseBoard({ quick, custom, onQuick, onCustom, onSaveCustom }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState([])
  const [text, setText] = useState('')
  const [emotion, setEmotion] = useState('neutral')

  const startEdit = () => {
    setDraft(custom)
    setEditing(true)
  }
  const add = (e) => {
    e.preventDefault()
    if (!text.trim()) return
    setDraft([...draft, { id: `c_${Date.now().toString(36)}`, text: text.trim(), emotion }])
    setText('')
    setEmotion('neutral')
  }

  if (editing) {
    return (
      <div className="flex flex-col gap-2 rounded-xl border border-line bg-sunken p-3">
        <div className="label">My phrases</div>
        {draft.length === 0 && <p className="text-sm text-muted">No phrases yet.</p>}
        <ul className="flex flex-col gap-1.5">
          {draft.map((p, i) => (
            <li key={p.id} className="flex items-center gap-2 rounded-lg bg-raised px-2 py-1.5">
              <span className="flex-1">
                {EMO_ICON[p.emotion]} {p.text}
              </span>
              <button
                className="btn !px-2 !py-0.5 text-xs"
                disabled={i === 0}
                onClick={() => setDraft(move(draft, i, i - 1))}
                aria-label="Move up"
              >
                ↑
              </button>
              <button
                className="btn !px-2 !py-0.5 text-xs"
                onClick={() => setDraft(draft.filter((_, k) => k !== i))}
                aria-label={`Remove ${p.text}`}
              >
                🗑
              </button>
            </li>
          ))}
        </ul>
        <form onSubmit={add} className="flex flex-wrap gap-2">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="New phrase, e.g. I am allergic to penicillin."
            className="field min-w-0 flex-1 !rounded-lg px-3 py-2"
          />
          <select
            value={emotion}
            onChange={(e) => setEmotion(e.target.value)}
            className="field !w-auto !rounded-lg px-2"
            aria-label="Tone"
          >
            <option value="neutral">Neutral</option>
            <option value="question">Question</option>
            <option value="urgent">Urgent</option>
            <option value="happy">Happy</option>
          </select>
          <button className="btn">＋ Add</button>
        </form>
        <div className="flex justify-end gap-2">
          <button className="btn" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button
            className="btn btn-accent"
            onClick={async () => {
              await onSaveCustom(draft)
              setEditing(false)
            }}
          >
            Save phrases
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {quick.map((q) => (
          <button
            key={q.id}
            onClick={() => onQuick(q.id)}
            className={`rounded-xl border px-3 py-3 text-left font-semibold leading-tight transition hover:-translate-y-0.5 hover:border-accent hover:bg-accent-soft hover:shadow-[0_0_16px_var(--accent-glow)] ${
              q.emotion === 'urgent' ? 'tone tone-urgent !animate-none' : 'border-line-strong bg-raised text-ink'
            }`}
          >
            {EMO_ICON[q.emotion] && <span aria-hidden>{EMO_ICON[q.emotion]} </span>}
            {q.text}
          </button>
        ))}
      </div>
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="label">My phrases</span>
          <button className="text-sm font-semibold text-accent hover:underline" onClick={startEdit}>
            ✏️ Edit
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {custom.map((p) => (
            <button key={p.id} className="chip" onClick={() => onCustom(p)}>
              {EMO_ICON[p.emotion] && <span aria-hidden>{EMO_ICON[p.emotion]} </span>}
              {p.text}
            </button>
          ))}
          {custom.length === 0 && <span className="text-sm text-muted">Add your own phrases with Edit.</span>}
        </div>
      </div>
    </div>
  )
}

function move(list, from, to) {
  const a = [...list]
  const [x] = a.splice(from, 1)
  a.splice(to, 0, x)
  return a
}

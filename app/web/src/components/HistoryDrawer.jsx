import { useEffect, useState } from 'react'
import { api, clipIndex, download, printConversation, toText } from '../lib/api'
import Avatar from './Avatar'
import Drawer from './Drawer'
import ToneTag from './ToneTag'

/** Saved conversations: summary, transcript, export, and the signs used (learn-as-you-talk). */
export default function HistoryDrawer({ onClose, open: initial, settings }) {
  const [list, setList] = useState(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(initial || null)

  const load = () =>
    api
      .history()
      .then(setList)
      .catch(() => setError('Could not reach the app backend (python server.py).'))
  useEffect(() => {
    load()
  }, [])

  const view = async (id) => {
    try {
      setOpen(await api.conversation(id))
    } catch {
      setError('Could not load that conversation.')
    }
  }

  if (open) {
    return (
      <Drawer title="Conversation" onClose={onClose} wide>
        <button className="btn no-print mb-4" onClick={() => setOpen(null)}>
          ← All conversations
        </button>
        <ConversationView conv={open} settings={settings} onDeleted={() => (setOpen(null), load())} />
      </Drawer>
    )
  }

  return (
    <Drawer title="History" onClose={onClose}>
      {error && <p className="mb-3 rounded-lg bg-danger-soft p-3 text-sm text-danger">{error}</p>}
      {list === null && !error && <p className="text-muted">Loading…</p>}
      {list?.length === 0 && (
        <p className="text-muted">No saved conversations yet. Use “End &amp; save” to keep one with its summary.</p>
      )}
      <ul className="flex flex-col gap-2">
        {list?.map((c) => (
          <li key={c.id}>
            <button
              onClick={() => view(c.id)}
              className="w-full rounded-xl border border-line p-3 text-left hover:border-accent hover:bg-accent-soft"
            >
              <div className="font-semibold">{c.title}</div>
              <div className="text-xs text-muted">
                {new Date(c.created_at).toLocaleString()} · {c.messages} messages
              </div>
              {c.summary && <div className="mt-1 line-clamp-2 text-sm text-muted">{c.summary}</div>}
            </button>
          </li>
        ))}
      </ul>
    </Drawer>
  )
}

export function ConversationView({ conv, settings, onDeleted }) {
  const [index, setIndex] = useState({})
  const [practice, setPractice] = useState(null)
  useEffect(() => {
    clipIndex().then(setIndex)
  }, [])
  const signs = (conv.signs || []).filter((g) => index[g]).slice(0, 5)
  const base = conv.title.replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '_') || 'conversation'

  return (
    <article className="flex flex-col gap-5">
      <div>
        <h3 className="text-xl font-bold">{conv.title}</h3>
        <div className="text-sm text-muted">{new Date(conv.created_at).toLocaleString()}</div>
      </div>

      <section className="rounded-xl border border-accent/40 bg-accent-soft p-4">
        <div className="label mb-1">Summary</div>
        <p className="leading-relaxed">{conv.summary || 'No summary (the speech service was not reachable).'}</p>
        {conv.key_points?.length > 0 && (
          <ul className="mt-2 list-disc pl-5">
            {conv.key_points.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        )}
      </section>

      <div className="no-print flex flex-wrap gap-2">
        <button className="btn" onClick={() => download(`${base}.txt`, toText(conv))}>
          ⬇ Text
        </button>
        <button
          className="btn"
          onClick={() => download(`${base}.json`, JSON.stringify(conv, null, 2), 'application/json')}
        >
          ⬇ JSON
        </button>
        <button className="btn" onClick={() => printConversation(conv)}>
          🖨 Print / PDF
        </button>
        {onDeleted && (
          <button
            className="btn ml-auto text-danger"
            onClick={async () => {
              if (confirm('Delete this conversation? This cannot be undone.')) {
                await api.remove(conv.id)
                onDeleted()
              }
            }}
          >
            🗑 Delete
          </button>
        )}
      </div>

      {signs.length > 0 && (
        <section className="no-print">
          <div className="label mb-1">Learn as you talk: signs used most</div>
          <p className="mb-2 text-sm text-muted">Tap a sign to watch it, then try it yourself.</p>
          <div className="mb-3 flex flex-wrap gap-2">
            {signs.map((g) => (
              <button
                key={g}
                className={`chip font-bold tracking-wide ${practice?.gloss === g ? '!border-accent !bg-accent !text-accent-ink' : ''}`}
                onClick={() => setPractice({ gloss: g, id: Date.now() })}
              >
                {g}
              </button>
            ))}
          </div>
          {practice && (
            <div className="max-w-sm">
              <Avatar
                sequence={{ id: practice.id, clips: [{ gloss: practice.gloss, ...index[practice.gloss] }] }}
                mode={settings.avatarMode}
                speed={0.75}
                compact
              />
            </div>
          )}
        </section>
      )}

      <section>
        <div className="label mb-2">Transcript</div>
        <ol className="flex flex-col gap-2">
          {(conv.transcript || []).map((m, i) => (
            <li key={i} className="rounded-lg border border-line p-2.5">
              <div className="flex items-center gap-2 text-xs text-muted">
                <b className={m.from === 'signer' ? 'text-accent' : 'text-speaker'}>
                  {m.from === 'signer' ? 'Deaf user' : 'Hearing person'}
                </b>
                <span>{m.timestamp ? new Date(m.timestamp).toLocaleTimeString() : ''}</span>
                <ToneTag emotion={m.emotion} hideNeutral />
              </div>
              <div className="mt-0.5">{m.text}</div>
              {m.original && m.original !== m.text && <div className="text-sm text-muted">{m.original}</div>}
            </li>
          ))}
        </ol>
      </section>
    </article>
  )
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import HistoryDrawer from './components/HistoryDrawer'
import SettingsDrawer from './components/SettingsDrawer'
import SignerPanel from './components/SignerPanel'
import SosOverlay from './components/SosOverlay'
import SpeakerPanel from './components/SpeakerPanel'
import Timeline from './components/Timeline'
import { api, download, quickReplies, toText } from './lib/api'
import { useBridge, useHealth } from './lib/bridge'
import { useSettings } from './lib/settings'
import { speak, stopSpeaking, vibrate } from './lib/voice'

let nextId = 1
const stamp = (m) => ({ ...m, id: nextId++, timestamp: m.timestamp || new Date().toISOString() })
const ALERT_TONES = new Set(['urgent', 'angry'])

/** Most-used signs in a conversation (learn-as-you-talk). */
function topSigns(items) {
  const n = {}
  for (const m of items) {
    const g = m.from === 'speaker' ? (m.clips || []).map((c) => c.gloss) : m.type === 'gloss' ? m.content.split(/\s+/) : []
    for (const x of g) if (x) n[x] = (n[x] || 0) + 1
  }
  return Object.entries(n)
    .sort((a, b) => b[1] - a[1])
    .map(([g]) => g)
}

const forExport = (m) => ({
  from: m.from,
  type: m.type,
  text: m.from === 'signer' ? m.sentence_en || m.sentence || m.content : m.sentence || m.content,
  original: m.type === 'gloss' ? m.content : m.from === 'speaker' ? m.content : m.sentence,
  emotion: m.emotion,
  language: m.language,
  timestamp: m.timestamp,
  ...(m.gloss ? { gloss: m.gloss } : {}),
})

export default function App() {
  const [settings, update, resetSettings] = useSettings()
  const [items, setItems] = useState([])
  const [speakerPartial, setSpeakerPartial] = useState('')
  const [signing, setSigning] = useState({ status: 'idle', partial: '' })
  const [suggestions, setSuggestions] = useState([])
  const [avatarSeq, setAvatarSeq] = useState(null)
  const [sos, setSos] = useState(null)
  const [flashKey, setFlashKey] = useState(0)
  const [drawer, setDrawer] = useState(null) // settings | history
  const [savedConv, setSavedConv] = useState(null)
  const [saving, setSaving] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [toast, setToast] = useState(null)
  const [quick, setQuick] = useState([])
  const [custom, setCustom] = useState([])
  const [mobileTab, setMobileTab] = useState('signer')
  const pendingSave = useRef(null)
  const itemsRef = useRef(items)
  itemsRef.current = items
  const settingsRef = useRef(settings)
  settingsRef.current = settings

  /* ------------------------------------------------------------ accessibility classes on <html> */
  useEffect(() => {
    const h = document.documentElement
    h.classList.toggle('hc', settings.highContrast)
    h.classList.toggle('text-large', settings.textSize === 'large')
    h.classList.toggle('text-xlarge', settings.textSize === 'xlarge')
  }, [settings.highContrast, settings.textSize])

  const notify = useCallback((text, kind = 'info') => {
    setToast({ text, kind, id: Date.now() })
  }, [])
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 4500)
    return () => clearTimeout(t)
  }, [toast])

  const alertUser = useCallback(() => {
    const s = settingsRef.current
    if (s.flashAlerts) setFlashKey((k) => k + 1)
    if (s.vibrate) vibrate([200, 100, 200, 100, 400])
  }, [])

  const say = useCallback((m) => {
    const s = settingsRef.current
    speak(m.sentence || m.content, m.language, m.emotion, {
      voice: s.voice,
      base: s.speechUrl,
      rate: s.voiceRate,
      onStart: () => setSpeaking(true),
      onEnd: () => setSpeaking(false),
    })
  }, [])

  const add = useCallback((m) => {
    const x = stamp(m)
    setItems((list) => [...list.slice(-299), x])
    return x
  }, [])

  /* ------------------------------------------------------------ messages from speech_service (section 6) */
  const onMessage = useCallback(
    (m) => {
      const s = settingsRef.current
      const { from, type } = m
      if (type === 'speech_partial') return setSpeakerPartial(m.sentence || m.content)
      if (type === 'gloss_partial') return setSigning((x) => ({ ...x, partial: m.content }))
      if (from === 'signer' && type === 'status') {
        return setSigning((x) => ({ status: m.content, partial: m.content === 'idle' ? '' : x.partial }))
      }
      if (from === 'speaker' && type === 'text') {
        setSpeakerPartial('')
        const x = add(m)
        if (m.clips?.length) setAvatarSeq({ id: x.id, clips: m.clips })
        if (ALERT_TONES.has(m.emotion)) alertUser()
        return
      }
      if (from === 'signer' && (type === 'gloss' || type === 'text')) {
        setSigning((x) => ({ ...x, partial: '' }))
        add(m)
        if (m.kind === 'suggestion' || m.kind === 'quick_reply') setSuggestions([])
        if (s.autoSpeak) say(m)
        return
      }
      if (type === 'alert') {
        add(m)
        setSos(m)
        alertUser()
        say(m)
        return
      }
      if (type === 'suggestions') return setSuggestions(m.suggestions || [])
      if (type === 'summary') {
        const p = pendingSave.current
        if (p) {
          clearTimeout(p.timer)
          pendingSave.current = null
          p.resolve(m)
        }
        return
      }
      if (from === 'system' && type === 'status' && m.content === 'sign_service_disconnected') {
        notify('Camera service (Part A) disconnected.', 'warn')
      }
    },
    [add, alertUser, notify, say],
  )

  const { status: wsStatus, send } = useBridge(settings.speechUrl, onMessage)
  const health = useHealth(settings.speechUrl)
  const signConnected = !!health?.sign_service

  /* ------------------------------------------------------------ phrase board */
  useEffect(() => {
    quickReplies(settings.speechUrl).then(setQuick)
  }, [settings.speechUrl])
  useEffect(() => {
    api
      .phrases()
      .then(setCustom)
      .catch(() => setCustom(JSON.parse(localStorage.getItem('signbridge.phrases') || '[]')))
  }, [])
  const saveCustom = async (list) => {
    setCustom(list)
    localStorage.setItem('signbridge.phrases', JSON.stringify(list))
    try {
      setCustom(await api.savePhrases(list))
    } catch {
      notify('Saved on this device only (app backend not reachable).', 'warn')
    }
  }

  // phrases the server has no id for (typed text, custom phrases, SOS presets): shown + spoken here
  const localSay = useCallback(
    (text, kind, emotion = 'neutral') => {
      const m = add({ from: 'signer', type: 'text', content: text, sentence: text, sentence_en: text, language: 'en', emotion, kind })
      say(m)
    },
    [add, say],
  )

  const sendOrWarn = useCallback(
    (cmd) => {
      if (!send(cmd)) notify('Not connected to the speech service.', 'warn')
    },
    [send, notify],
  )

  /* ------------------------------------------------------------ end & save (summary + history) */
  const clearConversation = () => {
    send({ cmd: 'new_conversation' })
    setItems([])
    setSuggestions([])
    setAvatarSeq(null)
    setSpeakerPartial('')
    stopSpeaking()
  }

  const endAndSave = async () => {
    if (!itemsRef.current.length) return notify('Nothing to save yet.')
    setSaving(true)
    const summary = await new Promise((resolve) => {
      if (!send({ cmd: 'summary' })) return resolve(null)
      pendingSave.current = { resolve, timer: setTimeout(() => ((pendingSave.current = null), resolve(null)), 20000) }
    })
    const list = itemsRef.current
    const first = list.find((m) => m.from === 'speaker' || m.type === 'gloss')
    const record = {
      title: `Conversation ${new Date().toLocaleDateString()} ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`,
      summary: summary?.content || '',
      key_points: summary?.key_points || [],
      transcript: list.map(forExport),
      language: settings.language,
      signs: topSigns(list),
    }
    if (first) {
      const t = first.sentence_en || first.sentence || first.content
      record.title += ` · ${t.length > 42 ? t.slice(0, 42).replace(/\s+\S*$/, '') + '…' : t}`
    }
    try {
      const saved = await api.save(record)
      clearConversation()
      setSavedConv(saved)
      setDrawer('history')
    } catch {
      notify('Could not save: app backend (python server.py) not reachable. Downloading instead.', 'warn')
      download('signbridge-conversation.txt', toText({ ...record, created_at: new Date().toISOString() }))
    } finally {
      setSaving(false)
    }
  }

  const lastSpeaker = useMemo(() => [...items].reverse().find((m) => m.from === 'speaker'), [items])
  const lastSigner = useMemo(() => [...items].reverse().find((m) => m.from === 'signer'), [items])
  const providers = health?.llm?.providers
  const ai = health?.mock ? 'mock' : Array.isArray(providers) ? providers[0] || 'rules only' : null

  return (
    <div className="flex h-dvh flex-col">
      {flashKey > 0 && <div key={flashKey} className="flash pointer-events-none fixed inset-0 z-[60]" aria-hidden />}
      {/* ------------------------------------------------ header */}
      <header className="no-print flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-2.5">
        <div className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-8 w-8" />
          <div>
            <h1 className="text-lg leading-none font-extrabold">SignBridge</h1>
            <p className="text-xs text-muted">Two-way ISL ↔ speech</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <Pill ok={wsStatus === 'open'} wait={wsStatus === 'connecting'} label="Speech" />
          <Pill ok={signConnected} label="Camera" />
          {ai && <Pill ok label={`AI: ${ai}`} />}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button className="btn" onClick={() => setDrawer('history')}>
            🗂 <span className="hidden sm:inline">History</span>
          </button>
          <button className="btn" onClick={endAndSave} disabled={saving || !items.length}>
            💾 <span className="hidden sm:inline">{saving ? 'Saving…' : 'End & save'}</span>
          </button>
          <button className="btn" onClick={() => setDrawer('settings')} aria-label="Settings">
            ⚙️ <span className="hidden sm:inline">Settings</span>
          </button>
          <button
            className="btn btn-danger !px-5 text-base font-black tracking-wider"
            onClick={() => {
              setSos({ sentence: '' })
              send({ cmd: 'sos' }) || alertUser()
            }}
          >
            🆘 SOS
          </button>
        </div>
      </header>

      {wsStatus !== 'open' && (
        <div className="no-print border-b border-amber-300 bg-amber-50 px-4 py-1.5 text-center text-sm text-amber-900">
          {wsStatus === 'connecting' ? 'Connecting to' : 'Cannot reach'} the speech service at{' '}
          <code className="font-mono">{settings.speechUrl}</code>. Start it (<code>docker compose up -d</code> in
          speech_service) or open <a className="underline" href="?mock">mock mode</a>.
        </div>
      )}

      {/* ------------------------------------------------ mobile tabs */}
      <nav className="flex border-b border-line bg-surface lg:hidden" role="tablist">
        {[
          ['signer', '🧏 Deaf user'],
          ['chat', '💬 Conversation'],
          ['speaker', '🗣️ Hearing'],
        ].map(([id, l]) => (
          <button
            key={id}
            role="tab"
            aria-selected={mobileTab === id}
            onClick={() => setMobileTab(id)}
            className={`flex-1 py-2 text-sm font-semibold ${mobileTab === id ? 'border-b-2 border-accent text-ink' : 'text-muted'}`}
          >
            {l}
          </button>
        ))}
      </nav>

      {/* ------------------------------------------------ split view */}
      <main className="grid min-h-0 flex-1 gap-3 p-3 lg:grid-cols-[minmax(0,1.05fr)_minmax(300px,0.8fr)_minmax(0,1fr)]">
        <div className={`min-h-0 ${mobileTab === 'signer' ? 'flex' : 'hidden'} flex-col lg:flex`}>
          <SignerPanel
            settings={settings}
            avatarSeq={avatarSeq}
            lastSpeaker={lastSpeaker}
            speakerPartial={speakerPartial}
            signing={signing}
            signConnected={signConnected}
            suggestions={suggestions}
            quick={quick}
            custom={custom}
            onSaveCustom={saveCustom}
            send={sendOrWarn}
            onLocalSay={localSay}
          />
        </div>
        <section
          className={`panel min-h-0 flex-col overflow-hidden ${mobileTab === 'chat' ? 'flex' : 'hidden'} lg:flex`}
          aria-label="Conversation"
        >
          <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <h2 className="font-bold">Conversation</h2>
            <span className="text-xs text-muted">{items.length} messages</span>
          </header>
          <Timeline
            items={items}
            speakerPartial={speakerPartial}
            signingPartial={signing.partial}
            onSpeak={say}
            onReplaySigns={(m) => {
              setAvatarSeq({ id: `${m.id}-${Date.now()}`, clips: m.clips })
              setMobileTab('signer')
            }}
          />
        </section>
        <div className={`min-h-0 ${mobileTab === 'speaker' ? 'flex' : 'hidden'} flex-col lg:flex`}>
          <SpeakerPanel
            settings={settings}
            update={update}
            lastSigner={lastSigner}
            signingPartial={signing.partial}
            speaking={speaking}
            send={sendOrWarn}
            onSpeak={say}
            onError={(e) => notify(e, 'warn')}
          />
        </div>
      </main>

      {toast && (
        <div
          key={toast.id}
          role="status"
          className={`fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-xl px-4 py-2.5 font-medium shadow-lg ${
            toast.kind === 'warn' ? 'bg-amber-400 text-black' : 'bg-slate-900 text-white'
          }`}
        >
          {toast.text}
        </div>
      )}

      {sos && (
        <SosOverlay
          alert={sos.sentence ? sos : null}
          flash={settings.flashAlerts}
          onClose={() => setSos(null)}
          onQuick={(id) => sendOrWarn({ cmd: 'quick_reply', id })}
          onSay={(t, e) => localSay(t, 'sos', e)}
        />
      )}
      {drawer === 'settings' && (
        <SettingsDrawer
          settings={settings}
          update={update}
          reset={resetSettings}
          onClose={() => setDrawer(null)}
          onNewConversation={() => {
            if (confirm('Clear the conversation without saving?')) clearConversation()
          }}
        />
      )}
      {drawer === 'history' && (
        <HistoryDrawer
          settings={settings}
          open={savedConv}
          onClose={() => {
            setDrawer(null)
            setSavedConv(null)
          }}
        />
      )}
    </div>
  )
}

function Pill({ ok, wait, label }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-semibold ${
        ok ? 'border-emerald-300 bg-emerald-50 text-emerald-800' : wait ? 'border-amber-300 bg-amber-50 text-amber-900' : 'border-line bg-sunken text-muted'
      }`}
    >
      <span className={`h-2 w-2 rounded-full ${ok ? 'bg-emerald-500' : wait ? 'bg-amber-500' : 'bg-slate-400'}`} />
      {label}
    </span>
  )
}

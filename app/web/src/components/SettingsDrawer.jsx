import { LANGS } from '../lib/settings'
import { speak } from '../lib/voice'
import Drawer from './Drawer'

function Row({ label, hint, children }) {
  return (
    <label className="flex items-center justify-between gap-4 py-2.5">
      <span>
        <span className="font-medium">{label}</span>
        {hint && <span className="block text-xs text-muted">{hint}</span>}
      </span>
      {children}
    </label>
  )
}

const Toggle = ({ value, onChange }) => (
  <input type="checkbox" className="h-5 w-5 accent-[var(--accent)]" checked={value} onChange={(e) => onChange(e.target.checked)} />
)

function Seg({ value, options, onChange }) {
  return (
    <span className="flex rounded-lg border border-line bg-sunken p-0.5">
      {options.map(([v, l]) => (
        <button
          type="button"
          key={v}
          onClick={() => onChange(v)}
          className={`rounded-md px-2.5 py-0.5 text-sm font-semibold ${value === v ? 'bg-accent text-accent-ink' : 'text-muted'}`}
        >
          {l}
        </button>
      ))}
    </span>
  )
}

export default function SettingsDrawer({ settings: s, update, reset, onClose, onNewConversation }) {
  const section = 'mt-5 mb-1 label'
  return (
    <Drawer title="Settings" onClose={onClose}>
      <div className={section.replace('mt-5', 'mt-0')}>Accessibility</div>
      <div className="divide-y divide-line">
        <Row label="Text size">
          <Seg
            value={s.textSize}
            options={[['normal', 'A'], ['large', 'A+'], ['xlarge', 'A++']]}
            onChange={(v) => update({ textSize: v })}
          />
        </Row>
        <Row label="High contrast">
          <Toggle value={s.highContrast} onChange={(v) => update({ highContrast: v })} />
        </Row>
        <Row label="Flash screen on alerts" hint="Urgent or angry speech, SOS">
          <Toggle value={s.flashAlerts} onChange={(v) => update({ flashAlerts: v })} />
        </Row>
        <Row label="Vibrate on alerts" hint="Phones and tablets">
          <Toggle value={s.vibrate} onChange={(v) => update({ vibrate: v })} />
        </Row>
      </div>

      <div className={section}>Signing avatar</div>
      <div className="divide-y divide-line">
        <Row label="Avatar style">
          <Seg
            value={s.avatarMode}
            options={[['video', 'Video'], ['skeleton', 'Figure']]}
            onChange={(v) => update({ avatarMode: v })}
          />
        </Row>
        <Row label={`Avatar speed: ${s.avatarSpeed.toFixed(2)}×`}>
          <input
            type="range"
            min="0.5"
            max="1.5"
            step="0.05"
            value={s.avatarSpeed}
            onChange={(e) => update({ avatarSpeed: Number(e.target.value) })}
          />
        </Row>
        <Row label="Play signs automatically">
          <Toggle value={s.autoPlayAvatar} onChange={(v) => update({ autoPlayAvatar: v })} />
        </Row>
        <Row label="Show camera preview">
          <Toggle value={s.showCamera} onChange={(v) => update({ showCamera: v })} />
        </Row>
      </div>

      <div className={section}>Voice &amp; language</div>
      <div className="divide-y divide-line">
        <Row label="Hearing person's language">
          <select
            className="rounded-lg border border-line bg-surface px-2 py-1"
            value={s.language}
            onChange={(e) => update({ language: e.target.value })}
          >
            {Object.entries(LANGS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.name} ({v.native})
              </option>
            ))}
          </select>
        </Row>
        <Row label="Speech recognition" hint="Browser: Chrome/Edge, instant. Whisper: better for Telugu.">
          <Seg
            value={s.sttEngine}
            options={[['browser', 'Browser'], ['whisper', 'Whisper']]}
            onChange={(v) => update({ sttEngine: v })}
          />
        </Row>
        <Row label="Read signed sentences aloud">
          <Toggle value={s.autoSpeak} onChange={(v) => update({ autoSpeak: v })} />
        </Row>
        <Row label="Voice" hint="Server voice matches the tone (e.g. faster when urgent)">
          <Seg value={s.voice} options={[['server', 'Server'], ['browser', 'Browser']]} onChange={(v) => update({ voice: v })} />
        </Row>
        <Row label={`Voice speed: ${s.voiceRate.toFixed(2)}×`}>
          <input
            type="range"
            min="0.6"
            max="1.6"
            step="0.05"
            value={s.voiceRate}
            onChange={(e) => update({ voiceRate: Number(e.target.value) })}
          />
        </Row>
        <div className="py-2.5">
          <button
            className="btn"
            onClick={() =>
              speak(
                { en: 'This is how I will sound.', hi: 'मेरी आवाज़ ऐसी होगी।', te: 'నా గొంతు ఇలా ఉంటుంది.' }[s.language],
                s.language,
                'neutral',
                { voice: s.voice, base: s.speechUrl, rate: s.voiceRate },
              )
            }
          >
            🔊 Test voice
          </button>
        </div>
      </div>

      <div className={section}>Connections</div>
      <div className="flex flex-col gap-3 py-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Speech service (Part B)</span>
          <input
            className="rounded-lg border border-line bg-surface px-3 py-1.5 font-mono text-sm"
            value={s.speechUrl}
            onChange={(e) => update({ speechUrl: e.target.value.trim() })}
          />
          <span className="text-xs text-muted">
            The app's only WebSocket ({'<url>'}/ws). Use {location.origin}/mock with <code>server.py --mock</code>.
          </span>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Sign service (Part A), camera preview</span>
          <input
            className="rounded-lg border border-line bg-surface px-3 py-1.5 font-mono text-sm"
            value={s.signUrl}
            onChange={(e) => update({ signUrl: e.target.value.trim() })}
          />
        </label>
      </div>

      <div className="mt-6 flex flex-wrap gap-2 border-t border-line pt-4">
        <button className="btn" onClick={onNewConversation}>
          🗑 Clear conversation
        </button>
        <button className="btn" onClick={reset}>
          ↺ Reset settings
        </button>
      </div>
    </Drawer>
  )
}

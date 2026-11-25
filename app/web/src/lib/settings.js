import { useEffect, useState } from 'react'

const KEY = 'signbridge.settings.v1'
const host = typeof location !== 'undefined' ? location.hostname || 'localhost' : 'localhost'
const mockParam = typeof location !== 'undefined' && new URLSearchParams(location.search).has('mock')

export const DEFAULTS = {
  // services
  speechUrl: `http://${host}:8002`, // Part B: the only WebSocket the app needs
  signUrl: `http://${host}:8001`, // Part A: camera preview only
  // speaker (hearing person)
  language: 'en', // en | hi | te
  sttEngine: 'browser', // browser (Web Speech API) | whisper (record + POST /speech)
  // voice for the signer's sentences
  autoSpeak: true,
  voice: 'server', // server (/tts, emotion-styled) | browser (speechSynthesis)
  voiceRate: 1,
  // avatar
  avatarMode: 'video', // video (INCLUDE clips) | skeleton (2-D landmarks)
  avatarSpeed: 1,
  autoPlayAvatar: true,
  // accessibility
  textSize: 'normal', // normal | large | xlarge
  highContrast: false,
  flashAlerts: true,
  vibrate: true,
  showCamera: true,
}

function readSaved() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '{}')
  } catch {
    return {}
  }
}

export function loadSettings() {
  const s = { ...DEFAULTS, ...readSaved() }
  if (mockParam) s.speechUrl = `${location.origin}/mock` // ?mock: this visit only, not saved
  return s
}

export function useSettings() {
  const [settings, setSettings] = useState(loadSettings)
  useEffect(() => {
    const keep = mockParam ? { speechUrl: readSaved().speechUrl ?? DEFAULTS.speechUrl } : {}
    localStorage.setItem(KEY, JSON.stringify({ ...settings, ...keep }))
  }, [settings])
  const update = (patch) => setSettings((s) => ({ ...s, ...patch }))
  const reset = () => setSettings({ ...DEFAULTS })
  return [settings, update, reset]
}

export const LANGS = {
  en: { name: 'English', native: 'English', bcp: 'en-IN' },
  hi: { name: 'Hindi', native: 'हिन्दी', bcp: 'hi-IN' },
  te: { name: 'Telugu', native: 'తెలుగు', bcp: 'te-IN' },
}

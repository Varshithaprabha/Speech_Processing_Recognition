import { LANGS } from './settings'

/* ---------------------------------------------------------------- text-to-speech (signer -> hearing person)
 * Sentences are queued so two messages never talk over each other.
 * 'server': GET speech_service /tts (edge-tts, en-IN/hi-IN/te-IN, emotion-styled). Falls back to the browser.
 */
const queue = []
let busy = false
let current = null

const RATE = { urgent: 1.15, angry: 1.05, question: 1, happy: 1.05, neutral: 1 }
const PITCH = { urgent: 1.1, angry: 0.9, question: 1.1, happy: 1.15, neutral: 1 }

function browserSpeak(text, language, emotion, rate) {
  return new Promise((resolve) => {
    if (!('speechSynthesis' in window)) return resolve()
    const u = new SpeechSynthesisUtterance(text)
    const bcp = LANGS[language]?.bcp || 'en-IN'
    u.lang = bcp
    const voices = speechSynthesis.getVoices()
    u.voice =
      voices.find((v) => v.lang === bcp) || voices.find((v) => v.lang.startsWith(language)) || null
    u.rate = (RATE[emotion] || 1) * rate
    u.pitch = PITCH[emotion] || 1
    u.onend = u.onerror = () => resolve()
    speechSynthesis.speak(u)
  })
}

async function serverSpeak(base, text, language, emotion, rate) {
  const url = `${base.replace(/\/$/, '')}/tts?${new URLSearchParams({ text, language, emotion })}`
  const r = await fetch(url)
  if (!r.ok) throw new Error(`tts ${r.status}`)
  const blob = await r.blob()
  const src = URL.createObjectURL(blob)
  await new Promise((resolve, reject) => {
    const a = new Audio(src)
    current = a
    a.playbackRate = rate
    a.onended = resolve
    a.onerror = reject
    a.play().catch(reject)
  }).finally(() => {
    current = null
    URL.revokeObjectURL(src)
  })
}

async function drain() {
  if (busy) return
  busy = true
  while (queue.length) {
    const { text, language, emotion, opts } = queue.shift()
    opts.onStart?.()
    try {
      if (opts.voice === 'server') await serverSpeak(opts.base, text, language, emotion, opts.rate)
      else await browserSpeak(text, language, emotion, opts.rate)
    } catch {
      await browserSpeak(text, language, emotion, opts.rate)
    }
    opts.onEnd?.()
  }
  busy = false
}

export function speak(text, language, emotion, opts) {
  if (!text) return
  queue.push({ text, language: language || 'en', emotion: emotion || 'neutral', opts })
  drain()
}

export function stopSpeaking() {
  queue.length = 0
  current?.pause()
  if ('speechSynthesis' in window) speechSynthesis.cancel()
}

/* ---------------------------------------------------------------- speech-to-text (hearing person)
 * 'browser': Web Speech API (Chrome/Edge), interim results -> {"cmd":"partial"}, final -> {"cmd":"text"}.
 * 'whisper': MediaRecorder; partial audio -> POST /speech_partial every ~1.5 s, final -> POST /speech.
 * Both engines report through the same callbacks; the server broadcasts the result to everyone.
 */
export const browserSttSupported = () =>
  typeof window !== 'undefined' && !!(window.SpeechRecognition || window.webkitSpeechRecognition)

export function startBrowserStt({ language, onPartial, onFinal, onError, onEnd }) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  const rec = new SR()
  rec.lang = LANGS[language]?.bcp || 'en-IN'
  rec.interimResults = true
  rec.continuous = true
  rec.maxAlternatives = 1
  rec.onresult = (e) => {
    let interim = ''
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i]
      if (r.isFinal) onFinal(r[0].transcript.trim(), r[0].confidence || 0.9)
      else interim += r[0].transcript
    }
    if (interim.trim()) onPartial(interim.trim())
  }
  rec.onerror = (e) => onError?.(e.error === 'not-allowed' ? 'Microphone permission denied' : e.error)
  rec.onend = () => onEnd?.()
  rec.start()
  return { stop: () => rec.stop() }
}

export async function startWhisperStt({ base, language, onError, onEnd, onBusy }) {
  const root = base.replace(/\/$/, '')
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg', 'audio/mp4'].find(
    (m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m),
  )
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
  const chunks = []
  let partialBusy = false
  const post = async (path, blob) => {
    const fd = new FormData()
    fd.append('file', blob, `speech.${(mime || 'audio/webm').split('/')[1].split(';')[0]}`)
    fd.append('language', language)
    const r = await fetch(root + path, { method: 'POST', body: fd })
    if (!r.ok) {
      let detail = `${r.status}`
      try {
        detail = (await r.json()).detail || detail
      } catch {
        /* ignore */
      }
      throw new Error(detail)
    }
    return r.json()
  }
  rec.ondataavailable = async (e) => {
    if (e.data.size) chunks.push(e.data)
    if (rec.state === 'recording' && !partialBusy && chunks.length) {
      partialBusy = true // live caption: server broadcasts speech_partial
      post('/speech_partial', new Blob(chunks, { type: rec.mimeType }))
        .catch(() => {})
        .finally(() => (partialBusy = false))
    }
  }
  rec.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop())
    onBusy?.(true)
    try {
      if (chunks.length) await post('/speech', new Blob(chunks, { type: rec.mimeType })) // server broadcasts "text"
    } catch (e) {
      onError?.(String(e.message || e))
    } finally {
      onBusy?.(false)
      onEnd?.()
    }
  }
  rec.start(1500)
  return { stop: () => rec.state !== 'inactive' && rec.stop() }
}

/* ---------------------------------------------------------------- alerts */
export function vibrate(pattern) {
  try {
    navigator.vibrate?.(pattern)
  } catch {
    /* ignore */
  }
}

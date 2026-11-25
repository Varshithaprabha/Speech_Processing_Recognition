import { useCallback, useEffect, useRef, useState } from 'react'

export const wsUrl = (httpBase) => httpBase.replace(/\/$/, '').replace(/^http/, 'ws') + '/ws'

/**
 * One WebSocket to speech_service (ws://host:8002/ws). It forwards Part A's messages too.
 * Reconnects with back-off. `onMessage` always sees the latest callback (kept in a ref).
 */
export function useBridge(httpBase, onMessage) {
  const [status, setStatus] = useState('connecting') // connecting | open | closed
  const sockRef = useRef(null)
  const handler = useRef(onMessage)
  handler.current = onMessage

  useEffect(() => {
    let stop = false
    let timer = null
    let delay = 500
    const connect = () => {
      setStatus('connecting')
      let ws
      try {
        ws = new WebSocket(wsUrl(httpBase))
      } catch {
        setStatus('closed')
        return
      }
      sockRef.current = ws
      ws.onopen = () => {
        delay = 500
        setStatus('open')
      }
      ws.onmessage = (ev) => {
        try {
          handler.current?.(JSON.parse(ev.data))
        } catch (e) {
          console.warn('bad message', e, ev.data)
        }
      }
      ws.onclose = () => {
        if (sockRef.current === ws) sockRef.current = null
        setStatus('closed')
        if (!stop) timer = setTimeout(connect, (delay = Math.min(delay * 2, 8000)))
      }
      ws.onerror = () => ws.close()
    }
    connect()
    return () => {
      stop = true
      clearTimeout(timer)
      sockRef.current?.close()
    }
  }, [httpBase])

  const send = useCallback((obj) => {
    const ws = sockRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj))
      return true
    }
    return false
  }, [])

  return { status, send }
}

/** Poll speech_service /health: tells us if sign_service (Part A) is connected and which AI answers. */
export function useHealth(httpBase, every = 5000) {
  const [health, setHealth] = useState(null)
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const r = await fetch(httpBase.replace(/\/$/, '') + '/health')
        const j = await r.json()
        if (alive) setHealth(j)
      } catch {
        if (alive) setHealth(null)
      }
    }
    tick()
    const id = setInterval(tick, every)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [httpBase, every])
  return health
}

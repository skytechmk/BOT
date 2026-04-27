import { useEffect, useRef, useState } from 'react'

export function useEventSource(url, { enabled = true } = {}) {
  const [data, setData] = useState(null)
  const [connected, setConnected] = useState(false)
  const esRef = useRef(null)

  useEffect(() => {
    if (!enabled || !url) return
    const token = localStorage.getItem('token')
    const fullUrl = token ? `${url}?token=${token}` : url
    const es = new EventSource(fullUrl)
    esRef.current = es

    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    es.onmessage = (e) => {
      try { setData(JSON.parse(e.data)) } catch {}
    }

    return () => { es.close(); setConnected(false) }
  }, [url, enabled])

  return { data, connected }
}

export function usePriceStream(enabled = true) {
  return useEventSource('/api/stream/prices', { enabled })
}

export function useLivePnlStream(enabled = true) {
  return useEventSource('/api/stream/live_pnl', { enabled })
}

export function useStatsStream(enabled = true) {
  return useEventSource('/api/stream/stats', { enabled })
}

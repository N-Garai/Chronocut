import { useEffect, useState } from 'react'
import { getCapabilities } from '../lib/api'

export function useCapabilities() {
  const [caps, setCaps] = useState(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let alive = true
    getCapabilities()
      .then((d) => alive && setCaps(d))
      .catch(() => alive && setCaps({ support_envelope: {}, provider_menu: [] }))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])
  return { caps, loading }
}

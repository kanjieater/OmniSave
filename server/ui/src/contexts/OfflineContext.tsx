import * as React from 'react'
import { queryClient } from '@/lib/queryClient'

interface OfflineContextValue {
  isOffline: boolean
  errorCount: number
  retryIn: number | null
  handleRetry: () => void
}

const OfflineContext = React.createContext<OfflineContextValue | null>(null)

const FAILURE_THRESHOLD = 3
const RETRY_INTERVAL_SECS = 60

export function OfflineProvider({ children }: { children: React.ReactNode }) {
  const [isOffline, setIsOffline] = React.useState(false)
  const [retryIn, setRetryIn] = React.useState<number | null>(null)
  const [errorCount, setErrorCount] = React.useState(0)

  // Use a ref so callbacks don't go stale inside the subscribe closure
  const consecutiveFailures = React.useRef(0)
  const countdownInterval = React.useRef<ReturnType<typeof setInterval> | null>(null)
  const retryTimeout = React.useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimers = React.useCallback(() => {
    if (countdownInterval.current) { clearInterval(countdownInterval.current); countdownInterval.current = null }
    if (retryTimeout.current)      { clearTimeout(retryTimeout.current);       retryTimeout.current = null }
  }, [])

  const startCountdown = React.useCallback(() => {
    clearTimers()
    setRetryIn(RETRY_INTERVAL_SECS)

    countdownInterval.current = setInterval(() => {
      setRetryIn((prev) => (prev !== null && prev > 1 ? prev - 1 : null))
    }, 1_000)

    retryTimeout.current = setTimeout(() => {
      clearTimers()
      setRetryIn(null)
      void queryClient.invalidateQueries()
    }, RETRY_INTERVAL_SECS * 1_000)
  }, [clearTimers])

  const recordFailure = React.useCallback(() => {
    consecutiveFailures.current += 1
    if (consecutiveFailures.current >= FAILURE_THRESHOLD) {
      setIsOffline(true)
      startCountdown()
    }
  }, [startCountdown])

  const recordSuccess = React.useCallback(() => {
    consecutiveFailures.current = 0
    setIsOffline(false)
    setRetryIn(null)
    clearTimers()
  }, [clearTimers])

  const handleRetry = React.useCallback(() => {
    clearTimers()
    setRetryIn(null)
    void queryClient.invalidateQueries()
  }, [clearTimers])

  // Wire offline detection to TanStack Query cache events
  React.useEffect(() => {
    const unsub = queryClient.getQueryCache().subscribe((event) => {
      if (event.type === 'updated') {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const actionType = (event as any).action?.type as string | undefined
        if (actionType === 'error')   recordFailure()
        if (actionType === 'success') recordSuccess()
      }

      // Keep notification badge in sync with unacknowledged errors
      const errorsData = queryClient.getQueryData<{ errors: { acknowledged: boolean }[] }>(['errors'])
      if (errorsData) {
        setErrorCount(errorsData.errors.filter((e) => !e.acknowledged).length)
      }
    })
    return () => { unsub(); clearTimers() }
  }, [recordFailure, recordSuccess, clearTimers])

  return (
    <OfflineContext.Provider value={{ isOffline, errorCount, retryIn, handleRetry }}>
      {children}
    </OfflineContext.Provider>
  )
}

export function useOffline() {
  const ctx = React.useContext(OfflineContext)
  if (!ctx) throw new Error('useOffline must be used within OfflineProvider')
  return ctx
}

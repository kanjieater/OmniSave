import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api'
import { OfflineProvider, useOffline } from '@/contexts/OfflineContext'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { OfflineBanner } from '@/components/ui/offline-banner'
import { BottomNav } from './BottomNav'
import { NotificationDrawerV2 } from './NotificationDrawerV2'
import { SideNav } from './SideNav'
import { TopBar } from './TopBar'

interface BackgroundCtxValue {
  setBg: (url: string | null) => void
  dynamicBgEnabled: boolean
  setDynamicBgEnabled: (v: boolean) => void
}
const BackgroundCtx = React.createContext<BackgroundCtxValue>({
  setBg: () => {},
  dynamicBgEnabled: true,
  setDynamicBgEnabled: () => {},
})
export function useBackground() { return React.useContext(BackgroundCtx).setBg }
export function useAppearance() {
  const { dynamicBgEnabled, setDynamicBgEnabled } = React.useContext(BackgroundCtx)
  return { dynamicBgEnabled, setDynamicBgEnabled }
}

function DynamicBackground({ url }: { url: string | null }) {
  const [slots, setSlots] = React.useState<[string | null, string | null]>([null, null])
  const [active, setActive] = React.useState<0 | 1 | -1>(-1)

  React.useEffect(() => {
    if (!url) {
      setActive(-1)  // fade out current slot; backgroundImage stays for smooth transition
      return
    }
    const next = active === 0 ? 1 : 0
    setSlots(s => { const n = [...s] as [string | null, string | null]; n[next] = url; return n })
    setActive(next)
  }, [url])

  return (
    <>
      {([0, 1] as const).map(i => (
        <div
          key={i}
          aria-hidden="true"
          className="fixed inset-0 w-full h-full bg-cover bg-center scale-150 blur-xl pointer-events-none select-none transition-opacity duration-[2000ms] ease-in-out"
          style={{
            backgroundImage: slots[i] ? `url(${slots[i]})` : undefined,
            opacity: active === i ? 0.15 : 0,
          }}
        />
      ))}
    </>
  )
}

/**
 * Radix Select v2.x (tested at 2.2.6) hardcodes RemoveScroll inside SelectContent with
 * no API to disable it. When ANY Select dropdown opens, react-remove-scroll-bar injects:
 *
 *   body[data-scroll-locked] { overflow: hidden !important; margin-right: Xpx !important; }
 *
 * This removes the browser scrollbar and shifts the page width, making all grid cards
 * appear to shrink simultaneously. The `modal` prop that would disable this does not exist
 * in v2.2.6 — it was added in a later version.
 *
 * Fix: inject our own <style> that cancels those rules. Because both sides use !important,
 * the rule that appears LATER in <head> wins. A MutationObserver keeps our element as the
 * last child of <head> so we always win, even after react-style-singleton injects its tag.
 *
 * Do NOT remove this hook or "simplify" it away — the symptom looks like a layout shift
 * bug, not a Radix internals issue, which is why it took a long time to diagnose.
 */
function useScrollLockOverride() {
  React.useEffect(() => {
    const el = document.createElement('style')
    el.textContent = [
      'body[data-scroll-locked]{',
      'overflow:auto!important;',
      'margin-right:0!important;',
      'padding-right:0!important;',
      '}',
    ].join('')
    const pin = () => { if (document.head.lastChild !== el) document.head.appendChild(el) }
    const obs = new MutationObserver(pin)
    obs.observe(document.head, { childList: true })
    pin()
    return () => { obs.disconnect(); el.remove() }
  }, [])
}

function ShellInner({ children }: { children: React.ReactNode }) {
  useScrollLockOverride()
  const { isOffline, errorCount, retryIn, handleRetry } = useOffline()
  const [bgUrl, setBgUrl] = React.useState<string | null>(null)
  const [dynamicBgEnabled, setDynamicBgEnabled] = useLocalStorage<boolean>('pref:appearance:dynamic-bg', false)

  const { data: conflictCount = 0 } = useQuery({
    queryKey: ['games'],
    queryFn: () => api.games(),
    select: (d) => d.games.filter((g) => g.status === 'CONFLICT').length,
    refetchInterval: 15_000,
    staleTime: 15_000,
  })
  const [notifOpen, setNotifOpen] = React.useState(false)

  return (
    <BackgroundCtx.Provider value={{ setBg: setBgUrl, dynamicBgEnabled, setDynamicBgEnabled }}>
    <div className="relative flex min-h-svh bg-[var(--color-bg-base)] text-[var(--color-text-primary)] overflow-hidden">
      {/* Wallpaper background — same as login page */}
      {dynamicBgEnabled && (
        <img
          src="/omnisave-background.svg"
          className="fixed inset-0 w-full h-full object-cover scale-150 blur-xl opacity-20 pointer-events-none select-none"
          aria-hidden="true"
          alt=""
        />
      )}
      {/* Dynamic game image layer — crossfades when a page sets a bg image */}
      <DynamicBackground url={dynamicBgEnabled ? bgUrl : null} />

      {/* Skip-to-content — first focusable element on every page (WCAG 2.4.1) */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-[var(--spacing-2)] focus:left-[var(--spacing-2)] focus:z-[var(--z-tooltip)] focus:px-[var(--spacing-3)] focus:py-[var(--spacing-2)] focus:rounded-[var(--radius-md)] focus:bg-[var(--color-accent)] focus:text-white focus:text-sm focus:font-[var(--font-weight-medium)]"
      >
        Skip to content
      </a>

      {/* Full-width top bar — spans over side nav (z-sticky > z-fixed) */}
      <TopBar
        errorCount={errorCount}
        onBellClick={() => setNotifOpen(true)}
        className="fixed top-0 left-0 right-0 z-[var(--z-sticky)]"
      />

      {/* Desktop icon rail — starts below TopBar, must match --layout-topbar */}
      <aside
        aria-label="Site navigation"
        className="hidden md:flex flex-col w-[var(--layout-sidenav)] shrink-0 fixed top-[var(--layout-topbar)] left-0 bottom-0 z-[var(--z-fixed)] border-r border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)]"
      >
        <SideNav conflictCount={conflictCount} />
      </aside>

      {/* Main column — offset right for side nav, down for top bar */}
      <div className="flex flex-col flex-1 md:pl-[var(--layout-sidenav)] pt-[var(--layout-topbar)] min-w-0">
        {isOffline && (
          <OfflineBanner retryIn={retryIn ?? undefined} onRetry={handleRetry} />
        )}

        <main id="main-content" className="flex-1 min-w-0 pb-[var(--touch-bottom-nav)] md:pb-0">
          {children}
        </main>
      </div>

      {/* Mobile bottom bar */}
      <BottomNav />

      {/* Notification drawer */}
      <NotificationDrawerV2 open={notifOpen} onOpenChange={setNotifOpen} />
    </div>
    </BackgroundCtx.Provider>
  )
}

export function AppShellV2({ children }: { children: React.ReactNode }) {
  return (
    <OfflineProvider>
      <ShellInner>{children}</ShellInner>
    </OfflineProvider>
  )
}

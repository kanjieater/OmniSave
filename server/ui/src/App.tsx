import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './contexts/AuthContext'
import AuthPage from './components/auth/AuthPage'
import Dashboard from './components/dashboard/Dashboard'
import DeviceDetailPage from './components/devices/DeviceDetailPage'
import DevicesPage from './components/devices/DevicesPage'
import EventsPage from './components/events/EventsPage'
import GamePage from './components/game/GamePage'
import LibraryPage from './components/library/LibraryPage'
import { AppShellV2 } from './components/layout/AppShellV2'
import SettingsPage from './components/settings/SettingsPage'

function FullScreenMessage({ title, sub, action }: { title: string; sub: string; action?: ReactNode }) {
  return (
    <div className="relative min-h-svh flex items-center justify-center overflow-hidden p-[var(--spacing-4)]">
      <div className="absolute inset-0 bg-[var(--color-bg-base)]" aria-hidden="true" />
      <img
        src="/omnisave-background.svg"
        className="fixed inset-0 w-full h-full object-cover scale-150 blur-xl opacity-20 pointer-events-none select-none"
        aria-hidden="true"
        alt=""
      />
      <div className="relative z-10 w-full max-w-sm flex flex-col items-center gap-[var(--spacing-6)]">
        <img src="/omnisave.png" alt="OmniSave" className="w-20 h-20 object-contain rounded-[var(--radius-xl)]" />
        <div
          className="w-full flex flex-col items-center gap-[var(--spacing-4)] rounded-[var(--radius-xl)] border border-[var(--color-border-subtle)] p-[var(--spacing-6)] backdrop-blur-2xl text-center"
          style={{ backgroundColor: 'rgba(17, 19, 24, 0.72)' }}
        >
          <p className="text-base font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]">{title}</p>
          <p className="text-sm text-[var(--color-text-muted)]">{sub}</p>
          {action}
        </div>
      </div>
    </div>
  )
}

function AuthGuard({ children }: { children: ReactNode }) {
  const { authenticated, loading, netError, retryAuth } = useAuth()
  const [showLoading, setShowLoading] = useState(false)

  useEffect(() => {
    if (!loading) { setShowLoading(false); return; }
    const t = setTimeout(() => setShowLoading(true), 300)
    return () => clearTimeout(t)
  }, [loading])

  if (loading) return showLoading ? (
    <FullScreenMessage
      title="Connecting…"
      sub="Reaching your OmniSave server"
    />
  ) : null
  if (netError) return (
    <FullScreenMessage
      title="Can't reach server"
      sub="Retrying automatically — or tap to try now"
      action={
        <button
          onClick={retryAuth}
          className="px-[var(--spacing-4)] py-[var(--spacing-2)] rounded-[var(--radius-md)] bg-[var(--color-accent)] text-white text-sm font-[var(--font-weight-medium)] hover:opacity-90 transition-opacity"
        >
          Retry now
        </button>
      }
    />
  )
  if (!authenticated) return <AuthPage />
  return <>{children}</>
}

function AnimatedRoutes() {
  const location = useLocation()
  return (
    <div key={location.key} className="animate-page-in min-h-full">
      <Routes location={location}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/game/:title_id" element={<GamePage />} />
        <Route path="/devices" element={<DevicesPage />} />
        <Route path="/devices/:device_id" element={<DeviceDetailPage />} />
        <Route path="/activity" element={<EventsPage />} />
        <Route path="/events" element={<Navigate to="/activity" replace />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </div>
  )
}

export default function App() {
  return (
    <AuthGuard>
      <AppShellV2>
        <AnimatedRoutes />
      </AppShellV2>
    </AuthGuard>
  )
}

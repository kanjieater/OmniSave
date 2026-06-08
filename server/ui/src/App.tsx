import type { ReactNode } from 'react'
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

function AuthGuard({ children }: { children: ReactNode }) {
  const { authenticated, loading } = useAuth()
  if (loading) return null
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

import { Eye, EyeOff } from 'lucide-react'
import * as React from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export default function AuthPage() {
  const { login } = useAuth()
  const [username, setUsername] = React.useState('')
  const [password, setPassword] = React.useState('')
  const [showPass, setShowPass] = React.useState(false)
  const [err, setErr] = React.useState('')
  const [busy, setBusy] = React.useState(false)

  const handleLogin = async () => {
    if (!username.trim()) { setErr('Enter your username'); return }
    if (!password) { setErr('Enter your password'); return }
    setBusy(true)
    setErr('')
    try {
      await login(username.trim(), password)
    } catch {
      setErr('Invalid username or password')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative min-h-svh flex items-center justify-center overflow-hidden p-[var(--spacing-4)]">
      {/* Dark base */}
      <div className="absolute inset-0 bg-[var(--color-bg-base)]" aria-hidden="true" />

      {/* Giant blurred background image */}
      <img
        src="/omnisave-background.svg"
        className="fixed inset-0 w-full h-full object-cover scale-150 blur-xl opacity-20 pointer-events-none select-none"
        aria-hidden="true"
        alt=""
      />

      {/* Card */}
      <div className="relative z-10 w-full max-w-sm flex flex-col items-center gap-[var(--spacing-6)]">
        <div className="flex flex-col items-center gap-[var(--spacing-3)]">
          <img src="/omnisave.png" alt="OmniSave" className="w-20 h-20 object-contain rounded-[var(--radius-xl)]" />
          <div className="text-center">
            <h1 className="text-xl font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]">
              OmniSave
            </h1>
            <p className="text-sm text-[var(--color-text-muted)] mt-[var(--spacing-1)]">
              Sign in to your server
            </p>
          </div>
        </div>

        <div
          className="w-full flex flex-col gap-[var(--spacing-4)] rounded-[var(--radius-xl)] border border-[var(--color-border-subtle)] p-[var(--spacing-6)] backdrop-blur-2xl"
          style={{ backgroundColor: 'rgba(17, 19, 24, 0.72)' }}
        >
          {err && (
            <div role="alert" className="text-sm text-[var(--color-error)] bg-[var(--color-error-subtle)] border border-[var(--color-error-border)] rounded-[var(--radius-md)] px-[var(--spacing-3)] py-[var(--spacing-2)]">
              {err}
            </div>
          )}

          <div className="flex flex-col gap-[var(--spacing-2)]">
            <label htmlFor="auth-username" className="text-sm font-[var(--font-weight-medium)] text-[var(--color-text-secondary)]">
              Username
            </label>
            <Input
              id="auth-username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void handleLogin()}
              placeholder="admin"
              autoFocus
              autoComplete="username"
              error={!!err}
            />
          </div>

          <div className="flex flex-col gap-[var(--spacing-2)]">
            <label htmlFor="auth-password" className="text-sm font-[var(--font-weight-medium)] text-[var(--color-text-secondary)]">
              Password
            </label>
            <div className="relative">
              <Input
                id="auth-password"
                type={showPass ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void handleLogin()}
                placeholder="••••••••"
                autoComplete="current-password"
                error={!!err}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPass((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                aria-label={showPass ? 'Hide password' : 'Show password'}
              >
                {showPass ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          <Button className="w-full" onClick={() => void handleLogin()} disabled={busy}>
            {busy ? 'Signing in…' : 'Sign In'}
          </Button>
        </div>
      </div>
    </div>
  )
}

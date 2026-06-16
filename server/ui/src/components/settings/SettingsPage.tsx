import { AlertCircle, Trash2 } from 'lucide-react'
import * as React from 'react'
import { useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api'
import type { LoginUser } from '@/types'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { useAppearance } from '@/components/layout/AppShellV2'
import { MyDevicesSection, PairNewDevice, AcceptShareCode } from './DevicesSection'

function useSectionHash(hash: string) {
  const location = useLocation()
  const ref = React.useRef<HTMLElement>(null)
  const [flashing, setFlashing] = React.useState(false)
  React.useEffect(() => {
    if (location.hash !== hash) return
    ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setFlashing(true)
    const t = setTimeout(() => setFlashing(false), 1400)
    return () => clearTimeout(t)
  }, [location.hash, location.key, hash])
  return { ref, flashing }
}

function AppearanceSection() {
  const { dynamicBgEnabled: dynamicBg, setDynamicBgEnabled: setDynamicBg } = useAppearance()
  return (
    <section className="flex flex-col gap-[var(--spacing-4)]">
      <div className="flex min-h-8 items-center">
        <h2 className="text-sm font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] uppercase tracking-[var(--tracking-wide)]">
          Appearance
        </h2>
      </div>
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] px-[var(--spacing-4)]">
        <div className="py-3 flex items-center justify-between gap-3">
          <div className="flex flex-col gap-[var(--spacing-1)]">
            <label className="text-sm">Background image</label>
            <p className="text-xs text-[var(--color-text-muted)]">Show blurred art behind page content</p>
          </div>
          <Switch checked={dynamicBg} onCheckedChange={setDynamicBg} />
        </div>
      </div>
    </section>
  )
}

function RommServerSection() {
  const { ref, flashing } = useSectionHash('#romm-server')
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['rommServerSettings'],
    queryFn: () => api.rommServerSettings(),
  })

  const [host, setHost] = React.useState('')
  const [apiKey, setApiKey] = React.useState('')
  const [connectDirty, setConnectDirty] = React.useState(false)

  React.useEffect(() => {
    if (data) {
      setHost(data.host ?? '')
      setApiKey('')
      setConnectDirty(false)
    }
  }, [data])

  // Toggle fires immediately — no Save button needed.
  const toggleMut = useMutation({
    mutationFn: (v: boolean) => api.setRommServerSettings({ enabled: v }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rommServerSettings'] })
      qc.invalidateQueries({ queryKey: ['devices'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: () => {
      qc.invalidateQueries({ queryKey: ['rommServerSettings'] })
    },
  })

  // Connect button saves host + API key only.
  const connectMut = useMutation({
    mutationFn: () => api.setRommServerSettings({
      host: host || undefined,
      api_key: apiKey || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rommServerSettings'] })
      qc.invalidateQueries({ queryKey: ['devices'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setApiKey('')
      setConnectDirty(false)
    },
  })

  const enabled = data?.enabled ?? true

  const CONNECT_STATUS_LABELS: Record<string, string> = {
    auth_failed: 'Auth failed',
    network_error: 'Unreachable',
    bad_response: 'Bad response',
    unknown: 'Error',
  }

  const statusDot = (() => {
    if (isLoading) return null
    const connectStatus = data?.romm_connect_status ?? ''
    const hasError = !!connectStatus && connectStatus !== 'ok'
    const active = enabled && !!data?.host && !!data?.has_api_key && !!data?.romm_username && !hasError
    const partial = enabled && !!data?.host && !data?.has_api_key
    const color = hasError
      ? 'bg-[var(--color-error)]'
      : active ? 'bg-[var(--color-success)]'
      : partial ? 'bg-amber-400'
      : 'bg-[var(--color-text-muted)]'
    const label = !enabled ? 'Offline'
      : !data?.host ? 'Not configured'
      : !data?.has_api_key ? 'No API key'
      : hasError ? (CONNECT_STATUS_LABELS[connectStatus] ?? 'Error')
      : 'Online'
    return (
      <span className="inline-flex items-center gap-1.5">
        <span className="relative flex h-2 w-2">
          {active && <span className={`animate-device-pulse absolute inline-flex h-full w-full rounded-full ${color}`} />}
          <span className={`relative inline-flex rounded-full h-2 w-2 ${color}`} />
        </span>
        <span className="text-xs text-[var(--color-text-muted)]">{label}</span>
      </span>
    )
  })()

  return (
    <section id="romm-server" ref={ref} className={cn('flex flex-col gap-[var(--spacing-4)]', flashing && 'animate-section-flash')}>
      <div className="flex min-h-8 items-center gap-3">
        <h2 className="text-sm font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] uppercase tracking-[var(--tracking-wide)]">
          RomM Server
        </h2>
        {statusDot}
      </div>

      {/* Toggle — immediate, no save button */}
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] px-[var(--spacing-4)]">
        {isLoading ? (
          <div className="py-3 flex items-center gap-3"><Skeleton className="h-4 flex-1" /><Skeleton className="h-5 w-9" /></div>
        ) : (
          <div className="py-3 flex items-center justify-between gap-3">
            <label className="text-sm">Enable RomM sync</label>
            <Switch
              checked={enabled}
              loading={toggleMut.isPending}
              onCheckedChange={(v) => toggleMut.mutate(v)}
            />
          </div>
        )}
      </div>

      {/* Server config — requires Connect RomM */}
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] px-[var(--spacing-4)] divide-y divide-[var(--color-border-subtle)]">
        {isLoading ? (
          <div className="py-3 flex flex-col gap-2">
            <Skeleton className="h-4 w-32" /><Skeleton className="h-7 w-full" />
          </div>
        ) : (
          <>
            <div className="py-3 flex flex-col gap-1.5">
              <label className="text-xs text-[var(--color-text-muted)]">Server URL</label>
              <Input
                placeholder="https://romm.example.com"
                value={host}
                onChange={(e) => { setHost(e.target.value); setConnectDirty(true) }}
              />
            </div>
            <div className="py-3 flex flex-col gap-1.5">
              <label className="text-xs text-[var(--color-text-muted)]">
                API Key {data?.has_api_key && <span className="text-[var(--color-text-muted)]">(set — leave blank to keep)</span>}
              </label>
              <Input
                type="password"
                placeholder={data?.has_api_key ? '••••••••' : 'Enter API key'}
                value={apiKey}
                onChange={(e) => { setApiKey(e.target.value); setConnectDirty(true) }}
                autoComplete="new-password"
              />
            </div>
            {data?.romm_username && (
              <div className="py-3 flex items-center justify-between gap-2">
                <span className="text-xs text-[var(--color-text-muted)]">Connected as</span>
                <span className="text-xs font-[var(--font-weight-medium)] text-[var(--color-text-primary)]">{data.romm_username}</span>
              </div>
            )}
            <div className="py-3 flex justify-end">
              <Button
                size="sm"
                disabled={!connectDirty || connectMut.isPending}
                onClick={() => connectMut.mutate()}
              >
                {connectMut.isPending ? 'Connecting…' : 'Connect RomM'}
              </Button>
            </div>
          </>
        )}
      </div>
      {connectMut.isError && (
        <p className="text-xs text-[var(--color-error)]">{String(connectMut.error)}</p>
      )}
      {!connectMut.isError && connectMut.data?.romm_connect_status && connectMut.data.romm_connect_status !== 'ok' && (
        <div className="flex items-center gap-2 text-xs text-[var(--color-error)]">
          <AlertCircle size={13} className="shrink-0" />
          <span>
            {CONNECT_STATUS_LABELS[connectMut.data.romm_connect_status] ?? 'Connection error'}
            {connectMut.data.romm_connect_detail ? ` — ${connectMut.data.romm_connect_detail}` : ''}
            {connectMut.data.romm_connect_status === 'auth_failed' ? '. Check your API key.' : '. Check server URL.'}
          </span>
        </div>
      )}
    </section>
  )
}

function CredentialsSection() {
  const { ref, flashing } = useSectionHash('#account')
  const { username, logout } = useAuth()
  const [currentPw, setCurrentPw] = React.useState('')
  const [newUsername, setNewUsername] = React.useState('')
  const [newPw, setNewPw] = React.useState('')
  const [err, setErr] = React.useState('')
  const [ok, setOk] = React.useState(false)
  const [busy, setBusy] = React.useState(false)

  const save = async () => {
    if (!currentPw) { setErr('Current password is required'); return }
    if (!newUsername.trim() && !newPw) { setErr('Enter a new username or new password'); return }
    setBusy(true); setErr(''); setOk(false)
    try {
      await api.changeCredentials(currentPw, newUsername.trim() || undefined, newPw || undefined)
      setOk(true)
      setCurrentPw(''); setNewUsername(''); setNewPw('')
      if (newPw) {
        const { admin_token } = await api.rotate().catch(async () =>
          api.loginWithCredentials(newUsername.trim() || username, newPw)
        )
        localStorage.setItem('os_token', admin_token)
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : ''
      setErr(msg.includes('403') || msg.includes('current password') ? 'Current password is incorrect' : 'Failed to update credentials')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section id="account" ref={ref} className={cn('flex flex-col gap-[var(--spacing-4)]', flashing && 'animate-section-flash')}>
      <div className="flex min-h-8 items-center">
        <h2 className="text-sm font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] uppercase tracking-[var(--tracking-wide)]">
          Account
        </h2>
      </div>
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] p-[var(--spacing-4)] flex flex-col gap-[var(--spacing-4)]">
        <div>
          <p className="text-sm font-[var(--font-weight-medium)] text-[var(--color-text-primary)]">
            Signed in as <span className="font-mono">{username || 'admin'}</span>
          </p>
          <p className="text-xs text-[var(--color-text-muted)] mt-[var(--spacing-1)]">
            Change your username or password below.
          </p>
        </div>

        {err && (
          <div role="alert" className="text-sm text-[var(--color-error)] bg-[var(--color-error-subtle)] border border-[var(--color-error-border)] rounded-[var(--radius-md)] px-[var(--spacing-3)] py-[var(--spacing-2)]">
            {err}
          </div>
        )}
        {ok && (
          <div className="text-sm text-[var(--color-success,#22c55e)] rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] px-[var(--spacing-3)] py-[var(--spacing-2)]">
            Credentials updated.
          </div>
        )}

        <div className="flex flex-col gap-[var(--spacing-3)]">
          <div className="flex flex-col gap-[var(--spacing-1)]">
            <label className="text-xs font-[var(--font-weight-medium)] text-[var(--color-text-secondary)]">
              Current password <span className="text-[var(--color-error)]">*</span>
            </label>
            <Input type="password" value={currentPw} onChange={e => setCurrentPw(e.target.value)} autoComplete="current-password" />
          </div>
          {/* New username + new password side by side */}
          <div className="grid grid-cols-2 gap-[var(--spacing-3)]">
            <div className="flex flex-col gap-[var(--spacing-1)]">
              <label className="text-xs font-[var(--font-weight-medium)] text-[var(--color-text-secondary)]">
                New username
              </label>
              <Input type="text" value={newUsername} onChange={e => setNewUsername(e.target.value)} placeholder={username || 'admin'} autoComplete="username" />
            </div>
            <div className="flex flex-col gap-[var(--spacing-1)]">
              <label className="text-xs font-[var(--font-weight-medium)] text-[var(--color-text-secondary)]">
                New password
              </label>
              <Input type="password" value={newPw} onChange={e => setNewPw(e.target.value)} autoComplete="new-password" />
            </div>
          </div>
          <p className="text-xs text-[var(--color-text-muted)]">Leave a field blank to keep the current value.</p>
        </div>

        <div className="flex gap-[var(--spacing-2)]">
          <Button size="sm" onClick={() => void save()} disabled={busy}>
            {busy ? 'Saving…' : 'Save Changes'}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void logout()}
            className="text-[var(--color-error)] hover:bg-[var(--color-error-subtle)] hover:text-[var(--color-error)]"
          >
            Sign Out
          </Button>
        </div>
      </div>
    </section>
  )
}

function UsersSection() {
  const { ref, flashing } = useSectionHash('#users')
  const { username: currentUser } = useAuth()
  const qc = useQueryClient()
  const [newUser, setNewUser] = React.useState('')
  const [newPass, setNewPass] = React.useState('')
  const [err, setErr] = React.useState('')
  const [busy, setBusy] = React.useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: () => api.listUsers(),
  })

  const deleteMutation = useMutation({
    mutationFn: (username: string) => api.deleteUser(username),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  const createUser = async () => {
    if (!newUser.trim()) { setErr('Username required'); return }
    if (!newPass) { setErr('Password required'); return }
    setBusy(true); setErr('')
    try {
      await api.createUser(newUser.trim(), newPass)
      setNewUser(''); setNewPass('')
      await qc.invalidateQueries({ queryKey: ['users'] })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : ''
      setErr(msg.includes('409') || msg.includes('exists') ? 'Username already exists' : 'Failed to create user')
    } finally {
      setBusy(false)
    }
  }

  const users: LoginUser[] = data?.users ?? []

  return (
    <section id="users" ref={ref} className={cn('flex flex-col gap-[var(--spacing-4)]', flashing && 'animate-section-flash')}>
      <div className="flex min-h-8 items-center">
        <h2 className="text-sm font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] uppercase tracking-[var(--tracking-wide)]">
          Users
        </h2>
      </div>

      {/* User list */}
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] divide-y divide-[var(--color-border-subtle)]">
        {isLoading ? (
          [0, 1].map(i => (
            <div key={i} className="flex items-center gap-3 px-[var(--spacing-4)] py-[var(--spacing-3)]">
              <Skeleton className="h-4 w-28" />
            </div>
          ))
        ) : users.map(u => (
          <div key={u.username} className="flex items-center gap-[var(--spacing-3)] px-[var(--spacing-4)] py-[var(--spacing-3)]">
            <span className="flex-1 text-sm text-[var(--color-text-primary)] font-mono">
              {u.username}
            </span>
            {u.is_admin && (
              <span className="text-xs text-[var(--color-text-muted)] border border-[var(--color-border-subtle)] rounded px-[var(--spacing-2)] py-px">
                admin
              </span>
            )}
            {u.username === currentUser && (
              <span className="text-xs text-[var(--color-accent)] border border-[var(--color-accent-subtle)] rounded px-[var(--spacing-2)] py-px">
                you
              </span>
            )}
            {!u.is_admin && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => deleteMutation.mutate(u.username)}
                disabled={deleteMutation.isPending}
                className="text-[var(--color-error)] hover:bg-[var(--color-error-subtle)] hover:text-[var(--color-error)] p-[var(--spacing-1)]"
                aria-label={`Delete user ${u.username}`}
              >
                <Trash2 size={14} />
              </Button>
            )}
          </div>
        ))}
      </div>

      {/* Create user */}
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] p-[var(--spacing-4)] flex flex-col gap-[var(--spacing-3)]">
        <p className="text-sm font-[var(--font-weight-medium)] text-[var(--color-text-primary)]">Add user</p>
        {err && (
          <div role="alert" className="text-sm text-[var(--color-error)] bg-[var(--color-error-subtle)] border border-[var(--color-error-border)] rounded-[var(--radius-md)] px-[var(--spacing-3)] py-[var(--spacing-2)]">
            {err}
          </div>
        )}
        <div className="grid grid-cols-2 gap-[var(--spacing-3)]">
          <Input
            type="text"
            placeholder="Username"
            value={newUser}
            onChange={e => setNewUser(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && void createUser()}
            autoComplete="off"
          />
          <Input
            type="password"
            placeholder="Password"
            value={newPass}
            onChange={e => setNewPass(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && void createUser()}
            autoComplete="new-password"
          />
        </div>
        <Button size="sm" onClick={() => void createUser()} disabled={busy} className="self-start">
          {busy ? 'Creating…' : 'Create User'}
        </Button>
      </div>
    </section>
  )
}

function AboutSection() {
  const { data } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.health(),
    staleTime: Infinity,
  })

  return (
    <section className="flex flex-col items-center gap-[var(--spacing-1)] py-[var(--spacing-2)] text-center">
      <p className="text-xs text-[var(--color-text-muted)]">
        OmniSave {data?.version ? `v${data.version}` : ''}
      </p>
      <a
        href="https://github.com/kanjieater/OmniSave"
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs text-[var(--color-accent)] hover:underline"
      >
        github.com/kanjieater/OmniSave
      </a>
    </section>
  )
}

export default function SettingsPage() {
  const { isAdmin } = useAuth()

  return (
    <div className="flex flex-col gap-[var(--spacing-6)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">
      <CredentialsSection />

      <Separator />

      <PairNewDevice />

      <Separator />

      <MyDevicesSection />

      <Separator />

      <AppearanceSection />

      <Separator />

      {isAdmin && <UsersSection />}

      {isAdmin && <Separator />}

      <RommServerSection />

      <Separator />

      <AcceptShareCode />

      <Separator />

      <AboutSection />
    </div>
  )
}

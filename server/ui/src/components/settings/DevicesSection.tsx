import { AlertCircle, Check, Share2, Trash2, UserCheck, UserMinus } from 'lucide-react'
import * as React from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api'
import type { Device, DeviceAccessEntry, DeviceProfile } from '@/types'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { HardwareIcon } from '@/components/ui/hardware-icon'
import { InlineEdit } from '@/components/ui/inline-edit'
import { Input } from '@/components/ui/input'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

const SECTION_H2 = 'text-sm font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] uppercase tracking-[var(--tracking-wide)]'

// ── Share code display ────────────────────────────────────────────────────────

function SharePanel({ deviceId }: { deviceId: string }) {
  const [code, setCode] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)

  const generate = async () => {
    setBusy(true)
    try {
      const { code: c } = await api.generateShareCode(deviceId)
      setCode(c)
    } finally {
      setBusy(false)
    }
  }

  if (code) {
    return (
      <div className="border-t border-[var(--color-border-subtle)] px-[var(--spacing-4)] py-[var(--spacing-3)] flex items-center gap-[var(--spacing-3)]">
        <span className="font-mono font-[var(--font-weight-bold)] text-sm text-[var(--color-text-primary)] tracking-widest">
          {code}
        </span>
        <span className="text-xs text-[var(--color-text-muted)] flex-1">· expires 15 min · single use</span>
        <Button variant="ghost" size="sm" onClick={() => setCode(null)}>Done</Button>
      </div>
    )
  }

  return (
    <div className="border-t border-[var(--color-border-subtle)] px-[var(--spacing-4)] py-[var(--spacing-3)] flex items-center justify-between">
      <span className="text-sm text-[var(--color-text-secondary)]">Share access</span>
      <Button variant="ghost" size="sm" onClick={() => void generate()} disabled={busy}>
        <Share2 size={14} />
        {busy ? 'Generating…' : 'Get code'}
      </Button>
    </div>
  )
}

// ── Shared users list ─────────────────────────────────────────────────────────

function AccessList({ deviceId }: { deviceId: string }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['deviceAccess', deviceId],
    queryFn: () => api.listDeviceAccess(deviceId),
    staleTime: 30_000,
  })

  const revoke = useMutation({
    mutationFn: (userId: string) => api.revokeDeviceAccess(deviceId, userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['deviceAccess', deviceId] }),
  })

  const entries: DeviceAccessEntry[] = data?.access ?? []
  if (isLoading) return (
    <div className="border-t border-[var(--color-border-subtle)] px-[var(--spacing-4)] py-[var(--spacing-2)]">
      <Skeleton className="h-4 w-32" />
    </div>
  )
  if (entries.length === 0) return null

  return (
    <div className="border-t border-[var(--color-border-subtle)] divide-y divide-[var(--color-border-subtle)]">
      {entries.map((e) => (
        <div key={e.user_id} className="flex items-center gap-[var(--spacing-3)] px-[var(--spacing-4)] py-[var(--spacing-2)]">
          <span className="font-mono text-xs text-[var(--color-text-secondary)] flex-1">
            {e.user_id}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => revoke.mutate(e.user_id)}
            disabled={revoke.isPending}
            className="shrink-0 text-[var(--color-text-muted)] hover:text-[var(--color-error)] hover:bg-[var(--color-error-subtle)]"
            aria-label={`Revoke access for ${e.user_id}`}
          >
            <UserMinus size={13} />
          </Button>
        </div>
      ))}
    </div>
  )
}

// ── RomM profile row ──────────────────────────────────────────────────────────

const ROMM_STATUS_LABELS: Record<string, string> = {
  auth_failed: 'Auth failed',
  network_error: 'Unreachable',
  bad_response: 'Bad response',
  unknown: 'Error',
}

function RommProfileRow() {
  const { data, isLoading } = useQuery({
    queryKey: ['rommServerSettings'],
    queryFn: () => api.rommServerSettings(),
    staleTime: 30_000,
  })
  const username = data?.romm_username
  const connectStatus = data?.romm_connect_status ?? ''
  const connectDetail = data?.romm_connect_detail ?? ''
  const hasError = !!connectStatus && connectStatus !== 'ok' && !username

  return (
    <div className="border-t border-[var(--color-border-subtle)] px-[var(--spacing-4)] py-[var(--spacing-3)]">
      <p className="text-xs text-[var(--color-text-muted)] mb-[var(--spacing-2)]">Profile</p>
      {isLoading ? (
        <Skeleton className="h-4 w-28" />
      ) : username ? (
        <div className="flex items-center gap-[var(--spacing-2)]">
          <UserCheck size={14} className="text-[var(--color-success)] shrink-0" />
          <span className="text-sm text-[var(--color-text-primary)]">{username}</span>
        </div>
      ) : hasError ? (
        <div className="flex items-center gap-[var(--spacing-2)]">
          <AlertCircle size={14} className="text-[var(--color-error)] shrink-0" />
          <span className="text-xs text-[var(--color-error)]">
            {ROMM_STATUS_LABELS[connectStatus] ?? 'Connection error'}
            {connectDetail ? ` (${connectDetail})` : ''}
          </span>
        </div>
      ) : (
        <span className="text-xs text-[var(--color-text-muted)]">Not configured</span>
      )}
    </div>
  )
}

// ── Profiles inline ───────────────────────────────────────────────────────────

function ProfilesInCard({ device }: { device: Device }) {
  const deviceId = device.device_id
  const { isAdmin, username } = useAuth()
  const qc = useQueryClient()
  const profilesKey = ['deviceProfiles', deviceId]
  const devicesKey = ['devices']

  const { data, isLoading } = useQuery({
    queryKey: profilesKey,
    queryFn: () => api.deviceProfiles(deviceId),
    staleTime: 30_000,
  })
  const profiles: DeviceProfile[] = data?.profiles ?? []

  const claim = useMutation({
    mutationFn: (profileId: string) => api.claimProfile(deviceId, profileId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: profilesKey }),
  })
  const unclaim = useMutation({
    mutationFn: (profileId: string) => api.unclaimProfile(deviceId, profileId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: profilesKey }),
  })
  const setDefault = useMutation({
    mutationFn: (profileId: string) => api.setDeviceDefaultProfile(deviceId, profileId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: devicesKey }),
  })

  if (!isLoading && profiles.length === 0) return null

  return (
    <div className="border-t border-[var(--color-border-subtle)]">
      <div className="px-[var(--spacing-4)] pt-[var(--spacing-3)] pb-[var(--spacing-1)]">
        <p className="text-xs text-[var(--color-text-muted)]">Profiles</p>
      </div>
      {isLoading ? (
        <div className="px-[var(--spacing-4)] pb-[var(--spacing-3)] flex flex-col gap-[var(--spacing-3)]">
          {[0, 1].map((i) => (
            <div key={i} className="flex items-center gap-[var(--spacing-3)]">
              <Skeleton className="w-3.5 h-3.5 rounded-full shrink-0" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="h-7 w-16" />
            </div>
          ))}
        </div>
      ) : (
        <div className="divide-y divide-[var(--color-border-subtle)]">
          {profiles.map((p) => {
            const displayName = p.profile_name || p.display_hint || p.profile_id.slice(0, 8)
            const isMine = p.user_id === username
            const isClaimed = p.user_id !== null
            const isDefault = p.profile_id === device.default_profile_uid
            return (
              <div key={p.profile_id} className="flex items-center gap-[var(--spacing-3)] px-[var(--spacing-4)] py-[var(--spacing-2)]">
                <UserCheck size={14} className={cn('shrink-0', isMine ? 'text-[var(--color-success)]' : 'text-[var(--color-text-muted)]')} />
                <span className="flex-1 text-sm text-[var(--color-text-primary)] truncate min-w-0">{displayName}</span>

                {isDefault ? (
                  <span className="inline-flex items-center h-7 text-xs text-[var(--color-success)] border border-[var(--color-success)] rounded px-[var(--spacing-2)] shrink-0 select-none">
                    Default
                  </span>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => setDefault.mutate(p.profile_id)} disabled={setDefault.isPending} className="shrink-0 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]">
                    Set Default
                  </Button>
                )}

                {isMine ? (
                  <Button size="sm" variant="ghost" onClick={() => unclaim.mutate(p.profile_id)} disabled={unclaim.isPending} className="shrink-0 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]">
                    Not me
                  </Button>
                ) : isClaimed ? (
                  <>
                    <span className="text-xs text-[var(--color-text-muted)] shrink-0">
                      {isAdmin && p.user_id !== '__claimed__' ? p.user_id : 'Claimed'}
                    </span>
                    {isAdmin && (
                      <Button size="sm" variant="ghost" onClick={() => unclaim.mutate(p.profile_id)} disabled={unclaim.isPending} className="shrink-0 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]">
                        Unclaim
                      </Button>
                    )}
                  </>
                ) : (
                  <Button size="sm" onClick={() => claim.mutate(p.profile_id)} disabled={claim.isPending} className="shrink-0">
                    This is me
                  </Button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Device card ───────────────────────────────────────────────────────────────

function DeviceCard({ device, isOwner }: { device: Device; isOwner: boolean }) {
  const qc = useQueryClient()
  const [confirmDelete, setConfirmDelete] = React.useState(false)

  const del = useMutation({
    mutationFn: () => api.deleteDevice(device.device_id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['devices'] }),
  })

  const rename = async (name: string) => {
    if (name.trim()) await api.setDeviceLabel(device.device_id, name.trim())
    else await api.clearDeviceLabel(device.device_id)
    await qc.invalidateQueries({ queryKey: ['devices'] })
  }

  const deviceLabel = device.display_name ?? device.device_id.slice(0, 8)

  return (
    <>
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] overflow-hidden">
        {/* Identity header */}
        <div className="px-[var(--spacing-4)] py-[var(--spacing-3)] flex items-center gap-[var(--spacing-3)]">
          <Link to={`/devices/${device.device_id}`} className="shrink-0" tabIndex={-1} aria-hidden="true">
            <HardwareIcon clientType={device.client_type} hardwareType={device.hardware_type} size={24} />
          </Link>
          <div className="flex-1 min-w-0">
            <InlineEdit
              value={deviceLabel}
              onSave={rename}
              editLabel="Rename client"
              renderValue={(v) => (
                <Link
                  to={`/devices/${device.device_id}`}
                  className="text-sm font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] truncate block hover:underline"
                >
                  {v}
                </Link>
              )}
            />
            <p className="text-xs text-[var(--color-text-muted)] mt-px">
              Last seen <RelativeTime iso={device.last_seen} />
              {!isOwner && <span className="ml-[var(--spacing-2)]">· shared</span>}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setConfirmDelete(true)}
            aria-label={`Remove ${deviceLabel}`}
            className="shrink-0 text-[var(--color-text-muted)] hover:text-[var(--color-error)] hover:bg-[var(--color-error-subtle)]"
          >
            <Trash2 size={15} />
          </Button>
        </div>

        {device.client_type === 'romm' ? <RommProfileRow /> : <ProfilesInCard device={device} />}

        {isOwner && (
          <>
            <SharePanel deviceId={device.device_id} />
            <AccessList deviceId={device.device_id} />
          </>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={`Remove ${device.display_name ?? device.device_id.slice(0, 8)}?`}
        description="This client will no longer sync saves with OmniSave. Your existing saves on the server are not deleted."
        confirmLabel="Remove Client"
        variant="destructive"
        loading={del.isPending}
        error={del.isError ? 'Failed to remove client' : null}
        onConfirm={() => del.mutate()}
      />
    </>
  )
}

// ── Pair a new device ─────────────────────────────────────────────────────────

export function PairNewDevice() {
  const location = useLocation()
  const sectionRef = React.useRef<HTMLElement>(null)
  const [flashing, setFlashing] = React.useState(false)
  React.useEffect(() => {
    if (location.hash !== '#pair-device') return
    sectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setFlashing(true)
    const t = setTimeout(() => setFlashing(false), 1400)
    return () => clearTimeout(t)
  }, [location.hash, location.key])

  const qc = useQueryClient()
  const [code, setCode] = React.useState('')
  const [err, setErr] = React.useState('')
  const [paired, setPaired] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)

  const pair = async () => {
    const c = code.trim().toUpperCase()
    if (c.length !== 6) { setErr('Code must be 6 characters'); return }
    setBusy(true); setErr(''); setPaired(null)
    try {
      const { display_name, device_id } = await api.pairByCode(c)
      setPaired(display_name ?? device_id)
      setCode('')
      await qc.invalidateQueries({ queryKey: ['devices'] })
    } catch {
      setErr('Invalid or expired pairing code')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section id="pair-device" ref={sectionRef} className={cn('flex flex-col gap-[var(--spacing-4)]', flashing && 'animate-section-flash')}>
      <div className="flex min-h-8 items-center">
        <h2 className={SECTION_H2}>Pair a New Device</h2>
      </div>
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] p-[var(--spacing-4)] flex flex-col gap-[var(--spacing-3)]">
        <p className="text-xs text-[var(--color-text-muted)]">
          Enter the 6-character code shown in the OmniSave overlay on your Switch.
        </p>
        {err && (
          <p role="alert" className="text-sm text-[var(--color-error)]">{err}</p>
        )}
        {paired && (
          <div className="flex items-center gap-[var(--spacing-2)] text-sm text-[var(--color-success)]">
            <Check size={14} />
            <span>Paired with <span className="font-mono">{paired}</span></span>
          </div>
        )}
        <div className="flex gap-[var(--spacing-2)]">
          <Input
            placeholder="ABC123"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && void pair()}
            maxLength={6}
            className="w-32 font-mono tracking-widest uppercase text-center"
            aria-label="Pairing code"
          />
          <Button size="sm" onClick={() => void pair()} disabled={busy || code.trim().length !== 6}>
            {busy ? 'Pairing…' : 'Pair Device'}
          </Button>
        </div>
      </div>
    </section>
  )
}

// ── Accept a share code ───────────────────────────────────────────────────────

export function AcceptShareCode() {
  const location = useLocation()
  const sectionRef = React.useRef<HTMLElement>(null)
  const [flashing, setFlashing] = React.useState(false)
  React.useEffect(() => {
    if (location.hash !== '#shared-device') return
    sectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setFlashing(true)
    const t = setTimeout(() => setFlashing(false), 1400)
    return () => clearTimeout(t)
  }, [location.hash, location.key])

  const qc = useQueryClient()
  const [code, setCode] = React.useState('')
  const [err, setErr] = React.useState('')
  const [joined, setJoined] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)

  const accept = async () => {
    const c = code.trim().toUpperCase()
    if (c.length !== 6) { setErr('Code must be 6 characters'); return }
    setBusy(true); setErr(''); setJoined(null)
    try {
      const { display_name, device_id } = await api.acceptShare(c)
      setJoined(display_name ?? device_id)
      setCode('')
      await qc.invalidateQueries({ queryKey: ['devices'] })
    } catch {
      setErr('Invalid or expired share code')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section id="shared-device" ref={sectionRef} className={cn('flex flex-col gap-[var(--spacing-4)]', flashing && 'animate-section-flash')}>
      <div className="flex min-h-8 items-center">
        <h2 className={SECTION_H2}>Shared OmniSave User Device</h2>
      </div>
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] p-[var(--spacing-4)] flex flex-col gap-[var(--spacing-3)]">
        <p className="text-xs text-[var(--color-text-muted)]">
          Enter a share code from a device owner to gain access to your device profile and sync your saves.
        </p>
        {err && (
          <p role="alert" className="text-sm text-[var(--color-error)]">{err}</p>
        )}
        {joined && (
          <div className="flex items-center gap-[var(--spacing-2)] text-sm text-[var(--color-success)]">
            <Check size={14} />
            <span>Access granted for <span className="font-mono">{joined}</span></span>
          </div>
        )}
        <div className="flex gap-[var(--spacing-2)]">
          <Input
            placeholder="XYZ789"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && void accept()}
            maxLength={6}
            className="w-32 font-mono tracking-widest uppercase text-center"
            aria-label="Share code"
          />
          <Button size="sm" onClick={() => void accept()} disabled={busy || code.trim().length !== 6}>
            {busy ? 'Joining…' : 'Join Device'}
          </Button>
        </div>
      </div>
    </section>
  )
}

// ── My Clients ────────────────────────────────────────────────────────────────

export function MyDevicesSection() {
  const { username } = useAuth()
  const location = useLocation()
  const sectionRef = React.useRef<HTMLElement>(null)
  const [flashing, setFlashing] = React.useState(false)

  React.useEffect(() => {
    if (location.hash !== '#my-clients') return
    sectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setFlashing(true)
    const t = setTimeout(() => setFlashing(false), 1400)
    return () => clearTimeout(t)
  }, [location.hash, location.key])

  const { data, isLoading } = useQuery({
    queryKey: ['devices'],
    queryFn: () => api.devices(),
    staleTime: 30_000,
  })
  const devices: Device[] = (data?.devices ?? []).filter((d) => !d.is_deleted)

  return (
    <section
      id="my-clients"
      ref={sectionRef}
      className={cn('flex flex-col gap-[var(--spacing-4)]', flashing && 'animate-section-flash')}
    >
      <div className="flex min-h-8 items-center">
        <h2 className={SECTION_H2}>My Clients</h2>
      </div>
      {isLoading ? (
        <div className="flex flex-col gap-[var(--spacing-3)]">
          {[0, 1].map((i) => <Skeleton key={i} className="h-20 w-full rounded-[var(--radius-lg)]" />)}
        </div>
      ) : devices.length === 0 ? (
        <p className="text-sm text-[var(--color-text-muted)]">
          No devices yet. Pair one below.
        </p>
      ) : (
        <div className="flex flex-col gap-[var(--spacing-3)]">
          {devices.map((d) => (
            <DeviceCard key={d.device_id} device={d} isOwner={d.owner_user_id === username} />
          ))}
        </div>
      )}
    </section>
  )
}


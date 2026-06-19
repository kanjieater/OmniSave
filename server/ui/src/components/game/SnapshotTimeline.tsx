import { AlertCircle, Download, ExternalLink, Search, Trash2, Upload } from 'lucide-react'
import { ICON_BASE, ICON_NAV, ICON_SM } from '@/lib/ui-scale'
import * as React from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api'
import type { Device, DeviceProfile, DeviceSyncEntry, GameDetail, Snapshot } from '@/types'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DeviceStatusIndicator } from '@/components/ui/device-status-indicator'
import { GameIcon } from '@/components/ui/game-icon'
import { HardwareIcon } from '@/components/ui/hardware-icon'
import { IdDisplay } from '@/components/ui/id-display'
import { InlineEdit } from '@/components/ui/inline-edit'
import { RelativeTime } from '@/components/ui/relative-time'
import { Separator } from '@/components/ui/separator'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { getDisplayState, SYNC_STYLE } from '@/lib/syncState'

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const STATE_LABEL: Record<string, { text: string; muted: boolean }> = {
  SUPERSEDED: { text: 'Superseded', muted: true },
  PERSISTED:  { text: 'Pending',    muted: false },
}

function prepareHistory(snapshots: Snapshot[]) {
  const head = snapshots.find((s) => s.is_head) ?? snapshots[0] ?? null
  const all = [...snapshots].sort((a, b) => {
    if (a.sequence_num !== null && b.sequence_num !== null) return b.sequence_num - a.sequence_num
    if (a.sequence_num !== null) return -1
    if (b.sequence_num !== null) return 1
    return new Date(b.ingest_timestamp).getTime() - new Date(a.ingest_timestamp).getTime()
  })
  return { head, all }
}

// ── Device sync pills — uses shared SYNC_STYLE + getDisplayState from lib/syncState ──

function SyncPills({ matrix, titleId }: { matrix: DeviceSyncEntry[]; titleId: string }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const retry = useMutation({
    mutationFn: (txnId: string) => api.retryOutbound(txnId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['game', titleId] }),
  })
  const hasVisible = matrix.some((d) => getDisplayState(d.sync_state, d.pending_delivery, d.sync_enabled) !== null)
  if (!hasVisible) return null
  return (
    <div className="flex flex-wrap gap-[var(--spacing-2)] -ml-[var(--spacing-2)]">
      {matrix.map((d) => {
        const state = getDisplayState(d.sync_state, d.pending_delivery, d.sync_enabled)
        if (!state) return null
        const cfg = SYNC_STYLE[state]
        const name = d.device_name ?? d.device_id.slice(0, 8)
        return (
          <Tooltip key={d.device_id}>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); navigate(`/devices/${d.device_id}`) }}
                className={cn(
                  'inline-flex items-center gap-[var(--spacing-1)] text-base',
                  'px-[var(--spacing-2)] py-[2px] rounded-[var(--radius-sm)] cursor-pointer',
                  'bg-[var(--color-bg-elevated)] text-[var(--color-text-muted)]',
                  'hover:text-[var(--color-text-primary)] hover:brightness-110',
                  'transition-[filter,color] duration-[var(--motion-duration-fast)]',
                  !d.sync_enabled && 'opacity-50',
                )}
              >
                <HardwareIcon clientType={d.client_type} hardwareType={d.hardware_type} size={14} />
                <span>{name}{cfg.label ? `: ${cfg.label}` : ''}</span>
                <span className={cn('w-2 h-2 rounded-full shrink-0', cfg.dot)} />
              </button>
            </TooltipTrigger>
            <TooltipContent>
              <span>{cfg.tip}</span>
              {d.last_synced_at && (
                <span className="block text-xs opacity-70 mt-[2px]">
                  Last synced <RelativeTime iso={d.last_synced_at} />
                </span>
              )}
              {state === 'DELIVERY_FAILED' && d.failed_transaction_id && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); retry.mutate(d.failed_transaction_id!) }}
                  disabled={retry.isPending}
                  className="mt-[4px] flex items-center gap-[4px] text-xs text-[var(--color-accent)] hover:underline disabled:opacity-50"
                >
                  <Upload size={9} className={retry.isPending ? 'animate-pulse' : ''} />
                  {retry.isPending ? 'Pushing…' : 'Push'}
                </button>
              )}
            </TooltipContent>
          </Tooltip>
        )
      })}
    </div>
  )
}

// ── Game + Latest save unified card ───────────────────────────────────────────
// snap may be null when the game exists but has no confirmed HEAD yet.

function SnapshotHeadCard({
  snap, matrix, gameName, gameIconUrl, onSaveGameName, onRommSearch, deviceMap,
  rommEnabled, rommHost, rommId, titleId,
}: {
  snap: Snapshot | null
  matrix: DeviceSyncEntry[]
  gameName: string
  gameIconUrl: string | null | undefined
  onSaveGameName: (name: string) => Promise<void>
  onRommSearch: () => void
  deviceMap: Map<string, Device>
  rommEnabled?: boolean
  rommHost?: string | null
  rommId?: number | null
  titleId: string
}) {
  const navigate = useNavigate()
  const device = snap ? (snap.device_name ?? snap.device_id.slice(0, 8)) : null

  // Always show source device in sync pills — add it as SYNCED if missing or
  // override NO_DELIVERY (source always has the save locally).
  const augmentedMatrix = React.useMemo((): DeviceSyncEntry[] => {
    if (!snap) return matrix
    const idx = matrix.findIndex((d) => d.device_id === snap.device_id)
    if (idx === -1) {
      return [...matrix, {
        device_id: snap.device_id,
        device_name: snap.device_name ?? null,
        last_seen: deviceMap.get(snap.device_id)?.last_seen ?? null,
        hardware_type: deviceMap.get(snap.device_id)?.hardware_type ?? null,
        client_type: deviceMap.get(snap.device_id)?.client_type ?? null,
        sync_state: 'SYNCED' as const,
        local_sequence: snap.sequence_num ?? null,
        cloud_head_sequence: snap.sequence_num ?? null,
        sync_enabled: true,
        pending_delivery: false,
        last_synced_at: snap.ingest_timestamp,
        failed_transaction_id: null,
      }]
    }
    if (matrix[idx].sync_state === 'NO_DELIVERY') {
      const updated = [...matrix]
      updated[idx] = {
        ...updated[idx],
        sync_state: 'SYNCED' as const,
        local_sequence: snap.sequence_num ?? null,
        hardware_type: deviceMap.get(snap.device_id)?.hardware_type ?? null,
        client_type: deviceMap.get(snap.device_id)?.client_type ?? null,
      }
      return updated
    }
    return matrix
  }, [matrix, snap, deviceMap])

  const titleActions = (
    <div className="flex items-start gap-[var(--spacing-1)]">
      <InlineEdit
        value={gameName}
        onSave={onSaveGameName}
        editLabel="Edit game name"
        className="flex-1 min-w-0 w-full"
        renderValue={(v) => (
          <span className="text-sm font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] leading-tight truncate block">{v}</span>
        )}
      />
      {rommEnabled && rommId && rommHost && (
        <a
          href={`${rommHost.replace(/\/$/, '')}/rom/${rommId}`}
          target="_blank"
          rel="noopener noreferrer"
          className="h-[var(--touch-nav)] w-[var(--touch-nav)] shrink-0 inline-flex items-center justify-center rounded-[var(--radius-md)] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors duration-[var(--motion-duration-fast)]"
          aria-label="Open in RomM"
        >
          <ExternalLink size={ICON_BASE} />
        </a>
      )}
      {rommEnabled && (
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onRommSearch}
          aria-label="Link to RomM library"
          className="shrink-0"
        >
          <Search size={ICON_NAV} />
        </Button>
      )}
    </div>
  )

  return (
    <div className="border border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] rounded-[var(--radius-lg)] flex flex-col gap-[var(--spacing-3)] p-[var(--spacing-3)]">
      {/* Mobile: title + actions full-width at top */}
      <div className="md:hidden">
        {titleActions}
      </div>

      {/* Image + content row */}
      <div className="flex gap-[var(--spacing-3)] items-start">
        {/* Game cover */}
        <div className="relative w-1/2 md:w-40 aspect-[3/4] shrink-0 rounded-[var(--radius-md)] overflow-hidden bg-[var(--color-bg-elevated)]">
          <GameIcon
            iconUrl={gameIconUrl}
            name={gameName}
            size="full"
            className="w-full h-full object-cover"
          />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 flex flex-col gap-[var(--spacing-4)] py-[var(--spacing-1)]">
          {/* Desktop: title + actions inside content column */}
          <div className="hidden md:block">
            {titleActions}
          </div>

          {/* Latest Save + sequence number */}
          <div className="flex flex-col md:flex-row md:items-baseline gap-[var(--spacing-1)] md:gap-[var(--spacing-3)]">
            <p className="text-base text-[var(--color-text-muted)]">
              {snap ? 'Latest Save' : 'No save yet'}
            </p>
            {snap?.sequence_num != null && (
              <span className="font-mono font-[var(--font-weight-bold)] text-[var(--color-text-primary)] tabular-nums leading-none text-lg">
                #{snap.sequence_num}
              </span>
            )}
          </div>

          {/* Catalog source — shown when no save exists yet */}
          {!snap && matrix.length > 0 && (
            <div className="flex flex-wrap items-center gap-[var(--spacing-2)] text-xs">
              {matrix.map((d) => (
                <button
                  key={d.device_id}
                  type="button"
                  onClick={() => navigate(`/devices/${d.device_id}`)}
                  className="flex items-center gap-[var(--spacing-1)] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors duration-[var(--motion-duration-fast)] cursor-pointer"
                >
                  <HardwareIcon clientType={deviceMap.get(d.device_id)?.client_type ?? null} hardwareType={deviceMap.get(d.device_id)?.hardware_type ?? null} size={11} />
                  <span>{d.device_name ?? d.device_id.slice(0, 8)}</span>
                </button>
              ))}
            </div>
          )}

          {/* Save metadata row */}
          {snap && (
            <div className="flex flex-col md:flex-row md:items-center gap-[var(--spacing-2)] md:gap-[var(--spacing-4)] text-base">
              <button
                type="button"
                onClick={() => navigate(`/devices/${snap.device_id}`)}
                className="flex items-center gap-[var(--spacing-2)] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors duration-[var(--motion-duration-fast)] cursor-pointer"
              >
                <HardwareIcon clientType={deviceMap.get(snap.device_id)?.client_type ?? null} hardwareType={deviceMap.get(snap.device_id)?.hardware_type ?? null} size={13} />
                {device}
              </button>
              {snap.archive_size_bytes != null && (
                <span className="text-[var(--color-text-muted)]">{formatBytes(snap.archive_size_bytes)}</span>
              )}
              <span className="text-[var(--color-text-muted)]">
                <RelativeTime iso={snap.ingest_timestamp} />
              </span>
            </div>
          )}

          {/* Desktop: sync pills inside content column */}
          <div className="hidden md:block">
            <SyncPills matrix={augmentedMatrix} titleId={titleId} />
          </div>
        </div>
      </div>

      {/* Mobile: badges as a full-width row below image+content */}
      <div className="md:hidden">
        <SyncPills matrix={augmentedMatrix} titleId={titleId} />
      </div>
    </div>
  )
}

// ── Archive table ─────────────────────────────────────────────────────────────

function SnapshotArchiveTable({
  snapshots, onSelect, deviceMap, newTxnIds,
}: {
  snapshots: Snapshot[]
  onSelect: (snap: Snapshot) => void
  deviceMap: Map<string, Device>
  newTxnIds: Set<string>
}) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] overflow-x-auto bg-[var(--color-bg-subtle)]">
      <table className="w-full text-base">
        <thead>
          <tr className="border-b border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)]">
            {['#', 'Device', 'Profile', 'Size', 'When'].map((h, i) => (
              <th
                key={h}
                scope="col"
                className={cn(
                  'px-[var(--spacing-4)] py-[var(--spacing-2)] text-sm font-[var(--font-weight-medium)] text-[var(--color-text-muted)]',
                  i === 0 ? 'text-right w-14' : 'text-left',
                  i === 3 ? 'text-right' : '',
                )}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {snapshots.map((snap) => {
            const device = snap.device_name ?? snap.device_id.slice(0, 8)
            return (
              <tr
                key={snap.transaction_id}
                onClick={() => onSelect(snap)}
                className={cn('border-b border-[var(--color-border-subtle)] last:border-b-0 hover:bg-[var(--color-bg-hover)] cursor-pointer transition-colors duration-[var(--motion-duration-fast)]', newTxnIds.has(snap.transaction_id) && 'animate-row-new')}
              >
                <td className="px-[var(--spacing-4)] py-[var(--spacing-3)] font-mono text-[var(--color-text-muted)] text-right whitespace-nowrap">
                  {snap.sequence_num != null
                    ? `#${snap.sequence_num}`
                    : (() => {
                        const lbl = STATE_LABEL[snap.state]
                        return lbl ? (
                          <span className={cn(
                            'text-[0.65rem] font-[var(--font-weight-medium)] uppercase tracking-wide',
                            lbl.muted ? 'text-[var(--color-text-muted)]' : 'text-[var(--color-info)]',
                          )}>{lbl.text}</span>
                        ) : '—'
                      })()
                  }
                </td>
                <td className="px-[var(--spacing-4)] py-[var(--spacing-3)] text-[var(--color-text-primary)] whitespace-nowrap">
                  <span className="flex items-center gap-[var(--spacing-1)]">
                    <HardwareIcon clientType={deviceMap.get(snap.device_id)?.client_type ?? null} hardwareType={deviceMap.get(snap.device_id)?.hardware_type ?? null} size={11} />
                    {device}
                  </span>
                </td>
                <td className="px-[var(--spacing-4)] py-[var(--spacing-3)] text-[var(--color-text-muted)] whitespace-nowrap">
                  {snap.owner_user_id ?? <span className="opacity-40">—</span>}
                </td>
                <td className="px-[var(--spacing-4)] py-[var(--spacing-3)] text-[var(--color-text-muted)] text-right whitespace-nowrap">
                  <div className="flex flex-col items-end gap-[0.1rem]">
                    {snap.sha256 ? (
                      <span className="font-mono text-[0.6rem] opacity-50 leading-none">
                        {snap.sha256.slice(0, 8)}
                      </span>
                    ) : null}
                    <span>{snap.archive_size_bytes != null ? formatBytes(snap.archive_size_bytes) : '—'}</span>
                  </div>
                </td>
                <td className="px-[var(--spacing-4)] py-[var(--spacing-3)] text-[var(--color-text-muted)] whitespace-nowrap">
                  <RelativeTime iso={snap.ingest_timestamp} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Push section (inside details sheet) ───────────────────────────────────────

function DeviceProfilePicker({
  device,
  value,
  onChange,
}: {
  device: Device
  value: string | null
  onChange: (uid: string | null) => void
}) {
  const { data } = useQuery({
    queryKey: ['deviceProfiles', device.device_id],
    queryFn: () => api.deviceProfiles(device.device_id),
    staleTime: 60_000,
  })
  const profiles = (data?.profiles ?? [] as DeviceProfile[])

  const profileLabel = (p: DeviceProfile) =>
    p.profile_name || p.display_hint || p.profile_id.slice(0, 8)

  const defaultProfile = profiles.find((p) => p.profile_id === device.default_profile_uid)
  const defaultLabel = device.default_profile_name
    ? `${device.default_profile_name} — Default`
    : defaultProfile
      ? `${profileLabel(defaultProfile)} — Default`
      : device.device_id.startsWith('romm:')
        ? device.device_id.slice(5)
        : 'Default'

  // The default SelectItem's value is the actual UID when known, else the sentinel.
  // This lets the Select match whether the caller passed null or the real UID.
  const defaultItemValue = device.default_profile_uid ?? '__default__'
  const selectValue = (value === null || value === device.default_profile_uid)
    ? defaultItemValue
    : value

  return (
    <div className="flex items-center gap-[var(--spacing-3)] pt-[var(--spacing-2)] mt-[var(--spacing-2)] border-t border-[var(--color-border-subtle)]">
      <span className="text-xs text-[var(--color-text-muted)] shrink-0 w-12">Profile</span>
      <Select
        value={selectValue}
        onValueChange={(v) => onChange(v === defaultItemValue ? null : v)}
      >
        <SelectTrigger className="h-[var(--touch-sm)] text-xs flex-1 min-w-0 bg-[var(--color-accent-subtle)] border-[var(--color-accent)]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={defaultItemValue}>{defaultLabel}</SelectItem>
          {profiles.filter((p) => p.profile_id !== device.default_profile_uid).map((p) => (
            <SelectItem key={p.profile_id} value={p.profile_id}>
              {profileLabel(p)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function PushSection({ snap, titleId, onDone }: { snap: Snapshot; titleId: string; onDone: () => void }) {
  const qc = useQueryClient()

  const { data: devicesData, isLoading } = useQuery({
    queryKey: ['devices'],
    queryFn: () => api.devices(),
  })

  const allDevices: Device[] = (devicesData?.devices ?? []).filter((d) => !d.is_deleted)
  const [selected, setSelected] = React.useState<Set<string>>(new Set())
  const [profileOverrides, setProfileOverrides] = React.useState<Map<string, string | null>>(new Map())

  React.useEffect(() => {
    if (allDevices.length > 0) {
      const overrides = new Map<string, string | null>()
      allDevices.forEach((d) => overrides.set(d.device_id, d.default_profile_uid ?? null))
      setProfileOverrides(overrides)
    }
  }, [devicesData]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (id: string) =>
    setSelected((prev) => { const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s })

  const allSelected = allDevices.length > 0 && allDevices.every((d) => selected.has(d.device_id))
  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set(allDevices.map((d) => d.device_id)))

  const push = useMutation({
    mutationFn: () => api.pushSnapshot(
      snap.transaction_id,
      [...selected].map((id) => ({ device_id: id, target_profile_uid: profileOverrides.get(id) ?? null })),
    ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['game', titleId] })
      onDone()
    },
  })

  const count = selected.size
  const label = push.isPending ? 'Pushing…' : count === 0 ? 'Select a client' : count === 1 ? 'Push to 1 client' : `Push to ${count} clients`

  if (isLoading) return <p className="text-xs text-[var(--color-text-muted)]">Loading clients…</p>
  if (!allDevices.length) return <p className="text-xs text-[var(--color-text-muted)]">No clients registered.</p>

  return (
    <div className="flex flex-col gap-[var(--spacing-3)]">
      <button type="button" onClick={toggleAll}
        className="text-xs text-[var(--color-accent)] hover:underline text-left w-fit">
        {allSelected ? 'Deselect all' : 'Select all'}
      </button>
      <div className="flex flex-col gap-[var(--spacing-2)]">
        {allDevices.map((device) => {
          const checked = selected.has(device.device_id)
          return (
            <div
              key={device.device_id}
              className={cn(
                'rounded-[var(--radius-md)] border transition-colors duration-[var(--motion-duration-fast)]',
                checked
                  ? 'border-[var(--color-accent)] bg-[var(--color-accent-subtle)]'
                  : 'border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] hover:border-[var(--color-border-base)]',
              )}
            >
              <label className="flex items-center gap-[var(--spacing-3)] px-[var(--spacing-3)] py-[var(--spacing-2)] cursor-pointer">
                <input type="checkbox" checked={checked} onChange={() => toggle(device.device_id)}
                  disabled={push.isPending} className="w-4 h-4 accent-[var(--color-accent)] shrink-0"
                  aria-label={`Push to ${device.display_name ?? device.device_id}`} />
                <HardwareIcon clientType={device.client_type} hardwareType={device.hardware_type} size={14} />
                <span className="flex-1 min-w-0 text-sm text-[var(--color-text-primary)] truncate">
                  {device.display_name ?? <span className="font-mono">{device.device_id.slice(0, 10)}</span>}
                </span>
                <DeviceStatusIndicator lastSeen={device.last_seen} />
              </label>
              {checked && (
                <div className="px-[var(--spacing-3)] pb-[var(--spacing-2)]">
                  <DeviceProfilePicker
                    device={device}
                    value={profileOverrides.get(device.device_id) ?? null}
                    onChange={(uid) => setProfileOverrides((prev) => new Map(prev).set(device.device_id, uid))}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
      {push.isError && (
        <div className="flex items-start gap-[var(--spacing-2)] p-[var(--spacing-3)] rounded-[var(--radius-md)] bg-[var(--color-error-subtle)] border border-[var(--color-error-border)]" role="alert">
          <AlertCircle size={ICON_BASE} className="text-[var(--color-error)] shrink-0 mt-[1px]" aria-hidden="true" />
          <p className="text-xs text-[var(--color-error-text)]">
            {push.error instanceof Error ? push.error.message : 'Push failed — please try again.'}
          </p>
        </div>
      )}
      <Button onClick={() => push.mutate()} disabled={count === 0 || push.isPending} size="sm" className="w-full">
        <Upload size={ICON_SM} />
        {label}
      </Button>
    </div>
  )
}

// ── Details sheet ─────────────────────────────────────────────────────────────

function _fmtTs(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}_${p(d.getUTCHours())}-${p(d.getUTCMinutes())}-${p(d.getUTCSeconds())}`
}

function SnapshotDetailsSheet({
  snap, open, onClose, titleId, gameName, onDeleted,
}: {
  snap: Snapshot | null
  open: boolean
  onClose: () => void
  titleId: string
  gameName: string
  onDeleted: (txnId: string) => void
}) {
  const [confirmDelete, setConfirmDelete] = React.useState(false)
  const [dlBusy, setDlBusy] = React.useState(false)
  const [dlErr, setDlErr] = React.useState<string | null>(null)
  const del = useMutation({
    mutationFn: (id: string) => api.deleteSnapshot(id),
    onSuccess: (_, txnId) => { setConfirmDelete(false); onClose(); onDeleted(txnId) },
  })

  const handleDownload = async () => {
    if (dlBusy || !snap) return
    setDlBusy(true); setDlErr(null)
    try {
      await api.downloadSnapshot(snap.transaction_id)
    } catch (e) {
      setDlErr(e instanceof Error ? e.message : 'Download failed')
    } finally {
      setDlBusy(false)
    }
  }

  const handleClose = () => { if (!del.isPending) { setConfirmDelete(false); del.reset(); onClose() } }

  if (!snap) return null
  return (
    <>
      <Sheet open={open} onOpenChange={(v) => { if (!v) handleClose() }}>
        <SheetContent side="right" className="flex flex-col" onOpenAutoFocus={(e) => e.preventDefault()}>
          <SheetHeader>
            <SheetTitle>
              {snap.sequence_num != null ? `Save #${snap.sequence_num}` : 'Save Details'}
            </SheetTitle>
          </SheetHeader>

          <div className="flex flex-col gap-[var(--spacing-4)] px-[var(--spacing-5)] py-[var(--spacing-4)] flex-1 min-h-0 overflow-y-auto">
            <div className="flex flex-col gap-[var(--spacing-2)]">
              {(
                [
                  ['Device', snap.device_name ?? snap.device_id.slice(0, 8)],
                  ['Saved', <RelativeTime key="t" iso={snap.ingest_timestamp} format="absolute" />],
                  snap.archive_size_bytes != null ? ['Size', formatBytes(snap.archive_size_bytes)] : null,
                  ['SHA256', <IdDisplay key="sha" id={snap.sha256} chars={16} label="SHA256" />],
                ] as [string, React.ReactNode][]
              ).filter(Boolean).map(([label, value]) => (
                <div key={label as string} className="flex items-start justify-between gap-[var(--spacing-4)] py-[var(--spacing-1)] border-b border-[var(--color-border-subtle)] last:border-b-0">
                  <span className="text-xs text-[var(--color-text-muted)] shrink-0 pt-[1px]">{label}</span>
                  <span className="text-xs text-[var(--color-text-primary)] text-right break-all">{value}</span>
                </div>
              ))}
            </div>

            <Button variant="secondary" size="sm" className="w-full" onClick={() => void handleDownload()} disabled={dlBusy}>
              <Download size={ICON_SM} className="shrink-0" />
              <span className="truncate min-w-0">{dlBusy ? 'Downloading…' : `Download ${gameName} [${_fmtTs(snap.ingest_timestamp)}].zip`}</span>
            </Button>
            {dlErr && (
              <div role="alert" className="text-sm text-[var(--color-error)] bg-[var(--color-error-subtle)] border border-[var(--color-error-border)] rounded-[var(--radius-md)] px-[var(--spacing-3)] py-[var(--spacing-2)]">
                {dlErr}
              </div>
            )}

            <Separator />

            <div className="flex flex-col gap-[var(--spacing-3)]">
              <p className="text-xs font-[var(--font-weight-semibold)] text-[var(--color-text-muted)] uppercase tracking-[0.06em]">
                Send to device
              </p>
              <PushSection snap={snap} titleId={titleId} onDone={onClose} />
            </div>

            <Separator />

            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmDelete(true)}
              className="w-full text-[var(--color-error)] hover:bg-[var(--color-error-subtle)] hover:text-[var(--color-error)]"
            >
              <Trash2 size={ICON_SM} />
              Delete this snapshot
            </Button>
          </div>
        </SheetContent>
      </Sheet>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={(v) => { if (!v) { setConfirmDelete(false); del.reset() } }}
        title={`Delete Save #${snap.sequence_num ?? ''}?`}
        description="This save will be permanently removed from the server. This cannot be undone."
        confirmLabel="Delete"
        variant="destructive"
        loading={del.isPending}
        error={del.isError ? (del.error instanceof Error ? del.error.message : 'Delete failed') : null}
        onConfirm={() => del.mutate(snap.transaction_id)}
      />
    </>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export interface SnapshotTimelineProps {
  data: GameDetail
  titleId: string
  gameName: string
  gameIconUrl: string | null | undefined
  onSaveGameName: (name: string) => Promise<void>
  onRommSearch: () => void
  rommEnabled?: boolean
  rommHost?: string | null
}

export function SnapshotTimeline({
  data, titleId, gameName, gameIconUrl, onSaveGameName, onRommSearch, rommEnabled, rommHost,
}: SnapshotTimelineProps) {
  const qc = useQueryClient()
  const [selected, setSelected] = React.useState<Snapshot | null>(null)
  const [visibleCount, setVisibleCount] = React.useState(500)
  const prevTxnIds = React.useRef<Set<string>>(new Set())
  const [newTxnIds, setNewTxnIds] = React.useState<Set<string>>(new Set())

  React.useEffect(() => {
    const current = new Set(data.snapshots.map((s) => s.transaction_id))
    if (prevTxnIds.current.size > 0) {
      const incoming = new Set<string>()
      current.forEach((id) => { if (!prevTxnIds.current.has(id)) incoming.add(id) })
      if (incoming.size > 0) setNewTxnIds(incoming)
    }
    prevTxnIds.current = current
  }, [data.snapshots])

  const { data: devicesData } = useQuery({
    queryKey: ['devices'],
    queryFn: () => api.devices(),
    staleTime: 60_000,
  })
  const deviceMap = React.useMemo(() => {
    const m = new Map<string, Device>()
    for (const d of devicesData?.devices ?? []) m.set(d.device_id, d)
    return m
  }, [devicesData])

  // Intercept browser back button to close the details sheet instead of navigating away
  React.useEffect(() => {
    if (!selected) return
    window.history.pushState(null, '', window.location.href)
    const handler = () => setSelected(null)
    window.addEventListener('popstate', handler)
    return () => window.removeEventListener('popstate', handler)
  }, [selected])

  const handleDeleted = (txnId: string) => {
    qc.setQueryData<GameDetail>(['game', titleId], (old) =>
      old ? { ...old, snapshots: old.snapshots.filter((s) => s.transaction_id !== txnId) } : old,
    )
    void qc.invalidateQueries({ queryKey: ['game', titleId] })
  }

  const { head, all } = prepareHistory(data.snapshots)

  return (
    <>
      <SnapshotHeadCard
        snap={head}
        matrix={data.device_sync_matrix}
        gameName={gameName}
        gameIconUrl={gameIconUrl}
        onSaveGameName={onSaveGameName}
        onRommSearch={onRommSearch}
        deviceMap={deviceMap}
        rommEnabled={rommEnabled}
        rommHost={rommHost}
        rommId={data.rom_id}
        titleId={titleId}
      />

      {all.length > 0 && (
        <section className="flex flex-col gap-[var(--spacing-3)]">
          <h2 className="text-xs font-[var(--font-weight-semibold)] text-[var(--color-text-muted)] uppercase tracking-[var(--tracking-wide)]">
            All Saves
          </h2>
          <SnapshotArchiveTable snapshots={all.slice(0, visibleCount)} onSelect={setSelected} deviceMap={deviceMap} newTxnIds={newTxnIds} />
          {all.length > visibleCount && (
            <div className="flex justify-center">
              <Button variant="ghost" size="sm" onClick={() => setVisibleCount((n) => n + 500)}>
                Load more saves
              </Button>
            </div>
          )}
        </section>
      )}

      <SnapshotDetailsSheet
        snap={selected}
        open={!!selected}
        onClose={() => setSelected(null)}
        titleId={titleId}
        gameName={gameName}
        onDeleted={handleDeleted}
      />
    </>
  )
}

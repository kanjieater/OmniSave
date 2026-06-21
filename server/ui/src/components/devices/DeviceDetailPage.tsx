import { Download, Loader2, RefreshCw, Search, Settings, Upload } from 'lucide-react'
import * as React from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api'
import type { Device, DeviceGame, DeviceProfile } from '@/types'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { DeviceStatusIndicator } from '@/components/ui/device-status-indicator'
import { EmptyState } from '@/components/ui/empty-state'
import { GameIcon } from '@/components/ui/game-icon'
import { Switch } from '@/components/ui/switch'
import { HardwareIcon } from '@/components/ui/hardware-icon'
import { IdDisplay } from '@/components/ui/id-display'
import { InlineEdit } from '@/components/ui/inline-edit'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { getDisplayState, isPendingDelivery, SYNC_STYLE, SYNC_SORT_ORDER } from '@/lib/syncState'
import type { DashboardData } from '@/types'
import { useBackground } from '@/components/layout/AppShellV2'

function SyncCard({ game, deviceId, queryKey }: { game: DeviceGame; deviceId: string; queryKey: unknown[] }) {
  const qc = useQueryClient()
  const [localEnabled, setLocalEnabled] = React.useState(game.sync_enabled)
  const [pending, setPending] = React.useState(false)

  React.useEffect(() => { setLocalEnabled(game.sync_enabled) }, [game.sync_enabled])

  const label = game.display_name ?? game.title_id
  const dotState = getDisplayState(game.sync_state, game.pending_delivery, true)

  const handleToggle = async (next: boolean) => {
    setLocalEnabled(next)
    setPending(true)
    try {
      await api.setSyncPrefs(deviceId, [{ title_id: game.title_id, enabled: next }])
      await qc.invalidateQueries({ queryKey })
    } catch {
      setLocalEnabled(!next)
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="flex flex-col gap-[var(--spacing-2)]">
      {/* Cover — always links to game; dims when sync disabled */}
      <Link
        to={`/game/${game.title_id}`}
        className={cn(
          'relative w-full aspect-[3/4] rounded-[var(--radius-md)] overflow-hidden',
          'bg-[var(--color-bg-elevated)]',
          'transition-[box-shadow,opacity,filter] duration-[var(--motion-duration-fast)]',
          'hover:shadow-[0_0_0_1px_rgba(255,255,255,0.35)]',
          !localEnabled && 'opacity-40 grayscale',
        )}
      >
        <GameIcon iconUrl={game.icon_url} name={label} size="full" className="w-full h-full object-cover" />
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              style={{ boxShadow: '0 0 0 2px var(--color-bg-base)' }}
              className={cn(
                'absolute bottom-1 right-1 w-2.5 h-2.5 rounded-full',
                SYNC_STYLE[dotState ?? 'NO_DELIVERY'].dot,
              )}
              aria-label={SYNC_STYLE[dotState ?? 'NO_DELIVERY'].tip}
            />
          </TooltipTrigger>
          <TooltipContent>{SYNC_STYLE[dotState ?? 'NO_DELIVERY'].tip}</TooltipContent>
        </Tooltip>
      </Link>

      {/* Name + sync radio toggle */}
      <div className="flex items-center gap-[var(--spacing-1)] min-w-0">
        <Link
          to={`/game/${game.title_id}`}
          className="flex-1 text-xs font-[var(--font-weight-medium)] text-[var(--color-text-primary)] truncate min-w-0"
        >
          {game.display_name ?? <span className="font-mono">{game.title_id.slice(0, 10)}…</span>}
        </Link>
        <Switch
          checked={localEnabled}
          onCheckedChange={(v) => void handleToggle(v)}
          loading={pending}
          aria-label={`${localEnabled ? 'Disable' : 'Enable'} sync for ${label}`}
          wrapperClassName="min-h-0 min-w-0"
        />
      </div>

      {/* Time */}
      <p className="text-xs text-[var(--color-text-muted)] -mt-[var(--spacing-1)]">
        {game.last_synced_at ? <RelativeTime iso={game.last_synced_at} /> : 'Never synced'}
      </p>
    </div>
  )
}

export default function DeviceDetailPage() {
  const { device_id } = useParams<{ device_id: string }>()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [disableAllOpen, setDisableAllOpen] = React.useState(false)
  const [restoreAllOpen, setRestoreAllOpen] = React.useState(false)
  const [restoring, setRestoring] = React.useState(false)
  const [visibleGames, setVisibleGames] = React.useState(500)
  const [gameSearch, setGameSearch] = React.useState('')
  const [gameSortKey, setGameSortKey] = useLocalStorage<'name' | 'status' | 'recent'>(`pref:device:${device_id}:sort`, 'recent')

  const devicesKey = ['devices']
  const gamesKey = ['deviceGames', device_id]

  const { data: devicesData, isLoading: devLoading } = useQuery({
    queryKey: devicesKey,
    queryFn: () => api.devices(),
    refetchInterval: 10_000,
  })

  const { data: gamesData, isLoading: gamesLoading, isError: gamesError } = useQuery({
    queryKey: gamesKey,
    queryFn: () => api.deviceGames(device_id!),
    enabled: !!device_id,
    refetchInterval: 10_000,
  })

  const setBg = useBackground()
  const bgPickedRef = React.useRef(false)
  React.useEffect(() => {
    if (bgPickedRef.current) return
    const candidates = (gamesData?.games ?? []).filter(g => g.icon_url)
    if (candidates.length === 0) return
    bgPickedRef.current = true
    setBg(candidates[Math.floor(Math.random() * candidates.length)].icon_url!)
  }, [gamesData, setBg])

  const { data: profilesData } = useQuery({
    queryKey: ['deviceProfiles', device_id],
    queryFn: () => api.deviceProfiles(device_id!),
    enabled: !!device_id,
  })

  const { data: rommSettings, isLoading: isRommLoading } = useQuery({
    queryKey: ['romm-settings'],
    queryFn: () => api.rommServerSettings(),
    staleTime: 60_000,
  })
  const rommEnabled = rommSettings?.enabled ?? false

  const scan = useMutation({ mutationFn: () => api.triggerRommScan() })

  const retryAll = useMutation({
    mutationFn: () => api.retryAllFailed(device_id!),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: gamesKey })
      const prev = qc.getQueryData<{ games: DeviceGame[] }>(gamesKey)
      if (prev) {
        qc.setQueryData(gamesKey, {
          ...prev,
          games: prev.games.map((g) =>
            g.sync_state === 'DELIVERY_FAILED' ? { ...g, sync_state: 'OUT_OF_SYNC' as const } : g
          ),
        })
      }
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(gamesKey, ctx.prev)
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: gamesKey })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const device: Device | undefined = devicesData?.devices.find((d) => d.device_id === device_id)
  const games: DeviceGame[] = gamesData?.games ?? []
  const profiles: DeviceProfile[] = profilesData?.profiles ?? []
  const isLoading = devLoading || gamesLoading

  const filteredGames = React.useMemo(() => {
    let g = games
    const q = gameSearch.trim().toLowerCase()
    if (q) g = g.filter((x) => (x.display_name ?? x.title_id).toLowerCase().includes(q))
    if (gameSortKey === 'recent') g = [...g].sort((a, b) => {
      if (!a.last_synced_at && !b.last_synced_at) return 0
      if (!a.last_synced_at) return 1
      if (!b.last_synced_at) return -1
      return new Date(b.last_synced_at).getTime() - new Date(a.last_synced_at).getTime()
    })
    if (gameSortKey === 'name') g = [...g].sort((a, b) => (a.display_name ?? a.title_id).localeCompare(b.display_name ?? b.title_id))
    if (gameSortKey === 'status') g = [...g].sort((a, b) => {
      const sa = getDisplayState(a.sync_state, a.pending_delivery, true) ?? 'NO_DELIVERY'
      const sb = getDisplayState(b.sync_state, b.pending_delivery, true) ?? 'NO_DELIVERY'
      return (SYNC_SORT_ORDER[sa] ?? 5) - (SYNC_SORT_ORDER[sb] ?? 5)
    })
    return g
  }, [games, gameSearch, gameSortKey])

  const renameDevice = async (name: string) => {
    if (!device_id) return
    if (name.trim()) await api.setDeviceLabel(device_id, name.trim())
    else await api.clearDeviceLabel(device_id)
    await qc.invalidateQueries({ queryKey: devicesKey })
  }

  const restoreAll = async () => {
    if (!device_id || restoring) return
    setRestoreAllOpen(false)
    setRestoring(true)

    await qc.cancelQueries({ queryKey: gamesKey })
    const prevGames = qc.getQueryData<{ games: DeviceGame[] }>(gamesKey)
    if (prevGames) {
      qc.setQueryData(gamesKey, {
        ...prevGames,
        games: prevGames.games.map((g) => ({ ...g, pending_delivery: true })),
      })
    }

    try {
      const result = await api.restoreAll(device_id)
      if (result.queued > 0) {
        const prevDevices = qc.getQueryData<{ devices: Device[] }>(devicesKey)
        if (prevDevices) {
          qc.setQueryData(devicesKey, {
            ...prevDevices,
            devices: prevDevices.devices.map((d) =>
              d.device_id === device_id
                ? { ...d, pending_count: d.pending_count + result.queued }
                : d
            ),
          })
        }
        const prevDash = qc.getQueryData<DashboardData>(['dashboard'])
        if (prevDash) {
          qc.setQueryData<DashboardData>(['dashboard'], {
            ...prevDash,
            stats: { ...prevDash.stats, pending_deliveries: prevDash.stats.pending_deliveries + result.queued },
            devices: prevDash.devices.map((d) =>
              d.device_id === device_id
                ? { ...d, pending_count: d.pending_count + result.queued }
                : d
            ),
          })
        }
      }
      await qc.invalidateQueries({ queryKey: gamesKey })
      await qc.invalidateQueries({ queryKey: ['dashboard'] })
      await qc.invalidateQueries({ queryKey: ['devices'] })
      await qc.invalidateQueries({ queryKey: ['game'], exact: false })
    } catch {
      if (prevGames) qc.setQueryData(gamesKey, prevGames)
    } finally {
      setRestoring(false)
    }
  }

  const enableAll = async () => {
    if (!device_id) return
    await api.setSyncPrefs(device_id, games.map((g) => ({ title_id: g.title_id, enabled: true })))
    await qc.invalidateQueries({ queryKey: gamesKey })
  }

  const disableAll = async () => {
    if (!device_id) return
    await api.setSyncPrefs(device_id, games.map((g) => ({ title_id: g.title_id, enabled: false })))
    await qc.invalidateQueries({ queryKey: gamesKey })
    setDisableAllOpen(false)
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-[var(--spacing-6)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">
        <div className="flex items-center gap-[var(--spacing-4)]">
          <Skeleton className="w-14 h-14 rounded-[var(--radius-xl)] shrink-0" />
          <div className="flex flex-col gap-[var(--spacing-2)] flex-1">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-4 w-56" />
          </div>
        </div>
        <Skeleton className="h-48 w-full rounded-[var(--radius-lg)]" />
      </div>
    )
  }

  if (gamesError) {
    return (
      <div className="flex flex-col gap-[var(--spacing-6)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">
        <EmptyState title="Failed to load games" description="Server error loading this client's game list. Check the server logs for details." />
      </div>
    )
  }

  if (!device || device.is_deleted) return (
    <div className="flex flex-col gap-[var(--spacing-6)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">
      <EmptyState title="Client not found" description="This client may have been removed." />
    </div>
  )

  const deviceLabel = device.display_name ?? device.device_id.slice(0, 8)

  return (
    <div className="flex flex-col gap-[var(--spacing-6)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">

      {/* Device header */}
      <div className="flex items-center gap-[var(--spacing-4)]">
        <div className="flex items-center justify-center w-14 h-14 rounded-[var(--radius-xl)] bg-[var(--color-bg-elevated)] border border-[var(--color-border-subtle)] shrink-0">
          <HardwareIcon clientType={device.client_type} hardwareType={device.hardware_type} size={28} />
        </div>
        <div className="flex-1 min-w-0">
          <InlineEdit
            value={deviceLabel}
            onSave={renameDevice}
            editLabel="Edit client name"
            renderValue={(v) => (
              <h1 className="text-xl font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]">{v}</h1>
            )}
          />
          <div className="flex items-center gap-[var(--spacing-2)] mt-[var(--spacing-1)] text-xs text-[var(--color-text-muted)] flex-wrap">
            <DeviceStatusIndicator lastSeen={device.last_seen} showLabel />
            <span aria-hidden>·</span>
            <span>Last seen <RelativeTime iso={device.last_seen} /></span>
            <span aria-hidden>·</span>
            <IdDisplay id={device.device_id} chars={12} />
          </div>
        </div>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setRestoreAllOpen(true)}
              disabled={restoring}
              aria-label="Restore all available saves to this device"
              className="shrink-0 text-[var(--color-text-muted)]"
            >
              <Download size={16} className={restoring ? 'animate-pulse' : ''} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Restore All</TooltipContent>
        </Tooltip>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => nav('/settings#my-clients')}
          aria-label={`Settings for ${deviceLabel}`}
          className="shrink-0 text-[var(--color-text-muted)]"
        >
          <Settings size={16} />
        </Button>
      </div>

      {/* Sync preferences */}
      <section className="flex flex-col gap-[var(--spacing-4)]">
        <div className="flex min-h-8 items-center justify-between">
          <div>
            <h2 className="text-xs font-[var(--font-weight-semibold)] text-[var(--color-text-muted)] uppercase tracking-[0.06em]">
              Games
            </h2>
            {games.length > 0 && (
              <p className="text-xs text-[var(--color-text-muted)] flex items-center gap-[var(--spacing-1)] flex-wrap">
                <span>
                  {games.filter((g) => g.sync_enabled).length} of {games.length} syncing · use the dot below each cover to toggle
                  {(() => {
                    const n = games.filter(isPendingDelivery).length
                    return n > 0 ? ` · ${n} Pending` : null
                  })()}
                </span>
                {games.filter((g) => g.sync_state === 'DELIVERY_FAILED').length > 0 && (
                  <>
                    <span aria-hidden>·</span>
                    <span>{games.filter((g) => g.sync_state === 'DELIVERY_FAILED').length} Need Retry</span>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => retryAll.mutate()}
                      disabled={retryAll.isPending}
                      aria-label="Retry all failed deliveries"
                      className="shrink-0 -my-1"
                    >
                      <Upload size={12} />
                    </Button>
                  </>
                )}
              </p>
            )}
          </div>
          {games.length > 0 && (
            <div className="flex gap-[var(--spacing-2)]">
              <Button variant="ghost" size="sm" onClick={() => void enableAll()}>Enable All</Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setDisableAllOpen(true)}
                className="text-[var(--color-error)] hover:bg-[var(--color-error-subtle)] hover:text-[var(--color-error)]"
              >
                Disable All
              </Button>
            </div>
          )}
        </div>

        {games.length > 0 && (
          <div className="flex items-center gap-[var(--spacing-3)] flex-wrap">
            <div className="relative flex-1 min-w-32 max-w-xs">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" aria-hidden="true" />
              <Input
                value={gameSearch}
                onChange={(e) => setGameSearch(e.target.value)}
                placeholder="Search games…"
                aria-label="Search games"
                className="pl-8 text-sm"
              />
            </div>
            <Select value={gameSortKey} onValueChange={(v) => setGameSortKey(v as typeof gameSortKey)}>
              <SelectTrigger className="w-32" aria-label="Sort games by">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="recent">Recent</SelectItem>
                <SelectItem value="name">Name</SelectItem>
                <SelectItem value="status">Status</SelectItem>
              </SelectContent>
            </Select>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => scan.mutate()}
                  disabled={scan.isPending || isRommLoading || !rommEnabled}
                  aria-label="Scan for missing RomM titles"
                  className={cn('shrink-0 text-[var(--color-text-muted)]', (!rommEnabled || isRommLoading) && 'invisible pointer-events-none')}
                >
                  <RefreshCw size={15} className={scan.isPending ? 'animate-spin' : ''} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{scan.isSuccess ? 'Scan queued' : 'Scan for missing titles'}</TooltipContent>
            </Tooltip>
          </div>
        )}

        {(() => {
          const isRommDevice = device.client_type === 'romm'
          const scanRunning = gamesData?.scan_running ?? false
          const scanQueued = gamesData?.scan_queued ?? false
          const scanError = gamesData?.scan_error ?? null

          if (games.length === 0) {
            if (isRommDevice && (scanRunning || scanQueued)) {
              return (
                <EmptyState
                  title="Indexing RomM library…"
                  description={
                    <span className="flex items-center gap-2 justify-center">
                      <Loader2 size={14} className="animate-spin shrink-0" />
                      Scanning your RomM catalog for games. This may take a minute.
                    </span>
                  }
                />
              )
            }
            if (isRommDevice && scanError) {
              return (
                <EmptyState
                  title="RomM scan failed"
                  description={`Could not index RomM library: ${scanError}`}
                />
              )
            }
            if (isRommDevice) {
              return (
                <EmptyState
                  title="No games found"
                  description="No games matched in your RomM library. Check that RomM is reachable and your ROMs have title IDs in their filenames."
                />
              )
            }
            return (
              <EmptyState
                title="No games"
                description="No saves found for this client. Claim a profile in Settings to see your save history."
              />
            )
          }

          if (filteredGames.length === 0) {
            return <EmptyState title="No results" description={`No games match "${gameSearch}"`} />
          }

          return (
            <>
              {isRommDevice && scanError && (
                <div className="flex items-center gap-2 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-400">
                  RomM scan error — showing cached games: {scanError}
                </div>
              )}
              <div className="grid grid-cols-3 md:grid-cols-5 gap-x-[var(--spacing-3)] gap-y-[var(--spacing-5)]">
                {filteredGames.slice(0, visibleGames).map((game) => (
                  <SyncCard
                    key={game.title_id}
                    game={game}
                    deviceId={device_id!}
                    queryKey={gamesKey}
                  />
                ))}
              </div>
              {filteredGames.length > visibleGames && (
                <div className="flex justify-center">
                  <Button variant="ghost" size="sm" onClick={() => setVisibleGames((n) => n + 500)}>
                    Load more games
                  </Button>
                </div>
              )}
            </>
          )
        })()}
      </section>

      <ConfirmDialog
        open={disableAllOpen}
        onOpenChange={setDisableAllOpen}
        title={`Disable sync for ${games.length} game${games.length !== 1 ? 's' : ''}?`}
        description="Sync will be turned off for all games on this device. You can re-enable them individually at any time."
        confirmLabel="Disable All"
        variant="destructive"
        onConfirm={() => void disableAll()}
      />

      {(() => {
        const deviceLabel = device?.display_name ?? device_id ?? 'this device'
        const defaultProfile = profiles.find((p) => p.profile_id === device?.default_profile_uid)
        const profileLabel = defaultProfile?.profile_name || 'Default Profile'
        return (
          <ConfirmDialog
            open={restoreAllOpen}
            onOpenChange={setRestoreAllOpen}
            title={`Restore all available saves to ${deviceLabel}?`}
            description={`Pushes the latest cloud save for every game that has one — ${profileLabel}. Games that have never been synced are not touched.`}
            confirmLabel="Restore All"
            onConfirm={() => void restoreAll()}
          />
        )
      })()}
    </div>
  )
}

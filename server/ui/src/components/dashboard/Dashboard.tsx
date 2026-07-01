import { Gamepad2, Monitor, Upload } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'
import { RelativeTime } from '@/components/ui/relative-time'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api'
import type { AppEvent, DashboardData } from '@/types'
import { Button } from '@/components/ui/button'
import { DeviceStatusIndicator } from '@/components/ui/device-status-indicator'
import { GameCard } from '@/components/ui/game-card'
import { HardwareIcon } from '@/components/ui/hardware-icon'
import { Skeleton } from '@/components/ui/skeleton'
import { ActivityList } from '@/components/events/ActivityList'
import { DayHeatmap } from '@/components/ui/day-heatmap'
import { useAuth } from '@/contexts/AuthContext'
import { useBackground } from '@/components/layout/AppShellV2'

const SECTION_HEADER = 'text-sm font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] uppercase tracking-[var(--tracking-wide)] hover:opacity-80 transition-opacity duration-[var(--motion-duration-fast)]'

function DashboardDeviceCard({
  device,
  infoMap,
}: {
  device: { device_id: string; display_name: string | null; last_seen: string; pending_count: number; delivery_failed_count: number }
  infoMap: Map<string, { hardware_type: string | null; client_type: string | null }>
}) {
  const qc = useQueryClient()
  const retryAll = useMutation({
    mutationFn: () => api.retryAllFailed(device.device_id),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ['dashboard'] })
      const prev = qc.getQueryData<DashboardData>(['dashboard'])
      if (prev) {
        qc.setQueryData<DashboardData>(['dashboard'], {
          ...prev,
          devices: prev.devices.map((d) =>
            d.device_id === device.device_id
              ? { ...d, pending_count: d.pending_count + d.delivery_failed_count, delivery_failed_count: 0 }
              : d
          ),
        })
      }
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(['dashboard'], ctx.prev)
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
      void qc.invalidateQueries({ queryKey: ['devices'] })
      void qc.invalidateQueries({ queryKey: ['deviceGames', device.device_id] })
    },
  })

  const info = infoMap.get(device.device_id)

  return (
    <Link
      to={`/devices/${device.device_id}`}
      className="group rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] p-[var(--spacing-4)] flex flex-col gap-[var(--spacing-1)] h-full hover:bg-[var(--color-bg-hover)] hover:border-[var(--color-border-base)] transition-colors duration-[var(--motion-duration-fast)]"
    >
      <div className="flex items-center gap-[var(--spacing-2)]">
        <HardwareIcon clientType={info?.client_type ?? null} hardwareType={info?.hardware_type ?? null} size={20} className="shrink-0" />
        <p className="flex-1 min-w-0 text-sm font-[var(--font-weight-medium)] text-[var(--color-text-primary)] truncate">
          {device.display_name ?? (
            <span className="font-mono text-[var(--color-text-muted)]">{device.device_id.slice(0, 8)}…</span>
          )}
        </p>
        <DeviceStatusIndicator lastSeen={device.last_seen} />
      </div>
      {device.pending_count > 0 && (
        <p className="text-sm text-[var(--color-text-primary)]">
          {device.pending_count} Pending
        </p>
      )}
      {device.delivery_failed_count > 0 && (
        <div className="flex items-center justify-between gap-[var(--spacing-1)]">
          <p className="text-xs text-[var(--color-text-muted)]">
            {device.delivery_failed_count} Needs Retry
          </p>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); retryAll.mutate() }}
            disabled={retryAll.isPending}
            aria-label={`Retry ${device.delivery_failed_count} failed deliveries`}
            className="shrink-0"
          >
            <Upload size={13} className={retryAll.isPending ? 'animate-pulse' : ''} />
          </Button>
        </div>
      )}
      <div className="flex-1" />
      <p className="text-xs text-[var(--color-text-muted)]">
        <RelativeTime iso={device.last_seen} />
      </p>
    </Link>
  )
}

export default function Dashboard() {
  const { username } = useAuth()
  const { data, isLoading } = useQuery<DashboardData>({
    queryKey: ['dashboard'],
    queryFn: () => api.dashboard(),
    refetchInterval: 5_000,
  })

  const { data: devicesData } = useQuery({
    queryKey: ['devices'],
    queryFn: () => api.devices(),
  })
  const setBg = useBackground()
  const bgPickedRef = React.useRef(false)
  React.useEffect(() => {
    if (bgPickedRef.current) return
    const first = data?.recent_games?.find(g => g.icon_url)
    if (!first?.icon_url) return
    bgPickedRef.current = true
    setBg(first.icon_url)
  }, [data, setBg])

  const deviceInfoMap = React.useMemo(() => {
    const m = new Map<string, { hardware_type: string | null; client_type: string | null }>()
    for (const d of devicesData?.devices ?? []) m.set(d.device_id, { hardware_type: d.hardware_type, client_type: d.client_type })
    return m
  }, [devicesData])

  const { data: playtimeData, isLoading: playtimeLoading } = useQuery({
    queryKey: ['playtime-daily'],
    queryFn: () => api.dailyPlaytime(),
    staleTime: 60_000,
  })

  return (
    <div className="flex flex-col gap-[var(--spacing-8)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">

      {/* Recent Games */}
      <section className="flex flex-col gap-[var(--spacing-2)]">
        <div className="flex min-h-8 items-center">
          <Link to="/library">
            <h2 className={SECTION_HEADER}>{username ? `${username}'s Recent Games` : 'Recent Games'}</h2>
          </Link>
        </div>
        <div className="grid grid-cols-3 md:grid-cols-5 gap-x-[var(--spacing-3)] gap-y-[var(--spacing-5)]">
          {isLoading ? (
            [0,1,2,3,4,5,6,7,8,9].map((i) => (
              <div key={i} className={i >= 6 ? 'hidden md:flex flex-col gap-[var(--spacing-2)]' : 'flex flex-col gap-[var(--spacing-2)]'}>
                <Skeleton className="w-full aspect-[3/4] rounded-[var(--radius-md)]" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            ))
          ) : (data?.recent_games ?? []).length === 0 ? (
            <div className="col-span-full py-[var(--spacing-8)] flex flex-col items-center gap-[var(--spacing-3)] text-center">
              <Gamepad2 size={32} className="text-[var(--color-text-muted)]" aria-hidden="true" />
              <p className="text-sm text-[var(--color-text-muted)]">
                No games yet — add a client to start syncing your saves.
              </p>
              <Link
                to="/settings#pair-device"
                className="text-sm font-[var(--font-weight-medium)] text-[var(--color-text-primary)] underline underline-offset-2 hover:text-[var(--color-text-secondary)]"
              >
                Add a Client →
              </Link>
            </div>
          ) : (
            (data?.recent_games ?? []).slice(0, 10).map((game, index) => (
              <div key={game.title_id} className={index >= 6 ? 'hidden md:block' : undefined}>
                <GameCard
                  titleId={game.title_id}
                  displayName={game.display_name}
                  iconUrl={game.icon_url}
                  lastActivity={game.last_activity}
                />
              </div>
            ))
          )}
        </div>
      </section>

      {/* Clients */}
      <section className="flex flex-col gap-[var(--spacing-2)]">
        <div className="flex min-h-8 items-center">
          <Link to="/devices">
            <h2 className={SECTION_HEADER}>Clients</h2>
          </Link>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-[var(--spacing-3)]">
          {isLoading ? (
            [0, 1, 2].map((i) => (
              <div key={i} className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] p-[var(--spacing-4)] flex flex-col gap-[var(--spacing-2)]">
                <Skeleton className="w-8 h-8 rounded-[var(--radius-md)]" />
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-3 w-16" />
              </div>
            ))
          ) : (data?.devices ?? []).filter((d) => !d.is_deleted).length === 0 ? (
            <div className="col-span-full py-[var(--spacing-8)] flex flex-col items-center gap-[var(--spacing-2)] text-center">
              <Monitor size={32} className="text-[var(--color-text-muted)]" aria-hidden="true" />
              <p className="text-sm text-[var(--color-text-muted)]">No clients registered</p>
            </div>
          ) : (
            (data?.devices ?? []).filter((d) => !d.is_deleted).map((device) => (
              <DashboardDeviceCard key={device.device_id} device={device} infoMap={deviceInfoMap} />
            ))
          )}
        </div>
      </section>

      {/* Recent Activity */}
      <section className="flex flex-col gap-[var(--spacing-2)]">
        <div className="flex min-h-8 items-center">
          <Link to="/activity">
            <h2 className={SECTION_HEADER}>Recent Activity</h2>
          </Link>
        </div>
        <ActivityList
          events={(data?.recent_events ?? []) as AppEvent[]}
          loading={isLoading}
          grouped={false}
        />
      </section>

      {/* Play History */}
      <section className="flex flex-col gap-[var(--spacing-2)]">
        <div className="flex min-h-8 items-center">
          <h2 className="text-sm font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] uppercase tracking-[var(--tracking-wide)]">Play History</h2>
        </div>
        {playtimeLoading ? (
          <Skeleton className="h-24 w-full rounded-[var(--radius-md)]" />
        ) : (
          <DayHeatmap data={playtimeData?.days ?? []} />
        )}
      </section>

    </div>
  )
}

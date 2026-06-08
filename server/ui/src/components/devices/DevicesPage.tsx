import { Upload, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import * as React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api'
import { useLocalStorage } from '@/lib/useLocalStorage'
import type { Device } from '@/types'
import { DeviceStatusIndicator } from '@/components/ui/device-status-indicator'
import { EmptyState } from '@/components/ui/empty-state'
import { HardwareIcon } from '@/components/ui/hardware-icon'
import { Input } from '@/components/ui/input'
import { RelativeTime } from '@/components/ui/relative-time'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

type SortKey = 'recent' | 'name' | 'status'

const ONLINE_MS = 2 * 60_000

function isOnline(lastSeen: string): boolean {
  return Date.now() - new Date(lastSeen).getTime() < ONLINE_MS
}

function sortDevices(devices: Device[], key: SortKey): Device[] {
  return [...devices].sort((a, b) => {
    if (key === 'name') {
      const na = (a.display_name ?? a.device_id).toLowerCase()
      const nb = (b.display_name ?? b.device_id).toLowerCase()
      return na.localeCompare(nb)
    }
    if (key === 'status') {
      const diff = (isOnline(b.last_seen) ? 0 : 1) - (isOnline(a.last_seen) ? 0 : 1)
      if (diff !== 0) return diff
    }
    return new Date(b.last_seen).getTime() - new Date(a.last_seen).getTime()
  })
}

function DeviceCard({ device }: { device: Device }) {
  const deviceLabel = device.display_name ?? device.device_id.slice(0, 8)
  const qc = useQueryClient()
  const retryAll = useMutation({
    mutationFn: () => api.retryAllFailed(device.device_id),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ['devices'] })
      const prev = qc.getQueryData<{ devices: Device[] }>(['devices'])
      if (prev) {
        qc.setQueryData(['devices'], {
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
      if (ctx?.prev) qc.setQueryData(['devices'], ctx.prev)
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['devices'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
      void qc.invalidateQueries({ queryKey: ['deviceGames', device.device_id] })
    },
  })

  return (
    <Link
      to={`/devices/${device.device_id}`}
      className="group rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] p-[var(--spacing-4)] flex flex-col gap-[var(--spacing-1)] h-full hover:bg-[var(--color-bg-hover)] hover:border-[var(--color-border-base)] transition-colors duration-[var(--motion-duration-fast)]"
    >
      <div className="flex items-center gap-[var(--spacing-2)]">
        <HardwareIcon clientType={device.client_type} hardwareType={device.hardware_type} size={20} className="shrink-0" />
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
            aria-label={`Retry ${device.delivery_failed_count} failed deliveries for ${deviceLabel}`}
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

function DeviceCardSkeleton() {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)] p-[var(--spacing-4)] flex flex-col gap-[var(--spacing-2)]">
      <Skeleton className="w-8 h-8 rounded-[var(--radius-md)]" />
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-3 w-16" />
    </div>
  )
}

export default function DevicesPage() {
  const [search, setSearch] = React.useState('')
  const [sortKey, setSortKey] = useLocalStorage<SortKey>('pref:clients:sort', 'recent')

  const { data, isLoading } = useQuery({
    queryKey: ['devices'],
    queryFn: () => api.devices(),
    refetchInterval: 5_000,
  })

  const devices: Device[] = (data?.devices ?? []).filter((d) => !d.is_deleted)

  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return devices
    return devices.filter((d) =>
      (d.display_name ?? '').toLowerCase().includes(q) ||
      d.device_id.toLowerCase().includes(q),
    )
  }, [devices, search])

  const sorted = React.useMemo(() => sortDevices(filtered, sortKey), [filtered, sortKey])

  return (
    <div className="flex flex-col gap-[var(--spacing-6)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">

      {/* Controls row */}
      <div className="flex items-center gap-[var(--spacing-3)]">
        <div className="relative flex-1 md:max-w-xs">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]"
            aria-hidden="true"
          />
          <Input
            placeholder="Search clients…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8"
            aria-label="Search clients"
          />
        </div>

        <Select value={sortKey} onValueChange={(v) => setSortKey(v as SortKey)}>
          <SelectTrigger className="w-28 md:w-36" aria-label="Sort clients by">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="recent">Recent</SelectItem>
            <SelectItem value="name">Name</SelectItem>
            <SelectItem value="status">Status</SelectItem>
          </SelectContent>
        </Select>

        <span className={cn('hidden md:block text-sm text-[var(--color-text-muted)] shrink-0 w-24 text-right tabular-nums', isLoading && 'invisible')}>
          {filtered.length} {filtered.length === 1 ? 'client' : 'clients'}
        </span>
      </div>

      {/* Grid */}
      {isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-[var(--spacing-3)]">
          {[0, 1, 2, 3].map((i) => <DeviceCardSkeleton key={i} />)}
        </div>
      ) : sorted.length === 0 ? (
        search ? (
          <EmptyState title="No results" description={`No clients match "${search}"`} />
        ) : (
          <EmptyState
            title="No clients registered"
            description="Clients appear here when your Switch connects for the first time."
          />
        )
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-[var(--spacing-3)]">
          {sorted.map((device) => (
            <div key={device.device_id}>
              <DeviceCard device={device} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

import { Search } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api'
import { useLocalStorage } from '@/lib/useLocalStorage'
import type { AppEvent, Device, Game } from '@/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { ActivityList, ActivitySkeleton, eventLabel } from './ActivityList'

const INITIAL_LIMIT = 500

type TypeFilter = 'all' | 'uploads' | 'downloads' | 'errors' | 'system'

function matchesTypeFilter(type: string, f: TypeFilter): boolean {
  if (f === 'all') return true
  const t = type.toLowerCase()
  if (f === 'uploads') return t.includes('upload') || t.includes('snapshot') || t.includes('outbound')
  if (f === 'downloads') return t.includes('download') || t.includes('restore') || t.includes('deliver')
  if (f === 'errors') return t.includes('fail') || t.includes('error')
  if (f === 'system') return !t.includes('upload') && !t.includes('download') && !t.includes('snapshot') && !t.includes('restore') && !t.includes('deliver') && !t.includes('fail') && !t.includes('error')
  return true
}

export default function EventsPage() {
  const [limit, setLimit] = React.useState(INITIAL_LIMIT)
  const [typeFilter, setTypeFilter] = useLocalStorage<TypeFilter>('pref:activity:typeFilter', 'all')
  const [deviceFilter, setDeviceFilter] = useLocalStorage<string>('pref:activity:deviceFilter', 'all')
  const [gameSearch, setGameSearch] = React.useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['events', limit],
    queryFn: () => api.events(limit),
    refetchInterval: 20_000,
  })

  const { data: devicesData } = useQuery({
    queryKey: ['devices'],
    queryFn: () => api.devices(),
    staleTime: 60_000,
  })

  const { data: gamesData } = useQuery({
    queryKey: ['games'],
    queryFn: () => api.games(),
    staleTime: 30_000,
  })

  const allEvents: AppEvent[] = data?.events ?? []
  const devices: Device[] = devicesData?.devices ?? []

  const gameMap = React.useMemo(() => {
    const m = new Map<string, Game>()
    for (const g of gamesData?.games ?? []) m.set(g.title_id, g)
    return m
  }, [gamesData])

  const deviceMap = React.useMemo(() => {
    const m = new Map<string, Device>()
    for (const d of devices) m.set(d.device_id, d)
    return m
  }, [devices])

  const filtered = React.useMemo(() => {
    let ev = allEvents
    if (typeFilter !== 'all') ev = ev.filter((e) => matchesTypeFilter(e.event_type, typeFilter))
    if (deviceFilter !== 'all') ev = ev.filter((e) => e.device_id === deviceFilter)
    if (gameSearch.trim()) {
      const q = gameSearch.trim().toLowerCase()
      ev = ev.filter((e) => {
        const gameName = gameMap.get(e.title_id)?.display_name ?? ''
        const deviceName = deviceMap.get(e.device_id)?.display_name ?? ''
        const label = eventLabel(e.event_type)
        return (
          (e.title_id ?? '').toLowerCase().includes(q) ||
          (e.device_id ?? '').toLowerCase().includes(q) ||
          gameName.toLowerCase().includes(q) ||
          deviceName.toLowerCase().includes(q) ||
          label.toLowerCase().includes(q)
        )
      })
    }
    return ev
  }, [allEvents, typeFilter, deviceFilter, gameSearch, gameMap, deviceMap])

  const hasMore = allEvents.length >= limit
  const activeFilters = typeFilter !== 'all' || deviceFilter !== 'all' || gameSearch.trim()

  return (
    <div className="flex flex-col gap-[var(--spacing-6)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">
      <section className="flex flex-col gap-[var(--spacing-6)]">

        {/* Filters */}
        <div className="flex min-h-8 items-center gap-[var(--spacing-3)] flex-wrap">
          <Select value={typeFilter} onValueChange={(v) => setTypeFilter(v as TypeFilter)}>
            <SelectTrigger className="w-36" aria-label="Filter by type">
              <SelectValue placeholder="Type: All" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              <SelectItem value="uploads">Uploads</SelectItem>
              <SelectItem value="downloads">Downloads</SelectItem>
              <SelectItem value="errors">Errors</SelectItem>
              <SelectItem value="system">System</SelectItem>
            </SelectContent>
          </Select>

          <Select value={deviceFilter} onValueChange={setDeviceFilter}>
            <SelectTrigger className="w-40" aria-label="Filter by device">
              <SelectValue placeholder="Device: All" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All devices</SelectItem>
              {devices.map((d) => (
                <SelectItem key={d.device_id} value={d.device_id}>
                  {d.display_name ?? d.device_id.slice(0, 8)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="relative flex-1 min-w-32 max-w-xs">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" aria-hidden="true" />
            <Input
              value={gameSearch}
              onChange={(e) => setGameSearch(e.target.value)}
              placeholder="Search games…"
              aria-label="Search by game"
              className="pl-8 text-sm"
            />
          </div>
        </div>

        {/* Event list */}
        {isLoading ? (
          <ActivitySkeleton count={5} />
        ) : (
          <ActivityList
            events={filtered}
            grouped={true}
            emptyMessage={
              activeFilters
                ? 'No matching events — try adjusting your filters.'
                : 'No activity yet. Claim a profile on a device to see your sync history.'
            }
            emptyAction={
              !activeFilters ? (
                <Link
                  to="/devices"
                  className="text-sm font-[var(--font-weight-medium)] text-[var(--color-text-primary)] underline underline-offset-2 hover:text-[var(--color-text-secondary)]"
                >
                  Go to Devices →
                </Link>
              ) : undefined
            }
          />
        )}

        {!isLoading && hasMore && !activeFilters && (
          <div className="flex justify-center">
            <Button variant="ghost" size="sm" onClick={() => setLimit((l) => l + 500)}>
              Load earlier events
            </Button>
          </div>
        )}
      </section>
    </div>
  )
}

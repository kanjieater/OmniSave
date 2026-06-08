import * as React from 'react'
import { Activity } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api'
import type { AppEvent, Device, Game } from '@/types'
import { EmptyState } from '@/components/ui/empty-state'
import { GameIcon } from '@/components/ui/game-icon'
import { HardwareIcon } from '@/components/ui/hardware-icon'
import { RelativeTime } from '@/components/ui/relative-time'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { ICON_LG } from '@/lib/ui-scale'

export function eventLabel(type: string): string {
  const t = type.toLowerCase()
  if (t.includes('upload') && t.includes('complete')) return 'Upload Completed'
  if (t.includes('upload') && t.includes('fail')) return 'Upload Failed'
  if (t.includes('upload') && t.includes('start')) return 'Upload Started'
  if (t.includes('download') && t.includes('complete')) return 'Download Completed'
  if (t.includes('download') && t.includes('fail')) return 'Download Failed'
  if (t.includes('conflict')) return 'Conflict Detected'
  if (t.includes('snapshot') && t.includes('ready')) return 'Snapshot Ready'
  if (t.includes('snapshot') && t.includes('dedup')) return 'Duplicate Snapshot'
  if (t.includes('snapshot') && t.includes('store')) return 'Save Stored'
  if (t.includes('restore') && t.includes('ack')) return 'Save Restored'
  if (t.includes('inject') && t.includes('fail')) return 'Restore Failed'
  if (t.includes('inject')) return 'Restore Applied'
  if (t.includes('romm') && t.includes('push') && t.includes('fail')) return 'Upload Failed'
  if (t.includes('romm') && t.includes('push')) return 'Upload Completed'
  if (t.includes('romm') && t.includes('pull')) return 'Save Stored'
  if (t.includes('romm') && t.includes('ingest')) return 'Upload Started'
  if (t.includes('side_effect')) return 'Sync Error'
  if (t.includes('processing') && t.includes('fail')) return 'Upload Failed'
  if (t.includes('outbound') && t.includes('cancel')) return 'Delivery Cancelled'
  if (t.includes('outbound') && t.includes('retry')) return 'Delivery Retry'
  if (t.includes('outbound')) return 'Delivery Queued'
  return type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function eventDotClass(type: string): string {
  const t = type.toLowerCase()
  if (t.includes('fail') || t.includes('error')) return 'bg-[var(--color-error)]'
  if (t.includes('conflict')) return 'bg-[var(--color-warning)]'
  if (t.includes('dedup')) return 'bg-[var(--color-text-muted)]'
  if (t.includes('upload') || t.includes('outbound')) return 'bg-[var(--color-info)]'
  return 'bg-[var(--color-success)]'
}

export function eventDotTitle(type: string): string {
  const t = type.toLowerCase()
  if (t.includes('fail') || t.includes('error')) return 'Error'
  if (t.includes('conflict')) return 'Conflict'
  if (t.includes('dedup')) return 'Duplicate'
  if (t.includes('upload') || t.includes('outbound')) return 'Upload'
  return 'Success'
}

// FOLLOW-UP (required before v1.0): Add snapshot_sequence as a first-class field on AppEvent
// (server: LEFT JOIN sync_transactions on transaction_id, return sequence_num as snapshot_sequence).
// Remove parseSeqNum once available — current parsing breaks silently if event message wording changes.
function parseSeqNum(summary: string): number | null {
  const m = summary.match(/\bseq=(\d+)\b/)
  return m ? parseInt(m[1], 10) : null
}

export function groupByDay(events: AppEvent[]): Array<{ label: string; events: AppEvent[] }> {
  const now = new Date()
  const groups: Map<string, AppEvent[]> = new Map()
  for (const event of events) {
    const d = new Date(event.created_at)
    const diffDays = Math.floor((now.getTime() - d.getTime()) / 86_400_000)
    let label: string
    if (diffDays === 0) label = 'Today'
    else if (diffDays === 1) label = 'Yesterday'
    else if (diffDays < 7) label = `${diffDays} days ago`
    else label = d.toLocaleDateString(undefined, { month: 'long', day: 'numeric' })
    if (!groups.has(label)) groups.set(label, [])
    groups.get(label)!.push(event)
  }
  return Array.from(groups.entries()).map(([label, evs]) => ({ label, events: evs }))
}

interface EventRowProps {
  event: AppEvent
  gameMap: Map<string, Game>
  deviceMap: Map<string, Device>
}

function EventRow({ event, gameMap, deviceMap }: EventRowProps) {
  const game = event.title_id ? gameMap.get(event.title_id) : undefined
  const device = event.device_id ? deviceMap.get(event.device_id) : undefined
  const isDedup = event.event_type.toLowerCase().includes('dedup')
  const seqNum = !isDedup && event.summary ? parseSeqNum(event.summary) : null

  return (
    <div
      role="article"
      className="flex items-center gap-[var(--spacing-3)] py-[var(--spacing-3)] px-[var(--spacing-4)] border-b border-[var(--color-border-subtle)] last:border-b-0 min-w-[520px]"
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn('w-2 h-2 rounded-full shrink-0 cursor-default', eventDotClass(event.event_type))}
            aria-label={eventLabel(event.event_type)}
          />
        </TooltipTrigger>
        <TooltipContent>{eventLabel(event.event_type)}</TooltipContent>
      </Tooltip>

      {event.title_id ? (
        <Link to={`/game/${event.title_id}`} className="shrink-0 w-[40px] h-[40px] md:w-[52px] md:h-[52px] rounded-[var(--radius-sm)] overflow-hidden" tabIndex={-1} aria-hidden="true">
          <GameIcon iconUrl={event.icon_url} name={game?.display_name ?? ''} size="full" className="w-full h-full object-cover" />
        </Link>
      ) : (
        <div className="shrink-0 w-[40px] h-[40px] md:w-[52px] md:h-[52px]">
          <GameIcon iconUrl={event.icon_url} name="" size="full" className="w-full h-full" />
        </div>
      )}

      {/* Two-line content block */}
      <div className="flex-1 min-w-0">
        <p className="text-base font-[var(--font-weight-medium)] text-[var(--color-text-primary)] truncate">
          {eventLabel(event.event_type)}
        </p>
        {game?.display_name && (
          <Link
            to={`/game/${event.title_id}`}
            className="text-sm text-[var(--color-text-muted)] truncate hover:underline block"
          >
            {game.display_name}
          </Link>
        )}
      </div>

      {/* Save # — fixed-width slot so column aligns across all rows */}
      <div className="w-14 shrink-0 flex justify-end">
        {seqNum != null && event.title_id ? (
          <Link
            to={`/game/${event.title_id}`}
            onClick={() => window.scrollTo({ top: 0, behavior: 'instant' })}
            className="font-mono font-[var(--font-weight-bold)] text-[var(--color-text-primary)] tabular-nums leading-none text-sm md:text-lg"
            aria-label={`Save #${seqNum} — view in game history`}
          >
            #{seqNum}
          </Link>
        ) : null}
      </div>

      {/* Device — compact on mobile, wider on desktop */}
      <div className="w-[56px] md:w-24 shrink-0 flex items-center gap-[var(--spacing-1)] overflow-hidden">
        {device ? (
          <Link
            to={`/devices/${event.device_id}`}
            className="flex items-center gap-[var(--spacing-1)] min-w-0 text-xs md:text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
          >
            <HardwareIcon clientType={device.client_type} hardwareType={device.hardware_type} size={11} className="shrink-0" />
            <span className="truncate">{device.display_name ?? device.device_id.slice(0, 8)}</span>
          </Link>
        ) : null}
      </div>

      {/* Time */}
      <div className="w-[64px] md:w-[72px] shrink-0 overflow-hidden text-right">
        <RelativeTime
          iso={event.created_at}
          className="text-xs text-[var(--color-text-muted)] whitespace-nowrap"
        />
      </div>
    </div>
  )
}

export function ActivitySkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] overflow-x-auto bg-[var(--color-bg-subtle)]">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-[var(--spacing-3)] px-[var(--spacing-4)] py-[var(--spacing-3)] border-b border-[var(--color-border-subtle)] last:border-b-0"
        >
          <Skeleton className="w-2 h-2 rounded-full shrink-0" />
          <Skeleton className="w-7 h-7 rounded-[var(--radius-sm)] shrink-0" />
          <div className="flex-1 flex flex-col gap-[var(--spacing-1)]">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-56" />
          </div>
          <div className="w-10 shrink-0 flex justify-end">
            <Skeleton className="h-5 w-8" />
          </div>
          <div className="w-[56px] md:w-24 shrink-0 flex">
            <Skeleton className="h-3 w-12 md:w-20" />
          </div>
          <div className="flex w-[52px] sm:w-[68px] md:w-[72px] shrink-0 justify-end">
            <Skeleton className="h-3 w-12" />
          </div>
        </div>
      ))}
    </div>
  )
}

export interface ActivityListProps {
  events: AppEvent[]
  loading?: boolean
  grouped?: boolean
  emptyMessage?: string
  emptyAction?: React.ReactNode
}

export function ActivityList({ events, loading = false, grouped = true, emptyMessage, emptyAction }: ActivityListProps) {
  const { data: gamesData } = useQuery({
    queryKey: ['games'],
    queryFn: () => api.games(),
    staleTime: 30_000,
  })

  const { data: devicesData } = useQuery({
    queryKey: ['devices'],
    queryFn: () => api.devices(),
    staleTime: 60_000,
  })

  const gameMap = React.useMemo(() => {
    const m = new Map<string, Game>()
    for (const g of gamesData?.games ?? []) m.set(g.title_id, g)
    return m
  }, [gamesData])

  const deviceMap = React.useMemo(() => {
    const m = new Map<string, Device>()
    for (const d of devicesData?.devices ?? []) m.set(d.device_id, d)
    return m
  }, [devicesData])

  if (loading) return <ActivitySkeleton />

  if (events.length === 0) {
    return (
      <EmptyState
        icon={<Activity size={ICON_LG} />}
        title="No activity yet"
        description={emptyMessage ?? 'Events appear here as your devices sync.'}
        action={emptyAction}
      />
    )
  }

  if (!grouped) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] overflow-x-auto bg-[var(--color-bg-subtle)]">
        {events.map((event) => (
          <EventRow key={event.id} event={event} gameMap={gameMap} deviceMap={deviceMap} />
        ))}
      </div>
    )
  }

  const groups = groupByDay(events)

  return (
    <div role="feed" className="flex flex-col gap-[var(--spacing-4)]">
      {groups.map(({ label, events: groupEvents }) => (
        <section key={label} aria-label={label}>
          <h2 className="text-xs font-[var(--font-weight-medium)] text-[var(--color-text-secondary)] uppercase tracking-[0.06em] mb-[var(--spacing-2)] px-[var(--spacing-1)]">
            {label}
          </h2>
          <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] overflow-x-auto bg-[var(--color-bg-subtle)]">
            {groupEvents.map((event) => (
              <EventRow key={event.id} event={event} gameMap={gameMap} deviceMap={deviceMap} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

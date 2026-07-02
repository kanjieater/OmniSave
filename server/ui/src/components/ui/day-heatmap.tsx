import * as React from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { ActivityCalendar } from 'react-activity-calendar'
import type { PlaytimeDay, PlaytimeGame } from '@/types'
import { GameIcon } from '@/components/ui/game-icon'

type Activity = { date: string; count: number; level: number }

const THEME = {
  dark: [
    '#111318', // L0 — bg-subtle        (no play)
    '#0F2A1A', // L1 — success-subtle   (1–30 min)
    '#166534', // L2 — success-border   (31–90 min)
    '#22C55E', // L3 — success          (91–180 min)
    '#4ADE80', // L4 — success-text     (180+ min)
  ],
}

function minutesToLevel(m: number): number {
  if (m === 0) return 0
  if (m <= 30) return 1
  if (m <= 90) return 2
  if (m <= 180) return 3
  return 4
}

function fmt(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h > 0 && m > 0) return `${h}h ${m}m`
  if (h > 0) return `${h}h`
  return `${m}m`
}

function toISO(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function toCalendarData(days: PlaytimeDay[], year: number): Activity[] {
  const startStr = `${year}-01-01`
  const endStr = `${year}-12-31`
  const map = new Map(
    days.filter(d => d.date >= startStr && d.date <= endStr).map(d => [d.date, d.minutes])
  )
  const dates = new Set([startStr, ...map.keys(), endStr])
  return [...dates].sort().map(date => {
    const minutes = map.get(date) ?? 0
    return { date, count: minutes, level: minutesToLevel(minutes) }
  })
}

interface Stats {
  allTimeMinutes: number
  last7Avg: number
  longestStreak: number
  currentStreak: number
}

function computeStats(data: PlaytimeDay[]): Stats {
  const today = toISO(new Date())
  const sevenDaysAgo = toISO(new Date(Date.now() - 6 * 86400_000))

  const allTimeMinutes = Math.floor(data.flatMap(d => d.games).reduce((s, g) => s + g.total_sec, 0) / 60)
  const last7Total = data
    .filter(d => d.date >= sevenDaysAgo && d.date <= today)
    .reduce((s, d) => s + d.minutes, 0)
  const last7Avg = Math.round(last7Total / 7)

  const playDates = new Set(data.filter(d => d.minutes > 0).map(d => d.date))
  const sorted = [...playDates].sort()

  let longestStreak = 0
  let run = 0
  let prev: string | null = null
  for (const date of sorted) {
    if (prev) {
      const gap = (new Date(date + 'T00:00:00Z').getTime() - new Date(prev + 'T00:00:00Z').getTime()) / 86400_000
      run = gap === 1 ? run + 1 : 1
    } else {
      run = 1
    }
    if (run > longestStreak) longestStreak = run
    prev = date
  }

  function countBack(from: string): number {
    let count = 0
    let d = new Date(from + 'T12:00:00Z')
    while (playDates.has(toISO(d))) {
      count++
      d = new Date(d.getTime() - 86400_000)
    }
    return count
  }
  const yesterday = toISO(new Date(Date.now() - 86400_000))
  const currentStreak = playDates.has(today)
    ? countBack(today)
    : playDates.has(yesterday)
      ? countBack(yesterday)
      : 0

  return { allTimeMinutes, last7Avg, longestStreak, currentStreak }
}

interface TooltipState {
  date: string
  rect: DOMRect
}

interface Props {
  data: PlaytimeDay[]
  iconUrls?: Record<string, string | null>
}

export function DayHeatmap({ data, iconUrls }: Props) {
  const currentYear = new Date().getFullYear()
  const [year, setYear] = React.useState(currentYear)
  const [tooltip, setTooltip] = React.useState<TooltipState | null>(null)
  const calendarWrapperRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    if (!tooltip) return
    const onDown = (e: PointerEvent) => {
      if (!calendarWrapperRef.current?.contains(e.target as Node)) setTooltip(null)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [tooltip])

  const earliestYear = React.useMemo(() => {
    if (data.length === 0) return currentYear
    return Math.min(...data.map(d => parseInt(d.date.slice(0, 4), 10)))
  }, [data, currentYear])

  const calData = React.useMemo(() => toCalendarData(data, year), [data, year])

  const gameMap = React.useMemo(() => {
    const m = new Map<string, PlaytimeGame[]>()
    for (const d of data) m.set(d.date, d.games ?? [])
    return m
  }, [data])

  const yearMinutes = React.useMemo(
    () => Math.floor(
      data
        .filter(d => d.date.startsWith(`${year}-`))
        .flatMap(d => d.games)
        .reduce((s, g) => s + g.total_sec, 0) / 60
    ),
    [data, year]
  )

  const stats = React.useMemo(() => computeStats(data), [data])

  const tooltipGames = tooltip ? (gameMap.get(tooltip.date) ?? []) : []
  const tooltipMinutes = tooltipGames.reduce((s, g) => s + g.minutes, 0)
  const tooltipDateLabel = tooltip
    ? new Date(tooltip.date + 'T12:00:00').toLocaleDateString('en-US', {
        weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
      })
    : ''

  return (
    <div className="flex flex-col items-center gap-[var(--spacing-3)]">
      {/* Year navigation */}
      <div className="flex items-center gap-[var(--spacing-4)]">
        <button
          onClick={() => setYear(y => y - 1)}
          disabled={year <= earliestYear}
          className="cursor-pointer text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] disabled:opacity-25 disabled:cursor-not-allowed transition-colors duration-[var(--motion-duration-fast)]"
          aria-label="Previous year"
        >
          <ChevronLeft size={16} />
        </button>
        <span className="text-sm font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] tabular-nums w-10 text-center select-none">
          {year}
        </span>
        <button
          onClick={() => setYear(y => y + 1)}
          disabled={year >= currentYear}
          className="cursor-pointer text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] disabled:opacity-25 disabled:cursor-not-allowed transition-colors duration-[var(--motion-duration-fast)]"
          aria-label="Next year"
        >
          <ChevronRight size={16} />
        </button>
      </div>

      {/* Heatmap */}
      <div className="w-full overflow-x-auto">
        <div ref={calendarWrapperRef} className="flex justify-center min-w-fit">
          <ActivityCalendar
            data={calData}
            colorScheme="dark"
            theme={THEME}
            blockSize={14}
            blockMargin={3}
            blockRadius={3}
            fontSize={13}
            weekStart={1}
            showWeekdayLabels={false}
            showMonthLabels={false}
            showColorLegend={false}
            showTotalCount={false}
            renderBlock={(block, activity) => {
              const enriched = React.cloneElement(
                block as React.ReactElement<React.SVGProps<SVGRectElement>>,
                {
                  style: { cursor: 'pointer' },
                  onPointerEnter: (e: React.PointerEvent<SVGRectElement>) => {
                    if (e.pointerType === 'mouse') {
                      setTooltip({ date: activity.date, rect: e.currentTarget.getBoundingClientRect() })
                    }
                  },
                  onPointerLeave: (e: React.PointerEvent) => {
                    if (e.pointerType === 'mouse') setTooltip(null)
                  },
                  onPointerDown: (e: React.PointerEvent<SVGRectElement>) => {
                    if (e.pointerType !== 'mouse') {
                      e.preventDefault()
                      const rect = e.currentTarget.getBoundingClientRect()
                      setTooltip(prev => prev?.date === activity.date ? null : { date: activity.date, rect })
                    }
                  },
                }
              )
              return <React.Fragment key={activity.date}>{enriched}</React.Fragment>
            }}
            style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)' }}
          />
        </div>
      </div>

      {/* Tooltip portal — custom, no Radix, works on both mouse and touch */}
      {tooltip && createPortal(
        <div
          style={(() => {
            const maxW = Math.min(340, window.innerWidth - 32)
            const halfW = maxW / 2
            return {
              position: 'fixed' as const,
              top: tooltip.rect.top - 8,
              left: Math.max(halfW + 4, Math.min(
                tooltip.rect.left + tooltip.rect.width / 2,
                window.innerWidth - halfW - 4
              )),
              transform: 'translate(-50%, -100%)',
              zIndex: 9999,
              minWidth: '13rem',
              maxWidth: `min(340px, calc(100vw - 2rem))`,
              pointerEvents: 'none' as const,
            }
          })()}
          className="rounded-[var(--radius-md)] border border-[var(--color-border-base)] bg-[var(--color-bg-elevated)] shadow-[var(--shadow-lg)]"
        >
          <div className="flex items-center justify-between px-[var(--spacing-3)] pt-[var(--spacing-2)] pb-[var(--spacing-1)]">
            <p className="text-[var(--color-text-muted)] text-xs">{tooltipDateLabel}</p>
            {tooltipMinutes > 0 && (
              <p className="text-xs font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] pl-[var(--spacing-4)]">
                {fmt(tooltipMinutes)}
              </p>
            )}
          </div>
          {tooltipMinutes === 0 ? (
            <p className="text-sm text-[var(--color-text-muted)] px-[var(--spacing-3)] pb-[var(--spacing-2)]">No playtime</p>
          ) : (
            <div>
              {tooltipGames.map(g => (
                <div
                  key={g.title_id}
                  className="flex items-center gap-[var(--spacing-3)] py-[var(--spacing-2)] px-[var(--spacing-3)] border-t border-[var(--color-border-subtle)]"
                >
                  <GameIcon iconUrl={iconUrls?.[g.title_id] ?? null} name={g.display_name} size={40} />
                  <span className="flex-1 min-w-0 truncate text-sm text-[var(--color-text-primary)]">
                    {g.display_name}
                  </span>
                  <span className="text-sm text-[var(--color-text-muted)] tabular-nums shrink-0 pl-[var(--spacing-3)]">
                    {g.minutes > 0 ? fmt(g.minutes) : '< 1m'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>,
        document.body
      )}

      {/* Year total — always visible so height stays stable across year changes */}
      <p className="text-xs text-[var(--color-text-muted)] tabular-nums">
        {yearMinutes > 0 ? `${fmt(yearMinutes)} in ${year}` : `No playtime in ${year}`}
      </p>

      {/* Static stats bar — computed from all data, not filtered by year */}
      <div className="flex flex-wrap justify-center gap-x-[var(--spacing-6)] gap-y-[var(--spacing-1)] text-xs text-[var(--color-text-muted)]">
        <span>
          Last 7d avg:{' '}
          <span className="font-[var(--font-weight-semibold)] text-[var(--color-success-text)]">
            {fmt(stats.last7Avg)}
          </span>
        </span>
        <span>
          All time:{' '}
          <span className="font-[var(--font-weight-semibold)] text-[var(--color-success-text)]">
            {stats.allTimeMinutes > 0 ? fmt(stats.allTimeMinutes) : '—'}
          </span>
        </span>
        <span>
          Longest streak:{' '}
          <span className="font-[var(--font-weight-semibold)] text-[var(--color-info-text)]">
            {stats.longestStreak} {stats.longestStreak === 1 ? 'day' : 'days'}
          </span>
        </span>
        <span>
          Current streak:{' '}
          <span className="font-[var(--font-weight-semibold)] text-[var(--color-info-text)]">
            {stats.currentStreak} {stats.currentStreak === 1 ? 'day' : 'days'}
          </span>
        </span>
      </div>
    </div>
  )
}

import * as React from 'react'
import { ActivityCalendar } from 'react-activity-calendar'
import 'react-activity-calendar/tooltips.css'
import type { PlaytimeDay } from '@/types'

type Activity = { date: string; count: number; level: number }

const THEME = {
  dark: [
    '#191C23', // level 0 — bg-elevated (no play)
    '#1E3A5F', // level 1 — accent-subtle  (1–30 min)
    '#1D4ED8', // level 2 — blue-700       (31–90 min)
    '#2563EB', // level 3 — blue-600       (91–180 min)
    '#3B82F6', // level 4 — accent         (180+ min)
  ],
}

function minutesToLevel(m: number): number {
  if (m === 0) return 0
  if (m <= 30) return 1
  if (m <= 90) return 2
  if (m <= 180) return 3
  return 4
}

function toISO(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h > 0 && m > 0) return `${h}h ${m}m`
  if (h > 0) return `${h}h`
  return `${m}m`
}

function toCalendarData(days: PlaytimeDay[]): Activity[] {
  const map = new Map(days.map(d => [d.date, d.minutes]))

  const today = new Date()
  const start = new Date(today)
  start.setFullYear(start.getFullYear() - 1)
  start.setDate(start.getDate() + 1) // exactly 365 days ago

  const startStr = toISO(start)
  const endStr = toISO(today)

  // Anchors define the visible range; activity days fill in between
  const dates = new Set([startStr, ...days.map(d => d.date).filter(d => d >= startStr && d <= endStr), endStr])

  return [...dates].sort().map(date => {
    const minutes = map.get(date) ?? 0
    return { date, count: minutes, level: minutesToLevel(minutes) }
  })
}

interface Props {
  data: PlaytimeDay[]
}

export function DayHeatmap({ data }: Props) {
  const calData = React.useMemo(() => toCalendarData(data), [data])
  const totalMinutes = React.useMemo(() => data.reduce((s, d) => s + d.minutes, 0), [data])

  return (
    <div className="flex flex-col gap-[var(--spacing-2)]">
      <div className="overflow-x-auto">
        <ActivityCalendar
          data={calData}
          colorScheme="dark"
          theme={THEME}
          blockSize={10}
          blockMargin={2}
          blockRadius={2}
          fontSize={11}
          weekStart={1}
          showWeekdayLabels={['mon', 'wed', 'fri']}
          showMonthLabels
          showColorLegend={false}
          showTotalCount={false}
          tooltips={{
            activity: {
              text: (a: Activity) => {
                if (a.count === 0) return 'No playtime'
                const d = new Date(a.date + 'T12:00:00')
                const label = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                return `${formatDuration(a.count)} — ${label}`
              },
            },
          }}
          style={{ color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)' }}
        />
      </div>
      {totalMinutes > 0 && (
        <p className="text-xs text-[var(--color-text-muted)] tabular-nums">
          {formatDuration(totalMinutes)} total this year
        </p>
      )}
    </div>
  )
}

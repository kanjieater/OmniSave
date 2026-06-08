import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { serverNow } from './serverTime'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Truncate a hex ID to first N chars + ellipsis */
export function truncateId(id: string, chars = 8): string {
  if (id.length <= chars) return id
  return `${id.slice(0, chars)}…`
}

/** Format bytes to human-readable string */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

/** Format ISO timestamp to relative string */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return 'Never synced'
  const then = new Date(iso).getTime()
  if (isNaN(then)) return 'Never synced'
  const diffSec = Math.floor((serverNow() - then) / 1000)
  if (diffSec < 60) return 'just now'
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHour < 24) return `${diffHour}h ago`
  if (diffDay < 7) return `${diffDay}d ago`
  return new Date(iso).toLocaleDateString()
}

/**
 * How often (ms) to tick — drives the RelativeTime refresh interval.
 * Returns null when old enough that updates aren't useful.
 */
export function relativeTimeInterval(iso: string | null | undefined): number | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (isNaN(then)) return null
  const diffSec = (serverNow() - then) / 1000
  if (diffSec < 60) return 15_000
  if (diffSec < 3600) return 60_000
  if (diffSec < 86400) return 300_000
  return null
}

/** Format ISO timestamp to absolute locale string */
export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return 'Never synced'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return 'Never synced'
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

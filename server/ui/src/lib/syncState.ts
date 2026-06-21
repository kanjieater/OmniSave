import type { SyncState } from '@/types'

export type DisplayState =
  | SyncState
  | 'PENDING_DELIVERY'
  | 'SYNC_DISABLED'

export const SYNC_STYLE: Record<DisplayState, { dot: string; tip: string; label?: string }> = {
  SYNCED:           { dot: 'bg-[var(--color-success)]',            tip: 'In Sync' },
  OUT_OF_SYNC:      { dot: 'bg-[var(--color-warning)]',            tip: 'Needs to Sync' },
  UPLOADING:        { dot: 'bg-[var(--color-info)] animate-pulse', tip: 'Uploading',       label: 'Uploading' },
  PENDING_DELIVERY: { dot: 'bg-[var(--color-warning)]',            tip: 'Delivery Queued', label: 'Pending' },
  DOWNLOADING:      { dot: 'bg-[var(--color-info)] animate-pulse', tip: 'Downloading',     label: 'Downloading' },
  NO_DELIVERY:      { dot: 'bg-[var(--color-text-muted)]',         tip: 'Not yet synced' },
  SYNC_DISABLED:    { dot: 'bg-[var(--color-text-muted)]',         tip: 'Sync Disabled' },
  DELIVERY_FAILED:  { dot: 'bg-[var(--color-error)]',              tip: 'Delivery Failed', label: 'Failed' },
}

export function getDisplayState(
  sync_state: SyncState,
  pending_delivery: boolean,
  sync_enabled: boolean,
): DisplayState | null {
  if (!sync_enabled) return 'SYNC_DISABLED'
  if (sync_state === 'NO_DELIVERY') return null
  if (pending_delivery && sync_state !== 'UPLOADING' && sync_state !== 'DELIVERY_FAILED') return 'PENDING_DELIVERY'
  return sync_state
}

// Lower number = worse = sorts to top. Use with getDisplayState() for accurate ordering.
export const SYNC_SORT_ORDER: Record<string, number> = {
  DELIVERY_FAILED:  0,
  OUT_OF_SYNC:      1,
  PENDING_DELIVERY: 2,
  UPLOADING:        3,
  DOWNLOADING:      3,
  SYNCED:           4,
  SYNC_DISABLED:    5,
  NO_DELIVERY:      5,
}

export function isPendingDelivery(game: {
  sync_state: SyncState
  pending_delivery: boolean
  sync_enabled: boolean
}): boolean {
  return getDisplayState(game.sync_state, game.pending_delivery, game.sync_enabled) === 'PENDING_DELIVERY'
}

export const PENDING_LABEL = 'Pending'
export const RETRY_LABEL = 'Needs Retry'

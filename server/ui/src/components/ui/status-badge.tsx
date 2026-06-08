import { CheckCircle2, AlertTriangle, XCircle, Clock, Loader2, Archive } from 'lucide-react'
import * as React from 'react'
import { cn } from '@/lib/utils'
import type { GameStatus, SyncState } from '@/types'

type StatusVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'accent'

interface StatusConfig {
  label: string
  variant: StatusVariant
  Icon: React.ElementType
}

const GAME_STATUS_MAP: Record<GameStatus, StatusConfig> = {
  SYNCED:   { label: 'In Sync',  variant: 'success', Icon: CheckCircle2 },
  CONFLICT: { label: 'Conflict', variant: 'warning', Icon: AlertTriangle },
  ERROR:    { label: 'Error',    variant: 'error',   Icon: XCircle       },
  NO_DATA:  { label: 'No Data',  variant: 'neutral', Icon: Clock         },
}

const SYNC_STATE_MAP: Record<SyncState, StatusConfig> = {
  SYNCED:           { label: 'In Sync',        variant: 'success', Icon: CheckCircle2 },
  OUT_OF_SYNC:      { label: 'Needs Update',   variant: 'warning', Icon: AlertTriangle },
  UPLOADING:        { label: 'Uploading',      variant: 'accent',  Icon: Loader2      },
  DOWNLOADING:      { label: 'Downloading',    variant: 'accent',  Icon: Loader2      },
  NO_DELIVERY:      { label: 'Not Configured', variant: 'neutral', Icon: Archive      },
  DELIVERY_FAILED:  { label: 'Delivery Failed', variant: 'error',  Icon: XCircle      },
}

const VARIANT_CLASSES: Record<StatusVariant, string> = {
  success: 'bg-[var(--color-success-subtle)] text-[var(--color-success-text)] border-[var(--color-success-border)]',
  warning: 'bg-[var(--color-warning-subtle)] text-[var(--color-warning-text)] border-[var(--color-warning-border)]',
  error:   'bg-[var(--color-error-subtle)]   text-[var(--color-error-text)]   border-[var(--color-error-border)]',
  info:    'bg-[var(--color-info-subtle)]    text-[var(--color-info-text)]    border-[var(--color-info-border)]',
  neutral: 'bg-[var(--color-neutral-subtle)] text-[var(--color-neutral-text)] border-[var(--color-neutral-border)]',
  accent:  'bg-[var(--color-accent-subtle)]  text-[var(--color-accent)]       border-transparent',
}

interface StatusBadgeProps {
  gameStatus?: GameStatus
  syncState?: SyncState
  className?: string
  showIcon?: boolean
  size?: 'sm' | 'md' | 'lg'
}

export function StatusBadge({
  gameStatus,
  syncState,
  className,
  showIcon = true,
  size = 'md',
}: StatusBadgeProps) {
  const config = gameStatus
    ? GAME_STATUS_MAP[gameStatus]
    : syncState
      ? SYNC_STATE_MAP[syncState]
      : null

  if (!config) return null

  const { label, variant, Icon } = config

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-[var(--radius-full)] border font-[var(--font-weight-medium)] tracking-[0.04em] uppercase',
        size === 'sm'
          ? 'px-[6px] py-[1px] text-[10px]'
          : size === 'lg'
          ? 'px-[var(--spacing-3)] py-[var(--spacing-1)] text-sm'
          : 'px-[var(--spacing-2)] py-[2px] text-xs',
        VARIANT_CLASSES[variant],
        className,
      )}
    >
      {showIcon && (
        <Icon
          size={size === 'sm' ? 10 : 12}
          className={variant === 'accent' ? 'animate-spin' : ''}
          aria-hidden="true"
        />
      )}
      {label}
    </span>
  )
}

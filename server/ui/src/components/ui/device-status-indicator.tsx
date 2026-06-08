import * as React from 'react'
import { cn, relativeTime } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip'

interface DeviceStatusIndicatorProps {
  lastSeen: string
  className?: string
  showLabel?: boolean
}

const ONLINE_MS = 2 * 60_000

function isOnline(lastSeen: string): boolean {
  return Date.now() - new Date(lastSeen).getTime() < ONLINE_MS
}

export function DeviceStatusIndicator({ lastSeen, className, showLabel = false }: DeviceStatusIndicatorProps) {
  const [, tick] = React.useReducer((n: number) => n + 1, 0)
  React.useEffect(() => {
    const id = setInterval(tick, 30_000)
    return () => clearInterval(id)
  }, [])
  const online = isOnline(lastSeen)
  const label = online ? 'Online' : `Offline · Last seen ${relativeTime(lastSeen)}`

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn('inline-flex items-center gap-[var(--spacing-2)]', className)}>
          <span className="relative flex h-2 w-2">
            {online && (
              <span className="animate-device-pulse absolute inline-flex h-full w-full rounded-full bg-[var(--color-success)]" />
            )}
            <span
              className={cn(
                'relative inline-flex rounded-full h-2 w-2',
                online ? 'bg-[var(--color-success)]' : 'bg-[var(--color-text-muted)]',
              )}
            />
          </span>
          {/* Always present for screen readers; visible only when showLabel=true */}
          <span
            className={cn(
              'text-xs',
              online ? 'text-[var(--color-success)]' : 'text-[var(--color-text-muted)]',
              !showLabel && 'sr-only',
            )}
          >
            {online ? 'Online' : 'Offline'}
          </span>
        </span>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

import { Gamepad2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface GameIconProps {
  iconUrl: string | null | undefined
  name: string
  /** Fixed pixel size for list/table use (square). Pass 'full' to fill parent container. */
  size?: number | 'full'
  className?: string
}

export function GameIcon({ iconUrl, name, size = 40, className }: GameIconProps) {
  const isFull = size === 'full'
  const px = isFull ? undefined : (size as number)
  const style = isFull ? undefined : { width: px, height: px }

  if (iconUrl) {
    return (
      <img
        src={iconUrl}
        alt={name}
        width={px}
        height={px}
        className={cn(
          /* Grid/full mode: contain so the full cover is always visible */
          isFull ? 'w-full h-full object-contain' : 'object-cover',
          !isFull && 'rounded-[var(--radius-sm)] shrink-0 border border-[var(--color-border-subtle)]',
          className,
        )}
        style={style}
      />
    )
  }

  const iconSize = isFull ? 32 : Math.round((px ?? 40) * 0.5)

  return (
    <span
      className={cn(
        'flex items-center justify-center bg-[var(--color-bg-elevated)]',
        !isFull && 'shrink-0 rounded-[var(--radius-sm)] border border-[var(--color-border-subtle)]',
        isFull && 'w-full h-full',
        className,
      )}
      style={style}
      aria-hidden="true"
    >
      <Gamepad2 size={iconSize} className="text-[var(--color-text-muted)]" />
    </span>
  )
}

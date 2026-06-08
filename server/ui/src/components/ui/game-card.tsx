import { Link } from 'react-router-dom'
import { GameIcon } from '@/components/ui/game-icon'
import { RelativeTime } from '@/components/ui/relative-time'

interface GameCardProps {
  titleId: string
  displayName: string | null
  iconUrl: string | null
  lastActivity: string | null
}

export function GameCard({ titleId, displayName, iconUrl, lastActivity }: GameCardProps) {
  return (
    <Link to={`/game/${titleId}`} className="group flex flex-col gap-[var(--spacing-2)]">
      <div className="relative w-full aspect-[3/4] rounded-[var(--radius-md)] overflow-hidden bg-[var(--color-bg-elevated)] transition-[box-shadow] duration-[var(--motion-duration-fast)] group-hover:shadow-[0_0_0_1px_rgba(255,255,255,0.35)]">
        <GameIcon
          iconUrl={iconUrl}
          name={displayName ?? titleId}
          size="full"
          className="w-full h-full object-cover"
        />
      </div>
      <div className="flex flex-col gap-[2px]">
        <p className="text-sm font-[var(--font-weight-medium)] text-[var(--color-text-primary)] truncate">
          {displayName ?? <span className="font-mono">{titleId.slice(0, 10)}…</span>}
        </p>
        <p className="text-xs text-[var(--color-text-secondary)]">
          <RelativeTime iso={lastActivity} />
        </p>
      </div>
    </Link>
  )
}

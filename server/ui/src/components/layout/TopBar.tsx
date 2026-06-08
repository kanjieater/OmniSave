import { Bell, BellDot } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Breadcrumb } from './Breadcrumb'
import { ICON_NAV } from '@/lib/ui-scale'

interface TopBarProps {
  errorCount?: number
  onBellClick?: () => void
  className?: string
}

export function TopBar({ errorCount = 0, onBellClick, className }: TopBarProps) {
  const hasErrors = errorCount > 0

  return (
    <header
      role="banner"
      className={cn(
        'flex items-center h-[var(--layout-topbar)] pl-[8px] pr-[var(--spacing-4)]',
        'border-b border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)]',
        className,
      )}
    >
      {/* Breadcrumb (includes OmniSave logo + crumb trail) */}
      <div className="flex flex-1 min-w-0">
        <Breadcrumb />
      </div>

      {/* Bell — always on the right */}
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={onBellClick}
        aria-label={hasErrors ? `Notifications — ${errorCount} sync error${errorCount !== 1 ? 's' : ''}` : 'Notifications'}
        className="relative shrink-0 ml-[var(--spacing-2)]"
      >
        {hasErrors ? (
          <>
            <BellDot size={ICON_NAV} className="text-[var(--color-error)]" />
            <span
              className="absolute -top-1 -right-1 flex items-center justify-center h-4 min-w-4 rounded-[var(--radius-full)] px-[3px] bg-[var(--color-error)] text-white text-[10px] font-[var(--font-weight-bold)] leading-none"
              aria-hidden="true"
            >
              {errorCount > 9 ? '9+' : errorCount}
            </span>
          </>
        ) : (
          <Bell size={ICON_NAV} />
        )}
      </Button>
    </header>
  )
}

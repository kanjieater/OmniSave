import { Activity, Gamepad2, Monitor, Settings } from 'lucide-react'
import { NavLink, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { ICON_NAV } from '@/lib/ui-scale'

export function BottomNav({ className }: { className?: string }) {
  const location = useLocation()

  const isActive = (to: string) => location.pathname.startsWith(to)

  const items = [
    { label: 'Library',  icon: Gamepad2, to: '/library' },
    { label: 'Clients',  icon: Monitor,  to: '/devices' },
    { label: 'Activity', icon: Activity, to: '/activity' },
    { label: 'Settings', icon: Settings, to: '/settings' },
  ]

  return (
    <nav
      aria-label="Main navigation"
      className={`md:hidden fixed bottom-0 left-0 right-0 z-[var(--z-sticky)] flex border-t border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)]${className ? ` ${className}` : ''}`}
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      {items.map(({ label, icon: Icon, to }) => (
        <NavLink
          key={to}
          to={to}
          aria-current={isActive(to) ? 'page' : undefined}
          className={cn(
            'relative flex flex-1 flex-col items-center justify-center gap-[2px] py-[var(--spacing-1)] min-h-[var(--touch-bottom-nav)]',
            'text-[var(--color-text-muted)] transition-colors duration-[var(--motion-duration-fast)]',
            isActive(to) && 'text-[var(--color-accent)]',
          )}
        >
          <Icon size={ICON_NAV} aria-hidden="true" />
          <span className="text-xs font-[var(--font-weight-medium)]">{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

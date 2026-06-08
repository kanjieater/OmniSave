import {
  Activity,
  Gamepad2,
  Monitor,
  Settings,
} from 'lucide-react'
import * as React from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { ICON_NAV } from '@/lib/ui-scale'

interface NavItem {
  label: string
  icon: React.ElementType
  to: string
  badge?: number
  badgeVariant?: 'error' | 'warning'
}

interface SideNavProps {
  errorCount?: number
  conflictCount?: number
  onNavigate?: () => void
}

export function SideNav({ conflictCount = 0, onNavigate }: SideNavProps) {
  const location = useLocation()

  const items: NavItem[] = [
    { label: 'Library',  icon: Gamepad2, to: '/library',  badge: conflictCount > 0 ? conflictCount : undefined, badgeVariant: 'warning' },
    { label: 'Clients',  icon: Monitor,  to: '/devices' },
    { label: 'Activity', icon: Activity, to: '/activity' },
  ]

  const isActive = (to: string) => location.pathname.startsWith(to)

  return (
    <nav
      aria-label="Main navigation"
      className="flex flex-col h-full py-[var(--spacing-3)]"
    >
      {/* Nav items */}
      <ul className="flex flex-col gap-[var(--spacing-1)] px-[var(--spacing-1)] flex-1" role="list">
        {items.map(({ label, icon: Icon, to, badge, badgeVariant = 'error' }) => (
          <li key={to}>
            <NavLink
              to={to}
              onClick={onNavigate}
              aria-current={isActive(to) ? 'page' : undefined}
              className={cn(
                'relative flex items-center justify-center h-[var(--touch-nav)] w-[var(--touch-nav)] rounded-[var(--radius-md)] mx-auto',
                'text-[var(--color-text-muted)] transition-colors duration-[var(--motion-duration-fast)]',
                'hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]',
                'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-border-focus)]',
                isActive(to) && 'bg-[var(--color-bg-selected)] text-[var(--color-text-primary)]',
              )}
              title={label}
            >
              {isActive(to) && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[2px] h-5 rounded-r-full bg-[var(--color-accent)]" aria-hidden="true" />
              )}

              <Icon size={ICON_NAV} aria-hidden="true" />

              {badge != null && badge > 0 && (
                <span
                  className={cn(
                    'absolute -top-1 -right-1 flex items-center justify-center h-4 min-w-4 rounded-[var(--radius-full)] px-[3px] text-white text-[10px] font-[var(--font-weight-bold)] leading-none',
                    badgeVariant === 'warning'
                      ? 'bg-[var(--color-warning)] text-[var(--color-text-inverse)]'
                      : 'bg-[var(--color-error)]',
                  )}
                  aria-label={badgeVariant === 'warning' ? `${badge} conflicts` : `${badge} errors`}
                >
                  {badge > 9 ? '9+' : badge}
                </span>
              )}

              <span className="sr-only">{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      {/* Settings at bottom */}
      <div className="px-[var(--spacing-1)] mt-auto">
        <NavLink
          to="/settings"
          onClick={onNavigate}
          aria-current={location.pathname === '/settings' ? 'page' : undefined}
          className={cn(
            'relative flex items-center justify-center h-[var(--touch-nav)] w-[var(--touch-nav)] rounded-[var(--radius-md)] mx-auto',
            'text-[var(--color-text-muted)] transition-colors duration-[var(--motion-duration-fast)]',
            'hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]',
            'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-border-focus)]',
            location.pathname === '/settings' && 'bg-[var(--color-bg-selected)] text-[var(--color-text-primary)]',
          )}
          title="Settings"
        >
          {location.pathname === '/settings' && (
            <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[2px] h-5 rounded-r-full bg-[var(--color-accent)]" aria-hidden="true" />
          )}
          <Settings size={ICON_NAV} aria-hidden="true" />
          <span className="sr-only">Settings</span>
        </NavLink>
      </div>
    </nav>
  )
}

import { ChevronRight } from 'lucide-react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import type { Device, GameDetail } from '@/types'
import { cn } from '@/lib/utils'
import { ICON_TINY } from '@/lib/ui-scale'

interface Crumb {
  label: string
  to?: string
}

function useBreadcrumbs(): Crumb[] {
  const location = useLocation()
  const params = useParams()
  const qc = useQueryClient()
  const path = location.pathname

  if (path === '/' || path === '/dashboard') return []

  if (path === '/library') return [{ label: 'Library' }]

  if (path.startsWith('/game/')) {
    const titleId = params.title_id ?? ''
    const cached = qc.getQueryData<GameDetail>(['game', titleId])
    const label = cached?.display_name ?? (titleId ? titleId.slice(0, 12) : 'Game')
    return [{ label: 'Library', to: '/library' }, { label }]
  }

  if (path === '/devices') return [{ label: 'Clients' }]

  if (path.startsWith('/devices/')) {
    const deviceId = params.device_id ?? ''
    const devicesData = qc.getQueryData<{ devices: Device[] }>(['devices'])
    const device = devicesData?.devices.find((d) => d.device_id === deviceId)
    const label = device?.display_name ?? (deviceId ? deviceId.slice(0, 8) : 'Client')
    return [{ label: 'Clients', to: '/devices' }, { label }]
  }

  if (path === '/activity') return [{ label: 'Activity' }]
  if (path === '/settings') return [{ label: 'Settings' }]

  return []
}

function LogoHome({ linkTo }: { linkTo?: string }) {
  return (
    <Link
      to={linkTo ?? '/dashboard'}
      aria-label="Go to Dashboard"
      aria-current={linkTo ? undefined : 'page'}
      className="h-[var(--touch-nav)] flex items-center focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-border-focus)] rounded-[var(--radius-sm)]"
    >
      <span className="flex items-center gap-[var(--spacing-4)]">
        <img src="/omnisave.svg" alt="" aria-hidden="true" className="w-10 h-10 md:w-[var(--touch-nav)] md:h-[var(--touch-nav)] shrink-0" />
        <span className="text-sm md:text-base font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] tracking-[0.02em]">
          OmniSave
        </span>
      </span>
    </Link>
  )
}

export function Breadcrumb({ className }: { className?: string }) {
  const crumbs = useBreadcrumbs()
  const onDashboard = crumbs.length === 0

  // Mobile: collapse deep paths to … / penultimate / current
  const isTruncated = crumbs.length > 2
  const visibleCrumbs = isTruncated ? crumbs.slice(-2) : crumbs

  return (
    <nav aria-label="Breadcrumb" className={cn('flex items-center', className)}>
      <ol className="flex items-center gap-[var(--spacing-1)]">
        {/* Logo — home link on sub-pages, static on dashboard */}
        <li className="flex items-center">
          <LogoHome linkTo={onDashboard ? undefined : '/dashboard'} />
        </li>

        {/* Sub-page crumbs */}
        {isTruncated && (
          <li className="flex items-center gap-[var(--spacing-1)]">
            <ChevronRight size={ICON_TINY} className="text-[var(--color-text-muted)]" aria-hidden="true" />
            <span className="text-sm text-[var(--color-text-muted)]" aria-hidden="true">…</span>
          </li>
        )}
        {visibleCrumbs.map((crumb, i) => {
          const isLast = i === visibleCrumbs.length - 1
          return (
            <li key={i} className="flex items-center gap-[var(--spacing-1)]">
              <ChevronRight size={ICON_TINY} className="text-[var(--color-text-muted)]" aria-hidden="true" />
              {isLast || !crumb.to ? (
                <span
                  className="text-sm text-[var(--color-text-secondary)] truncate max-w-48"
                  aria-current={isLast ? 'page' : undefined}
                >
                  {crumb.label}
                </span>
              ) : (
                <Link
                  to={crumb.to}
                  className="text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors duration-[var(--motion-duration-fast)] truncate max-w-48"
                >
                  {crumb.label}
                </Link>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

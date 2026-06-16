import * as React from 'react'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  icon?: React.ReactNode
  title: string
  description?: React.ReactNode
  action?: React.ReactNode
  className?: string
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-[var(--spacing-3)] py-[var(--spacing-12)] px-[var(--spacing-6)] text-center',
        className,
      )}
    >
      {icon && (
        <div className="text-[var(--color-text-muted)]" aria-hidden="true">
          {icon}
        </div>
      )}
      <div className="flex flex-col gap-[var(--spacing-1)]">
        <p className="text-base font-[var(--font-weight-medium)] text-[var(--color-text-primary)]">
          {title}
        </p>
        {description && (
          <p className="text-sm text-[var(--color-text-secondary)] max-w-xs">
            {description}
          </p>
        )}
      </div>
      {action && <div>{action}</div>}
    </div>
  )
}

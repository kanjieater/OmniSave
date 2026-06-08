import { type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Skeleton } from './skeleton'

interface SummaryCardProps {
  label: string
  value: number | string
  icon: LucideIcon
  variant?: 'default' | 'alert' | 'info'
  loading?: boolean
}

export function SummaryCard({ label, value, icon: Icon, variant = 'default', loading = false }: SummaryCardProps) {
  const iconColor = variant === 'alert'
    ? 'text-[var(--color-error)]'
    : variant === 'info'
    ? 'text-[var(--color-info)]'
    : 'text-[var(--color-text-muted)]'

  const valueColor = variant === 'alert'
    ? 'text-[var(--color-error)]'
    : variant === 'info'
    ? 'text-[var(--color-info)]'
    : 'text-[var(--color-text-primary)]'

  return (
    <div
      className={cn(
        'flex flex-col gap-[var(--spacing-3)] p-[var(--spacing-4)] rounded-[var(--radius-lg)]',
        'border border-[var(--color-border-subtle)] bg-[var(--color-bg-subtle)]',
        variant === 'alert' && 'border-[var(--color-error-border)]',
      )}
      role="status"
      aria-live="polite"
      aria-label={`${label}: ${loading ? 'loading' : value}`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-[var(--font-weight-medium)] text-[var(--color-text-muted)] uppercase tracking-[0.06em]">
          {label}
        </span>
        <Icon size={14} className={iconColor} aria-hidden="true" />
      </div>
      {loading ? (
        <Skeleton className="h-8 w-16" />
      ) : (
        <span className={cn('text-[2rem] font-[var(--font-weight-semibold)] leading-none tabular-nums', valueColor)}>
          {value}
        </span>
      )}
    </div>
  )
}

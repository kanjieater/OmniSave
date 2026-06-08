import { type VariantProps, cva } from 'class-variance-authority'
import * as React from 'react'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-[var(--radius-full)] px-[var(--spacing-2)] text-xs font-[var(--font-weight-medium)] tracking-[0.04em] uppercase border',
  {
    variants: {
      variant: {
        default:
          'bg-[var(--color-bg-elevated)] text-[var(--color-text-secondary)] border-[var(--color-border-base)]',
        success:
          'bg-[var(--color-success-subtle)] text-[var(--color-success-text)] border-[var(--color-success-border)]',
        warning:
          'bg-[var(--color-warning-subtle)] text-[var(--color-warning-text)] border-[var(--color-warning-border)]',
        error:
          'bg-[var(--color-error-subtle)] text-[var(--color-error-text)] border-[var(--color-error-border)]',
        info:
          'bg-[var(--color-info-subtle)] text-[var(--color-info-text)] border-[var(--color-info-border)]',
        neutral:
          'bg-[var(--color-neutral-subtle)] text-[var(--color-neutral-text)] border-[var(--color-neutral-border)]',
        accent:
          'bg-[var(--color-accent-subtle)] text-[var(--color-accent)] border-[var(--color-accent-subtle)]',
      },
      size: {
        sm: 'h-4 text-[10px]',
        md: 'h-5',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'md',
    },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, size, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant, size }), className)} {...props} />
  )
}

export { Badge, badgeVariants }

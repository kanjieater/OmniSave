import * as React from 'react'
import { cn } from '@/lib/utils'

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: boolean
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, error, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        'flex min-h-20 w-full rounded-[var(--radius-sm)] border',
        'bg-[var(--color-bg-input)] px-[var(--spacing-3)] py-[var(--spacing-2)]',
        'text-sm text-[var(--color-text-primary)]',
        'placeholder:text-[var(--color-text-muted)]',
        'transition-colors duration-[var(--motion-duration-fast)]',
        'resize-y',
        error
          ? 'border-[var(--color-border-error)] focus-visible:border-[var(--color-border-error)]'
          : 'border-[var(--color-border-base)] focus-visible:border-[var(--color-border-focus)]',
        'focus-visible:outline-none focus-visible:ring-1',
        error
          ? 'focus-visible:ring-[var(--color-border-error)]'
          : 'focus-visible:ring-[var(--color-border-focus)]',
        'disabled:cursor-not-allowed disabled:opacity-40',
        className,
      )}
      {...props}
    />
  ),
)
Textarea.displayName = 'Textarea'

export { Textarea }

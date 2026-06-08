import * as React from 'react'
import { cn } from '@/lib/utils'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  error?: boolean
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, error, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          'flex h-[var(--touch-md)] w-full rounded-[var(--radius-sm)] bg-[var(--color-bg-input)] px-[var(--spacing-3)] py-[var(--spacing-1)] text-sm text-[var(--color-text-primary)] border transition-colors duration-[var(--motion-duration-fast)]',
          'placeholder:text-[var(--color-text-muted)]',
          'focus-visible:outline-none focus-visible:border-[var(--color-border-focus)]',
          'disabled:cursor-not-allowed disabled:opacity-40',
          error
            ? 'border-[var(--color-border-error)]'
            : 'border-[var(--color-border-base)] hover:border-[var(--color-border-strong)]',
          className,
        )}
        ref={ref}
        {...props}
      />
    )
  },
)
Input.displayName = 'Input'

export { Input }

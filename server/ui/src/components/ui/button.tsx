import { Slot } from '@radix-ui/react-slot'
import { type VariantProps, cva } from 'class-variance-authority'
import * as React from 'react'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-md)] text-sm font-[var(--font-weight-medium)] transition-colors duration-[var(--motion-duration-fast)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)] disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default:
          'bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)]',
        secondary:
          'bg-[var(--color-bg-elevated)] text-[var(--color-text-primary)] border border-[var(--color-border-base)] hover:bg-[var(--color-bg-hover)] hover:border-[var(--color-border-strong)]',
        ghost:
          'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]',
        destructive:
          'bg-[var(--color-error-subtle)] text-[var(--color-error-text)] border border-[var(--color-error-border)] hover:bg-[var(--color-error)] hover:text-white',
        link:
          'text-[var(--color-text-link)] underline-offset-4 hover:underline p-0 h-auto',
      },
      size: {
        sm: 'h-[var(--touch-sm)] px-[var(--comp-px-sm)] text-xs',
        md: 'h-[var(--touch-md)] px-[var(--comp-px-md)]',
        lg: 'h-[var(--touch-lg)] px-[var(--comp-px-lg)]',
        icon: 'h-[var(--touch-icon-md)] w-[var(--touch-icon-md)]',
        'icon-sm': 'h-[var(--touch-icon-sm)] w-[var(--touch-icon-sm)]',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'md',
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  },
)
Button.displayName = 'Button'

export { Button, buttonVariants }

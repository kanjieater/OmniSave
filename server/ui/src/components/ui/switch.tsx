import * as SwitchPrimitive from '@radix-ui/react-switch'
import { Loader2 } from 'lucide-react'
import * as React from 'react'
import { cn } from '@/lib/utils'

interface SwitchProps extends React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root> {
  loading?: boolean
  wrapperClassName?: string
}

const Switch = React.forwardRef<React.ElementRef<typeof SwitchPrimitive.Root>, SwitchProps>(
  ({ className, loading, disabled, wrapperClassName, ...props }, ref) => (
    /* 44×44px invisible tap target wrapper — spec requirement */
    <span className={cn('inline-flex items-center justify-center min-h-[var(--touch-md)] min-w-[var(--touch-md)]', wrapperClassName)}>
      <SwitchPrimitive.Root
        className={cn(
          'peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-[var(--radius-full)] border border-transparent',
          'transition-colors duration-[var(--motion-duration-fast)]',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)]',
          'disabled:cursor-not-allowed disabled:opacity-40',
          'data-[state=checked]:bg-[var(--color-accent)] data-[state=unchecked]:bg-[var(--color-bg-hover)]',
          'data-[state=unchecked]:border-[var(--color-border-base)]',
          className,
        )}
        disabled={loading || disabled}
        aria-busy={loading}
        ref={ref}
        {...props}
      >
        <SwitchPrimitive.Thumb
          className={cn(
            'pointer-events-none relative block h-3.5 w-3.5 rounded-[var(--radius-full)]',
            'transition-transform duration-[var(--motion-duration-fast)]',
            'data-[state=checked]:translate-x-[18px] data-[state=unchecked]:translate-x-[3px]',
            loading ? 'bg-transparent' : 'bg-white shadow-sm',
          )}
        >
          {loading && (
            <Loader2
              size={10}
              className="absolute inset-0 m-auto text-[var(--color-text-secondary)] animate-spin"
            />
          )}
        </SwitchPrimitive.Thumb>
      </SwitchPrimitive.Root>
    </span>
  ),
)
Switch.displayName = SwitchPrimitive.Root.displayName

export { Switch }

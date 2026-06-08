import { WifiOff, RefreshCw } from 'lucide-react'
import { Button } from './button'

interface OfflineBannerProps {
  retryIn?: number
  onRetry?: () => void
}

export function OfflineBanner({ retryIn, onRetry }: OfflineBannerProps) {
  return (
    <div
      role="alert"
      className="flex items-center gap-[var(--spacing-3)] px-[var(--spacing-6)] py-[var(--spacing-3)] bg-[var(--color-error-subtle)] border-b border-[var(--color-error-border)]"
    >
      <WifiOff size={16} className="text-[var(--color-error)] shrink-0" aria-hidden="true" />
      <div className="flex-1 text-sm">
        <span className="font-[var(--font-weight-medium)] text-[var(--color-error-text)]">
          Connection lost —{' '}
        </span>
        <span className="text-[var(--color-text-secondary)]">
          OmniSave server is unreachable.
          {retryIn != null && retryIn > 0 && ` Retrying in ${retryIn}s…`}
        </span>
      </div>
      {onRetry && (
        <Button
          variant="ghost"
          size="sm"
          onClick={onRetry}
          className="shrink-0 text-[var(--color-error-text)] hover:text-white hover:bg-[var(--color-error)]"
        >
          <RefreshCw size={12} />
          Retry now
        </Button>
      )}
    </div>
  )
}

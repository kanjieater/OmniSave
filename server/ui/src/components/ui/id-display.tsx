import { Copy, Check } from 'lucide-react'
import * as React from 'react'
import { cn, truncateId } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip'

interface IdDisplayProps {
  id: string
  chars?: number
  label?: string
  className?: string
}

export function IdDisplay({ id, chars = 8, label, className }: IdDisplayProps) {
  const [copied, setCopied] = React.useState(false)

  const handleCopy = () => {
    void navigator.clipboard.writeText(id)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={handleCopy}
          className={cn(
            'inline-flex items-center gap-1 rounded-[var(--radius-sm)] px-[var(--spacing-1)]',
            'font-mono text-xs text-[var(--color-text-secondary)]',
            'hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)]',
            'transition-colors duration-[var(--motion-duration-fast)] cursor-pointer',
            'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--color-border-focus)]',
            className,
          )}
          aria-label={`${label ?? 'ID'}: ${id}. Click to copy.`}
        >
          <span aria-hidden="true">{truncateId(id, chars)}</span>
          {copied
            ? <Check size={10} className="text-[var(--color-success)]" />
            : <Copy size={10} className="opacity-50" />
          }
        </button>
      </TooltipTrigger>
      <TooltipContent>
        <p className="font-mono">{id}</p>
        <p className="text-[var(--color-text-muted)] mt-[2px]">Click to copy</p>
      </TooltipContent>
    </Tooltip>
  )
}

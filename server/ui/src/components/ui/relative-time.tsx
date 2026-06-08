import * as React from 'react'
import { absoluteTime, relativeTime, relativeTimeInterval } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip'

interface RelativeTimeProps {
  iso: string | null | undefined
  className?: string
  /** 'relative' — "3h ago" with absolute in tooltip (default)
   *  'absolute' — "May 28, 14:32" with relative in tooltip */
  format?: 'relative' | 'absolute'
}

export function RelativeTime({ iso, className, format = 'relative' }: RelativeTimeProps) {
  const [, tick] = React.useReducer((x: number) => x + 1, 0)

  React.useEffect(() => {
    const ms = relativeTimeInterval(iso)
    if (ms === null) return
    const id = setInterval(tick, ms)
    return () => clearInterval(id)
  }, [iso])

  if (!iso) {
    return <span className={className}>Never synced</span>
  }

  const rel = relativeTime(iso)
  const abs = absoluteTime(iso)

  const display = format === 'absolute' ? abs : rel
  const tooltip = format === 'absolute' ? rel : abs

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <time dateTime={iso} className={className} style={{ cursor: 'default' }}>
          {display}
        </time>
      </TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  )
}

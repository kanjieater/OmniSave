import { Monitor } from 'lucide-react'
import { cn } from '@/lib/utils'
import switchSvgRaw from '@/assets/switch.svg?raw'
import rommUrl from '@/assets/romm.svg'

const switchSvgCurrentColor = switchSvgRaw
  .replace(/fill="#[0-9a-fA-F]{3,6}"/g, 'fill="currentColor"')
  .replace(/<svg([^>]*)\s+width="[^"]*"/, '<svg$1')
  .replace(/<svg([^>]*)\s+height="[^"]*"/, '<svg$1')
  .replace('<svg', '<svg width="100%" height="100%"')

function SwitchImg({ size, className }: { size: number; className?: string }) {
  return (
    <span
      className={className}
      style={{ width: size, height: size, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
      dangerouslySetInnerHTML={{ __html: switchSvgCurrentColor }}
      aria-hidden="true"
    />
  )
}

function RommImg({ size, className }: { size: number; className?: string }) {
  return (
    <img
      src={rommUrl}
      width={size}
      height={size}
      className={cn('grayscale opacity-50', className)}
      aria-hidden="true"
      alt=""
    />
  )
}

interface HardwareIconProps {
  clientType?: string | null | undefined
  hardwareType?: string | null | undefined
  size?: number
  className?: string
}

export function HardwareIcon({ clientType, size = 20, className }: HardwareIconProps) {
  const ct = (clientType ?? '').toLowerCase()

  return (
    <span className="inline-flex items-center justify-center shrink-0">
      {ct === 'switch' ? (
        <SwitchImg size={size} className={cn('text-[var(--color-text-secondary)]', className)} />
      ) : ct === 'romm' ? (
        <RommImg size={size} className={className} />
      ) : (
        <Monitor size={size} className={cn('text-[var(--color-text-secondary)]', className)} aria-hidden="true" />
      )}
    </span>
  )
}

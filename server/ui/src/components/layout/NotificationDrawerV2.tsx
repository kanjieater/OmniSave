import { AlertTriangle, CheckCheck, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api'
import type { AppError } from '@/types'
import { ICON_SM } from '@/lib/ui-scale'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { GameIcon } from '@/components/ui/game-icon'
import { HardwareIcon } from '@/components/ui/hardware-icon'
import { RelativeTime } from '@/components/ui/relative-time'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'

interface NotificationDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function NotificationDrawerV2({ open, onOpenChange }: NotificationDrawerProps) {
  const qc = useQueryClient()

  const { data } = useQuery({
    queryKey: ['errors'],
    queryFn: () => api.errors(),
    refetchInterval: 30_000,
  })

  const errors: AppError[] = (data?.errors ?? []).filter((e) => !e.acknowledged)

  const ack = useMutation({
    mutationFn: (txnId: string) => api.acknowledge(txnId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['errors'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const ackAll = () => errors.forEach((e) => ack.mutate(e.transaction_id))
  const close = () => onOpenChange(false)

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="[animation-timing-function:var(--motion-ease-spring)]">
        <SheetHeader>
          <SheetTitle>Sync Errors</SheetTitle>
        </SheetHeader>

        {errors.length > 0 && (
          <div className="px-[var(--spacing-5)] py-[var(--spacing-3)] border-b border-[var(--color-border-subtle)] flex items-center justify-between">
            <span className="text-sm text-[var(--color-text-muted)]">
              {errors.length} error{errors.length !== 1 ? 's' : ''}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={ackAll}
              className="flex items-center gap-[var(--spacing-1)] text-[var(--color-text-muted)]"
            >
              <CheckCheck size={14} />
              Dismiss all
            </Button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          {errors.length === 0 ? (
            <EmptyState
              icon={<AlertTriangle size={32} />}
              title="No errors"
              description="All syncs are healthy."
            />
          ) : (
            <ul className="flex flex-col" role="list">
              {errors.map((error) => (
                <li
                  key={error.transaction_id}
                  className="flex items-center gap-[var(--spacing-3)] px-[var(--spacing-4)] py-[var(--spacing-4)] border-b border-[var(--color-border-subtle)] hover:bg-[var(--color-bg-hover)] transition-colors"
                >
                  {/* Game icon */}
                  {error.title_id ? (
                    <Link to={`/game/${error.title_id}`} onClick={close} className="shrink-0" tabIndex={-1} aria-hidden="true">
                      <GameIcon iconUrl={error.icon_url ?? null} name={error.game_name ?? ''} size={52} />
                    </Link>
                  ) : (
                    <GameIcon iconUrl={null} name="" size={52} className="shrink-0" />
                  )}

                  {/* Text block — primary tap area, navigates to game */}
                  <Link
                    to={error.title_id ? `/game/${error.title_id}` : '#'}
                    onClick={error.title_id ? close : undefined}
                    className="flex-1 min-w-0 flex flex-col gap-[var(--spacing-1)]"
                  >
                    <p className="text-base font-[var(--font-weight-medium)] text-[var(--color-text-primary)] truncate">
                      {error.game_name ?? 'Unknown game'}
                    </p>
                    <p className="text-sm text-[var(--color-text-muted)] truncate">
                      {error.direction === 'inbound' ? 'Upload failed' : 'Download failed'}
                    </p>
                    <div className="flex items-center gap-[var(--spacing-1)] text-xs text-[var(--color-text-muted)]">
                      <HardwareIcon
                        clientType={error.client_type ?? null}
                        hardwareType={error.hardware_type ?? null}
                        size={14}
                      />
                      <span className="truncate max-w-[8rem]">
                        {error.device_name ?? error.device_id.slice(0, 8)}
                      </span>
                      <span aria-hidden="true">·</span>
                      <RelativeTime iso={error.created_at} />
                    </div>
                  </Link>

                  {/* Dismiss */}
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => ack.mutate(error.transaction_id)}
                    disabled={ack.isPending}
                    aria-label="Dismiss"
                    className="shrink-0"
                  >
                    <X size={ICON_SM} />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

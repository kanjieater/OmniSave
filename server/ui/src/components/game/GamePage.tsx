import * as React from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api'
import { useBackground } from '@/components/layout/AppShellV2'
import type { GameDetail } from '@/types'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { DayHeatmap } from '@/components/ui/day-heatmap'
import { RommSearchSheet } from './RommSearchSheet'
import { SnapshotTimeline } from './SnapshotTimeline'

export default function GamePage() {
  const { title_id } = useParams<{ title_id: string }>()
  const qc = useQueryClient()
  const [rommOpen, setRommOpen] = React.useState(false)
  const setBg = useBackground()

  const { data: rommSettings } = useQuery({
    queryKey: ['romm-settings'],
    queryFn: () => api.rommServerSettings(),
    staleTime: 60_000,
  })
  const rommEnabled = rommSettings?.enabled ?? false
  const rommHost = rommSettings?.host ?? null

  const { data, isLoading } = useQuery<GameDetail>({
    queryKey: ['game', title_id],
    queryFn: () => api.gameDetail(title_id!),
    enabled: !!title_id,
    refetchInterval: (query) => {
      const d = query.state.data
      if (!d) return 30_000
      const states = d.device_sync_matrix.map((e) => e.sync_state)
      if (states.includes('DOWNLOADING') || states.includes('UPLOADING')) return 4_000
      if (states.includes('OUT_OF_SYNC')) return 10_000
      return 30_000
    },
    refetchOnWindowFocus: true,
  })

  const { data: playtimeData, isLoading: playtimeLoading } = useQuery({
    queryKey: ['playtime-daily', title_id],
    queryFn: () => api.dailyPlaytime(title_id),
    enabled: !!title_id,
    staleTime: 60_000,
  })

  React.useEffect(() => { if (data?.icon_url) setBg(data.icon_url) }, [data?.icon_url, setBg])

  const saveLabel = async (newName: string) => {
    if (!title_id) return
    if (newName.trim()) await api.setGameLabel(title_id, newName.trim())
    else await api.clearGameLabel(title_id)
    await qc.invalidateQueries({ queryKey: ['game', title_id] })
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-[var(--spacing-6)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">
        <Skeleton className="h-40 w-full rounded-[var(--radius-lg)]" />
        <Skeleton className="h-32 w-full rounded-[var(--radius-lg)]" />
      </div>
    )
  }

  if (!data) return (
    <div className="flex flex-col gap-[var(--spacing-6)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">
      <EmptyState title="Game not found" description="This game may have been removed." />
    </div>
  )

  const gameName = data.display_name ?? data.title_id

  return (
    <div className="flex flex-col gap-[var(--spacing-6)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">
      <SnapshotTimeline
        data={data}
        titleId={title_id!}
        gameName={gameName}
        gameIconUrl={data.icon_url}
        onSaveGameName={saveLabel}
        onRommSearch={() => setRommOpen(true)}
        rommEnabled={rommEnabled}
        rommHost={rommHost}
      />

      <RommSearchSheet
        open={rommOpen}
        onOpenChange={setRommOpen}
        titleId={title_id!}
        initialQuery={gameName}
        rommHost={rommHost}
      />

      <section className="flex flex-col gap-[var(--spacing-2)]">
        <h2 className="text-sm font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] uppercase tracking-[var(--tracking-wide)]">Play History</h2>
        {playtimeLoading ? (
          <Skeleton className="h-24 w-full rounded-[var(--radius-md)]" />
        ) : (
          <DayHeatmap data={playtimeData?.days ?? []} />
        )}
      </section>
    </div>
  )
}

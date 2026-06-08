import { RefreshCw, Search } from 'lucide-react'
import * as React from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '@/api'
import { useBackground } from '@/components/layout/AppShellV2'
import { useLocalStorage } from '@/lib/useLocalStorage'
import type { Game } from '@/types'
import { Button } from '@/components/ui/button'
import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/ui/empty-state'
import { GameCard } from '@/components/ui/game-card'
import { Input } from '@/components/ui/input'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

type SortKey = 'recent' | 'name' | 'status'

const STATUS_ORDER: Record<string, number> = {
  CONFLICT: 0,
  ERROR:    1,
  SYNCED:   2,
  NO_DATA:  3,
}

function sortGames(games: Game[], key: SortKey): Game[] {
  return [...games].sort((a, b) => {
    if (key === 'name') {
      const na = (a.display_name ?? a.title_id).toLowerCase()
      const nb = (b.display_name ?? b.title_id).toLowerCase()
      return na.localeCompare(nb)
    }
    if (key === 'status') {
      const diff = (STATUS_ORDER[a.status] ?? 4) - (STATUS_ORDER[b.status] ?? 4)
      if (diff !== 0) return diff
    }
    const ta = a.last_activity ? new Date(a.last_activity).getTime() : -Infinity
    const tb = b.last_activity ? new Date(b.last_activity).getTime() : -Infinity
    return tb - ta
  })
}

export default function LibraryPage() {
  const [search, setSearch] = React.useState('')
  const [sortKey, setSortKey] = useLocalStorage<SortKey>('pref:library:sort', 'recent')

  const { data, isLoading } = useQuery({
    queryKey: ['games'],
    queryFn: () => api.games(),
    refetchInterval: 30_000,
    staleTime: 0,
    refetchOnWindowFocus: true,
  })

  const { data: rommSettings, isLoading: isRommLoading } = useQuery({
    queryKey: ['romm-settings'],
    queryFn: () => api.rommServerSettings(),
    staleTime: 60_000,
  })
  const rommEnabled = rommSettings?.enabled ?? false

  const scan = useMutation({
    mutationFn: () => api.triggerRommScan(),
  })

  const games: Game[] = data?.games ?? []

  const setBg = useBackground()
  const pickedRef = React.useRef(false)
  React.useEffect(() => {
    if (pickedRef.current || games.length === 0) return
    const candidates = games.filter(g => g.icon_url)
    if (candidates.length === 0) return
    pickedRef.current = true
    const pick = candidates[Math.floor(Math.random() * candidates.length)]
    setBg(pick.icon_url!)
  }, [games, setBg])

  const filtered = React.useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return games
    return games.filter((g) =>
      (g.display_name ?? '').toLowerCase().includes(q) ||
      g.title_id.toLowerCase().includes(q),
    )
  }, [games, search])

  const sorted = React.useMemo(() => sortGames(filtered, sortKey), [filtered, sortKey])

  return (
    <div className="flex flex-col gap-[var(--spacing-6)] p-[var(--spacing-4)] md:p-[var(--spacing-6)] max-w-5xl mx-auto">

      {/* Controls row */}
      <div className="flex items-center gap-[var(--spacing-3)]">
        <div className="relative flex-1 md:max-w-xs">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]"
            aria-hidden="true"
          />
          <Input
            placeholder="Search games…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8"
            aria-label="Search games"
          />
        </div>

        <Select value={sortKey} onValueChange={(v) => setSortKey(v as SortKey)}>
          <SelectTrigger className="w-28 md:w-36" aria-label="Sort games by">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="recent">Recent</SelectItem>
            <SelectItem value="name">Name</SelectItem>
            <SelectItem value="status">Status</SelectItem>
          </SelectContent>
        </Select>

        <span className={cn('hidden md:block text-sm text-[var(--color-text-muted)] shrink-0 w-20 text-right tabular-nums', isLoading && 'invisible')}>
          {filtered.length} {filtered.length === 1 ? 'game' : 'games'}
        </span>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => scan.mutate()}
              disabled={scan.isPending || isRommLoading || !rommEnabled}
              aria-label="Scan for missing RomM titles"
              className={cn('shrink-0 ml-auto text-[var(--color-text-muted)]', (!rommEnabled || isRommLoading) && 'invisible pointer-events-none')}
            >
              <RefreshCw size={15} className={scan.isPending ? 'animate-spin' : ''} />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{scan.isSuccess ? 'Scan queued' : 'Scan for missing titles'}</TooltipContent>
        </Tooltip>
      </div>

      {/* Grid */}
      {isLoading ? (
        <div className="grid grid-cols-3 md:grid-cols-5 gap-x-[var(--spacing-3)] gap-y-[var(--spacing-5)]">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <div key={i} className="flex flex-col gap-[var(--spacing-2)]">
              <Skeleton className="w-full aspect-[3/4] rounded-[var(--radius-md)]" />
              <Skeleton className="h-3 w-3/4" />
            </div>
          ))}
        </div>
      ) : sorted.length === 0 ? (
        search ? (
          <EmptyState title="No results" description={`No games match "${search}"`} />
        ) : (
          <EmptyState
            title="No games yet"
            description="Claim a profile on a device to see your saves here."
            action={
              <Link
                to="/devices"
                className="text-sm font-[var(--font-weight-medium)] text-[var(--color-text-primary)] underline underline-offset-2 hover:text-[var(--color-text-secondary)]"
              >
                Go to Devices →
              </Link>
            }
          />
        )
      ) : (
        <div className="grid grid-cols-3 md:grid-cols-5 gap-x-[var(--spacing-3)] gap-y-[var(--spacing-5)]">
          {sorted.map((game) => (
            <GameCard
              key={game.title_id}
              titleId={game.title_id}
              displayName={game.display_name}
              iconUrl={game.icon_url}
              lastActivity={game.last_activity}
            />
          ))}
        </div>
      )}
    </div>
  )
}

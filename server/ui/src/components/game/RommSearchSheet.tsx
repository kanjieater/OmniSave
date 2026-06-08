import { ExternalLink, Loader2, Search } from 'lucide-react'
import * as React from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api'
import type { RommResult } from '@/types'
import { GameIcon } from '@/components/ui/game-icon'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'

interface RommSearchSheetProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  titleId: string
  initialQuery?: string
  rommHost?: string | null
}

export function RommSearchSheet({ open, onOpenChange, titleId, initialQuery, rommHost }: RommSearchSheetProps) {
  const qc = useQueryClient()
  const [query, setQuery] = React.useState('')
  const [results, setResults] = React.useState<RommResult[]>([])
  const [searching, setSearching] = React.useState(false)
  const inputRef = React.useRef<HTMLInputElement>(null)

  const map = useMutation({
    mutationFn: (romId: number) => api.setRommMapping(titleId, romId),
    onSuccess: () => {
      void qc.refetchQueries({ queryKey: ['game', titleId] })
      void qc.refetchQueries({ queryKey: ['games'] })
      onOpenChange(false)
    },
  })

  // Immediate searching feedback; debounce the actual API call
  React.useEffect(() => {
    if (!query.trim()) {
      setResults([])
      setSearching(false)
      return
    }
    setSearching(true)
    const t = setTimeout(async () => {
      try {
        const data = await api.searchRomm(query, 20)
        setResults(data.results)
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    }, 350)
    return () => clearTimeout(t)
  }, [query])

  // Pre-populate + trigger search when sheet opens
  React.useEffect(() => {
    if (open) {
      map.reset()
      setResults([])
      setSearching(false)
      const q = initialQuery?.trim() ?? ''
      setQuery(q)
      setTimeout(() => {
        inputRef.current?.focus()
        inputRef.current?.select()
      }, 50)
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex flex-col gap-0 p-0">
        <SheetHeader className="px-[var(--spacing-5)] pt-[var(--spacing-5)] pb-[var(--spacing-4)] border-b border-[var(--color-border-subtle)]">
          <SheetTitle>Link to RomM Library</SheetTitle>
        </SheetHeader>

        {/* Search input */}
        <div className="px-[var(--spacing-4)] py-[var(--spacing-3)] border-b border-[var(--color-border-subtle)]">
          <div className="flex items-center gap-[var(--spacing-2)] rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] px-[var(--spacing-3)] py-[var(--spacing-2)]">
            {searching
              ? <Loader2 size={14} className="text-[var(--color-text-muted)] shrink-0 animate-spin" />
              : <Search size={14} className="text-[var(--color-text-muted)] shrink-0" />
            }
            <input
              ref={inputRef}
              type="search"
              placeholder="Search RomM…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1 bg-transparent text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] outline-none"
            />
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto">
          {!searching && query.trim() && results.length === 0 && (
            <p className="px-[var(--spacing-4)] py-[var(--spacing-3)] text-sm text-[var(--color-text-muted)]">
              No results found
            </p>
          )}
          {results.map((r) => {
            const isLinking = map.isPending && map.variables === r.id
            const rommUrl = rommHost ? `${rommHost.replace(/\/$/, '')}/rom/${r.id}` : null
            return (
              <div
                key={r.id}
                className="flex items-center border-b border-[var(--color-border-subtle)] last:border-b-0"
              >
                <button
                  type="button"
                  disabled={map.isPending}
                  onClick={() => map.mutate(r.id)}
                  className="flex-1 flex items-center gap-[var(--spacing-3)] px-[var(--spacing-4)] py-[var(--spacing-3)] hover:bg-[var(--color-bg-hover)] transition-colors duration-[var(--motion-duration-fast)] text-left disabled:opacity-50 min-w-0"
                >
                  {isLinking
                    ? <Loader2 size={40} className="shrink-0 animate-spin text-[var(--color-text-muted)] p-[10px]" />
                    : <GameIcon iconUrl={r.icon_url} name={r.name} size={40} />
                  }
                  <span className="flex-1 text-sm text-[var(--color-text-primary)] truncate">{r.name}</span>
                  {isLinking && (
                    <span className="text-xs text-[var(--color-text-muted)] shrink-0">Linking…</span>
                  )}
                </button>
                {rommUrl && (
                  <a
                    href={rommUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="shrink-0 px-[var(--spacing-3)] py-[var(--spacing-3)] text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors duration-[var(--motion-duration-fast)]"
                    aria-label={`Open ${r.name} in RomM`}
                  >
                    <ExternalLink size={14} />
                  </a>
                )}
              </div>
            )
          })}
        </div>

        {map.isError && (
          <div className="px-[var(--spacing-4)] py-[var(--spacing-3)] border-t border-[var(--color-border-subtle)] bg-[var(--color-error-subtle)]">
            <p className="text-xs text-[var(--color-error)]">
              {map.error instanceof Error ? map.error.message : 'Failed to link — try again'}
            </p>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}

import { Check, Loader2, Pencil, X } from 'lucide-react'
import * as React from 'react'
import { Button } from './button'
import { Input } from './input'

interface InlineEditProps {
  value: string
  onSave: (newValue: string) => Promise<void>
  placeholder?: string
  className?: string
  renderValue?: (value: string) => React.ReactNode
  editLabel?: string
}

type Mode = 'view' | 'edit' | 'saving'

export function InlineEdit({ value, onSave, placeholder, className, renderValue, editLabel = 'Edit' }: InlineEditProps) {
  const [mode, setMode] = React.useState<Mode>('view')
  const [draft, setDraft] = React.useState(value)
  const [error, setError] = React.useState<string | null>(null)
  const inputRef = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => { setDraft(value) }, [value])

  const startEdit = () => {
    setDraft(value)
    setError(null)
    setMode('edit')
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  const cancel = () => {
    setDraft(value)
    setError(null)
    setMode('view')
  }

  const save = async () => {
    setMode('saving')
    setError(null)
    try {
      await onSave(draft.trim())
      setMode('view')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed')
      setMode('edit')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') void save()
    if (e.key === 'Escape') cancel()
  }

  if (mode === 'view') {
    return (
      <span className={`group inline-flex items-center gap-[var(--spacing-2)] ${className ?? ''}`}>
        {renderValue ? renderValue(draft) : <span>{draft || placeholder}</span>}
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={startEdit}
          className="opacity-40 hover:opacity-100 transition-opacity duration-[var(--motion-duration-fast)]"
          aria-label={editLabel}
        >
          <Pencil size={12} />
        </Button>
      </span>
    )
  }

  return (
    <span className={`inline-flex flex-col gap-[var(--spacing-1)] ${className ?? ''}`}>
      <span className="inline-flex items-center gap-[var(--spacing-1)]">
        <Input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={mode === 'saving'}
          error={!!error}
          className="h-7 text-sm"
        />
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => void save()}
          disabled={mode === 'saving'}
          aria-label="Save"
        >
          {mode === 'saving' ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={cancel}
          disabled={mode === 'saving'}
          aria-label="Cancel"
        >
          <X size={12} />
        </Button>
      </span>
      {error && (
        <span className="text-xs text-[var(--color-error)]">{error}</span>
      )}
    </span>
  )
}

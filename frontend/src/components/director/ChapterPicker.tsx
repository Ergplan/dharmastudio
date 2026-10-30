import { useState } from 'react'
import { ChevronDown, ChevronRight, BookOpen } from 'lucide-react'
import { cx, Spinner } from '@/components/ui'
import type { ID } from '@/api/types'
import { AGE_TONE, useDChapters } from './api'

/** Chapters grouped by Book, shown by MANUSCRIPT number (Book Two = 22–41), with the age each is painted in. */
export function ChapterPicker({ value, onChange }: { value: ID | null; onChange: (id: ID) => void }) {
  const { data, isLoading } = useDChapters()
  const [closed, setClosed] = useState<Record<number, boolean>>({})
  if (isLoading || !data) return <Spinner />
  return (
    <div className="flex flex-col min-h-0">
      {!data.has_book && (
        <div className="m-2 p-2 rounded border border-amber-500/30 bg-amber-500/10 text-2xs text-amber-200 leading-4">
          <BookOpen size={11} className="inline mr-1" />The manuscript has not been imported yet. Drop the book PDF in <a className="underline" href="#/project">Project → Manuscript</a> so chapters carry their manuscript numbers, text and settings.
        </div>
      )}
      {data.books.map(b => (
        <div key={b.volume_id} className="border-b border-ink-800">
          <button className="w-full flex items-center gap-1.5 px-2.5 py-2 text-left hover:bg-ink-850" onClick={() => setClosed(c => ({ ...c, [b.volume]: !c[b.volume] }))}>
            {closed[b.volume] ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
            <span className="text-xs font-semibold text-ink-100">{b.book}</span>
            <span className="text-2xs text-ink-400 truncate">{b.title}</span>
            {b.range && <span className="ml-auto font-mono text-2xs text-ink-500">{b.range[0]}–{b.range[1]}</span>}
          </button>
          {!closed[b.volume] && (
            <ul className="pb-1">
              {b.chapters.map(c => (
                <li key={c.id}>
                  <button onClick={() => onChange(c.id)} className={cx('w-full flex items-center gap-2 pl-6 pr-2 py-1 text-left text-2xs hover:bg-ink-850', value === c.id && 'bg-gold-500/10 text-gold-200')}
                    title={`${c.label} · studio chapter ${b.volume}.${c.studio_number} · ${c.age_name} (${c.age_source})`}>
                    <span className="font-mono w-6 text-right text-ink-400 shrink-0">{c.manuscript_number ?? '—'}</span>
                    <span className={cx('truncate flex-1', value === c.id ? 'text-gold-200' : 'text-ink-200')}>{c.title}</span>
                    {c.pages > 0 && <span className="font-mono text-ink-500 shrink-0" title={`${c.review} in review · ${c.approved} approved`}>{c.approved}/{c.pages}</span>}
                    <span className={cx('h-4 px-1 rounded-sm border text-[0.58rem] uppercase tracking-wide shrink-0', AGE_TONE[c.age])}>{c.age}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  )
}

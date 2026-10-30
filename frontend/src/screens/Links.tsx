import { useState } from 'react'
import { Copy, ExternalLink, Lock, Download, Pencil, Check, X, RefreshCw, Trash2, Plus } from 'lucide-react'
import { useLinks, useSaveLink, useLockLink, useCheckLink, useDeleteLink, useCreateLink, type LinkRow, type TargetType } from '@/api/motion'
import { cx, Empty, Spinner } from '@/components/ui'
import { useToasts } from '@/store/toasts'

const STATUS_CLS: Record<string, string> = {
  published: 'border-emerald-500/50 text-emerald-300 bg-emerald-500/10',
  draft: 'border-ink-500 text-ink-300 bg-ink-700/40',
  broken: 'border-red-500/50 text-red-300 bg-red-500/10',
}

/** LINKS — every printed short URL, what it resolves to, where it is printed. */
export default function LinksScreen() {
  const { data: links = [], isLoading } = useLinks()
  const [q, setQ] = useState('')
  const [adding, setAdding] = useState(false)
  const rows = links.filter(l => !q || `${l.code} ${l.title} ${l.resolved.destination}`.toLowerCase().includes(q.toLowerCase()))
  if (isLoading) return <Spinner />
  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="p-3 border-b border-ink-800 flex items-center gap-2">
        <input className="input w-64" placeholder="Filter codes, titles, destinations…" value={q} onChange={e => setQ(e.target.value)} />
        <span className="text-2xs text-ink-400">{links.length} links · {links.filter(l => l.print_locked).length} printed · {links.filter(l => l.status === 'broken').length} broken</span>
        <div className="flex-1" />
        <button className="btn" onClick={() => setAdding(a => !a)}><Plus size={12} />New link</button>
        <a className="btn" href="/api/links/export.csv" download><Download size={12} />CSV for the printer</a>
      </div>
      {adding && <NewLink onDone={() => setAdding(false)} />}
      <div className="flex-1 overflow-auto">
        {rows.length === 0 ? <Empty>No links yet — making a page a moment creates its link ({'{volume}-{page}'}).</Empty> : (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-ink-900 text-ink-400 text-left">
              <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:font-medium border-b border-ink-800">
                <th>Short URL</th><th>Status</th><th>Resolves to</th><th>Where printed</th><th>Notes</th><th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>{rows.map(l => <Row key={l.id} l={l} />)}</tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function Row({ l }: { l: LinkRow }) {
  const save = useSaveLink()
  const lock = useLockLink()
  const check = useCheckLink()
  const del = useDeleteLink()
  const push = useToasts(s => s.push)
  const [edit, setEdit] = useState(false)
  const [dest, setDest] = useState(l.destination_override ?? '')
  const [code, setCode] = useState(l.code)
  const copy = () => { navigator.clipboard.writeText(l.short_url); push({ kind: 'ok', title: 'Copied', message: l.short_url }) }
  return (
    <tr className="border-b border-ink-850 align-top [&>td]:px-3 [&>td]:py-2 hover:bg-ink-900/60" data-testid="link-row">
      <td>
        {edit && !l.print_locked
          ? <input className="input font-mono w-40" value={code} onChange={e => setCode(e.target.value.toLowerCase())} />
          : <div className="font-mono text-ink-100 flex items-center gap-1.5">/v/{l.code}{l.print_locked && <Lock size={11} className="text-amber-300" aria-label="printed: code locked" />}</div>}
        <div className="text-2xs text-ink-400 truncate max-w-[14rem]">{l.title || `${l.target_type} ${l.target_ref}`}</div>
      </td>
      <td>
        <span className={cx('chip', STATUS_CLS[l.status])}>{l.status}</span>
        {!l.enabled && <span className="chip ml-1 border-amber-500/50 text-amber-300">disabled</span>}
        {l.reasons.length > 0 && <div className="text-2xs text-ink-500 mt-0.5 max-w-[12rem]">{l.reasons.join('; ')}</div>}
      </td>
      <td className="max-w-[22rem]">
        <div className="text-ink-300">{l.resolved.label}</div>
        {edit
          ? <input className="input font-mono mt-1 w-full" placeholder="destination override (e.g. a YouTube URL) — empty = the watch page" value={dest} onChange={e => setDest(e.target.value)} />
          : <a className="font-mono text-2xs text-sky-300 break-all" href={l.resolved.destination} target="_blank" rel="noreferrer">{l.resolved.destination}</a>}
      </td>
      <td className="text-2xs text-ink-300">{l.where_printed.length ? l.where_printed.map(w => <div key={`${w.page_id}-${w.qr_id}`}>Book {w.volume} · p{w.page} <span className="text-ink-500">({w.w_mm} mm)</span></div>) : <span className="text-ink-500">—</span>}</td>
      <td className="text-2xs text-ink-400 max-w-[12rem]">{l.notes}</td>
      <td className="text-right whitespace-nowrap">
        <div className="inline-flex gap-1">
          <button className="btn btn-sm btn-icon" title="Copy short URL" onClick={copy}><Copy size={11} /></button>
          <a className="btn btn-sm btn-icon" title="Open" href={l.short_url} target="_blank" rel="noreferrer"><ExternalLink size={11} /></a>
          {edit ? <>
            <button className="btn btn-sm btn-icon btn-primary" title="Save" onClick={() => save.mutate({ id: l.id, destination_override: dest, ...(l.print_locked ? {} : { code }) }, { onSuccess: () => setEdit(false) })}><Check size={11} /></button>
            <button className="btn btn-sm btn-icon" title="Cancel" onClick={() => { setEdit(false); setDest(l.destination_override ?? ''); setCode(l.code) }}><X size={11} /></button>
          </> : <button className="btn btn-sm btn-icon" title={l.print_locked ? 'Edit destination (the code is printed and locked)' : 'Edit code / destination'} onClick={() => setEdit(true)}><Pencil size={11} /></button>}
          <button className={cx('btn btn-sm', !l.enabled && 'border-amber-500/50')} title={l.enabled ? 'Disable: scans show a friendly coming-soon page' : 'Enable'} onClick={() => save.mutate({ id: l.id, enabled: !l.enabled })}>{l.enabled ? 'Disable' : 'Enable'}</button>
          {!l.print_locked && <button className="btn btn-sm btn-icon" title="Lock (mark as printed): the code can never change again" onClick={() => { if (confirm(`Lock /v/${l.code}? Its code can never change or be deleted afterwards.`)) lock.mutate(l.id) }}><Lock size={11} /></button>}
          {(l.destination_override || l.target_type === 'url') && <button className="btn btn-sm btn-icon" title="Check the external URL (HEAD)" onClick={() => check.mutate(l.id)}><RefreshCw size={11} /></button>}
          {!l.print_locked && <button className="btn btn-sm btn-icon btn-ghost" title="Delete" onClick={() => { if (confirm(`Delete /v/${l.code}?`)) del.mutate(l.id) }}><Trash2 size={11} /></button>}
        </div>
      </td>
    </tr>
  )
}

function NewLink({ onDone }: { onDone: () => void }) {
  const create = useCreateLink()
  const [t, setT] = useState<TargetType>('url')
  const [ref, setRef] = useState('')
  const [code, setCode] = useState('')
  return (
    <div className="p-3 border-b border-ink-800 bg-ink-900 flex items-center gap-2 text-xs">
      <select className="select w-28" value={t} onChange={e => setT(e.target.value as TargetType)}>{(['url', 'page', 'chapter', 'moment'] as const).map(x => <option key={x} value={x}>{x}</option>)}</select>
      <input className="input flex-1 font-mono" placeholder={t === 'url' ? 'https://…' : `${t} id`} value={ref} onChange={e => setRef(e.target.value)} />
      <input className="input w-40 font-mono" placeholder="code (optional)" value={code} onChange={e => setCode(e.target.value.toLowerCase())} />
      <button className="btn btn-primary" onClick={() => create.mutate({ target_type: t, target_ref: ref, code: code || undefined } as Partial<LinkRow>, { onSuccess: onDone })}>Create</button>
    </div>
  )
}

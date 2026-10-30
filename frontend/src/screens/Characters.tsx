import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Lock, Unlock, Star, Check, Upload, Sparkles, Trash2, ShieldAlert, Plus } from 'lucide-react'
import { useCharacters, useSaveCharacter, useSaveRef, useApiMutation, qk, type JobResp } from '@/api/hooks'
import { api, mediaUrl } from '@/api/client'
import { PROVIDERS, type Character, type Provider } from '@/api/types'
import { cx, Field, JobProgress, Spinner, Empty } from '@/components/ui'
import { toast } from '@/store/toasts'

export default function CharactersScreen() {
  const { data: chars, isLoading } = useCharacters()
  const { id } = useParams()
  const nav = useNavigate()
  const selected = chars?.find(c => c.id === Number(id)) ?? null
  const unlocked = (chars ?? []).filter(c => !c.locked)
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const create = useApiMutation((name: string) => api.post<Character>('/api/characters', { name, form_key: name.toLowerCase().replace(/\s+/g, '-') }), [qk.characters], (c) => { setAdding(false); setNewName(''); nav(`/characters/${c.id}`) })
  if (isLoading) return <Spinner />
  return (
    <div className="h-full flex">
      <div className="w-[380px] shrink-0 border-r border-ink-800 flex flex-col min-h-0">
        {unlocked.length > 0 ? (
          <div className="m-3 mb-0 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200 flex gap-2"><ShieldAlert size={14} className="shrink-0 mt-0.5" /><div><b>Lock before generating:</b> {unlocked.map(c => c.name).join(', ')}. A page naming an unlocked character cannot generate.</div></div>
        ) : (
          <div className="m-3 mb-0 rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200 flex gap-2"><Check size={14} className="shrink-0 mt-0.5" />All characters are locked. Every generation carries its look paragraph and primary reference.</div>
        )}
        <div className="panel-h justify-between mt-2"><span>Characters <span className="text-ink-500 font-normal">{chars?.length ?? 0}</span></span><button className="btn btn-sm" onClick={() => setAdding(a => !a)}><Plus size={11} /> Add</button></div>
        {adding && <form className="px-3 py-2 flex gap-1.5 border-b border-ink-800" onSubmit={(e) => { e.preventDefault(); if (newName.trim()) create.mutate(newName.trim()) }}><input autoFocus className="input" placeholder="Name (e.g. Agastya)" value={newName} onChange={(e) => setNewName(e.target.value)} /><button className="btn btn-primary btn-sm" type="submit">Create</button></form>}
        <div className="flex-1 overflow-auto p-3 grid grid-cols-2 gap-2 content-start">
          {chars?.length === 0 && <div className="col-span-2"><Empty>No characters yet. Propose the cast from the Project screen or add one.</Empty></div>}
          {chars?.map(c => {
            const prim = c.refs.find(r => r.id === c.primary_ref_id)
            return (
              <button key={c.id} onClick={() => nav(`/characters/${c.id}`)} className={cx('card text-left overflow-hidden hover:border-ink-500 transition-colors', selected?.id === c.id && 'border-gold-500/70 ring-1 ring-gold-500/30')}>
                <div className="aspect-square bg-ink-900 relative">
                  {prim ? <img src={mediaUrl(prim.path)} className="w-full h-full object-cover" alt="" /> : <div className="w-full h-full grid place-items-center text-ink-600 text-2xs">no primary ref</div>}
                  <span className={cx('absolute top-1.5 right-1.5 chip', c.locked ? 'border-emerald-500/60 bg-emerald-500/20 text-emerald-200' : 'border-amber-500/60 bg-amber-500/20 text-amber-200')}>{c.locked ? <Lock size={9} /> : <Unlock size={9} />}{c.locked ? 'locked' : 'unlocked'}</span>
                </div>
                <div className="px-2.5 py-2"><div className="text-sm text-ink-100 font-book">{c.name}</div><div className="font-mono text-2xs text-ink-500">{c.form_key} · {c.refs.length} ref{c.refs.length === 1 ? '' : 's'}</div></div>
              </button>
            )
          })}
        </div>
      </div>
      <div className="flex-1 min-w-0 overflow-auto">
        {selected ? <CharacterDetail key={selected.id} c={selected} /> : <div className="h-full grid place-items-center text-ink-500 text-xs">Select a character to edit its look, references and lock.</div>}
      </div>
    </div>
  )
}

function CharacterDetail({ c }: { c: Character }) {
  const save = useSaveCharacter()
  const saveRef = useSaveRef()
  const [look, setLook] = useState(c.look)
  useEffect(() => setLook(c.look), [c.look])
  const [provider, setProvider] = useState<Provider>('sunburst')
  const [n, setN] = useState(4)
  const [jobId, setJobId] = useState<number | null>(null)
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const gen = useApiMutation(() => api.post<JobResp>(`/api/characters/${c.id}/refs/generate`, { provider, n }), [qk.characters], (r) => setJobId(r.job_id))
  const upload = useApiMutation(async (files: File[]) => { const fd = new FormData(); files.forEach(f => fd.append('files', f)); return api.post(`/api/characters/${c.id}/refs/upload`, fd) }, [qk.characters], () => toast('ok', 'References uploaded'))
  const delRef = useApiMutation((rid: number) => api.del(`/api/characters/${c.id}/refs/${rid}`), [qk.characters])
  const prim = c.refs.find(r => r.id === c.primary_ref_id)
  const canLock = !!prim && prim.approved
  return (
    <div className="p-5 max-w-5xl flex flex-col gap-5">
      <div className="flex items-start gap-4">
        <div>
          <h1 className="text-xl font-book text-ink-100">{c.name}</h1>
          <div className="font-mono text-2xs text-ink-500">form <span className="text-ink-300">{c.form_key}</span> · id {c.id}</div>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <div className="text-right text-2xs text-ink-500 max-w-[220px]">{c.locked ? 'Locked: the look paragraph and the primary reference ride on every generation.' : canLock ? 'Ready to lock.' : 'Lock needs an approved primary reference.'}</div>
          <button
            className={cx('relative h-8 w-[108px] rounded-full border transition-colors flex items-center px-1', c.locked ? 'bg-emerald-500/25 border-emerald-400/60' : 'bg-ink-800 border-ink-600', !c.locked && !canLock && 'opacity-50 cursor-not-allowed')}
            disabled={!c.locked && !canLock}
            title={c.locked ? 'Unlock' : canLock ? 'Lock' : 'Approve a primary reference first'}
            onClick={() => save.mutate({ id: c.id, locked: !c.locked })}
          >
            <span className={cx('absolute top-0.5 h-6 w-6 rounded-full grid place-items-center transition-all', c.locked ? 'left-[78px] bg-emerald-300 text-ink-950' : 'left-0.5 bg-ink-500 text-ink-100')}>{c.locked ? <Lock size={12} /> : <Unlock size={12} />}</span>
            <span className={cx('text-2xs font-medium uppercase tracking-wide w-full', c.locked ? 'text-left pl-2 text-emerald-200' : 'text-right pr-2 text-ink-300')}>{c.locked ? 'Locked' : 'Unlocked'}</span>
          </button>
        </div>
      </div>

      <Field label="Look paragraph" hint={<span className="normal-case tracking-normal text-ink-500">saved on blur · carried verbatim into every prompt of this character</span>}>
        <textarea className="textarea min-h-[120px] text-[13px]" value={look} onChange={(e) => setLook(e.target.value)} onBlur={() => look !== c.look && save.mutate({ id: c.id, look })} />
      </Field>

      <section>
        <div className="flex items-center gap-2 mb-2">
          <span className="label">Reference images <span className="text-ink-500">{c.refs.length}/6</span></span>
          <div className="flex-1" />
          <select className="select w-44" value={provider} onChange={(e) => setProvider(e.target.value as Provider)}>{PROVIDERS.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}</select>
          <select className="select w-16" value={n} onChange={(e) => setN(Number(e.target.value))}>{[2, 3, 4, 5, 6].map(k => <option key={k} value={k}>{k}</option>)}</select>
          <button className="btn btn-primary" disabled={gen.isPending || !look.trim()} onClick={() => gen.mutate(undefined)}><Sparkles size={12} /> Generate references</button>
          <button className="btn" onClick={() => fileRef.current?.click()}><Upload size={12} /> Upload</button>
          <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => { const fs = Array.from(e.target.files ?? []); if (fs.length) upload.mutate(fs); e.target.value = '' }} />
        </div>
        {jobId && <div className="mb-3"><JobProgress jobId={jobId} /></div>}
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); const fs = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/')); if (fs.length) upload.mutate(fs) }}
          className={cx('grid grid-cols-4 gap-3 rounded-md border border-dashed p-3 min-h-[180px] transition-colors', drag ? 'border-gold-400 bg-gold-500/5' : 'border-ink-700')}
        >
          {c.refs.length === 0 && <div className="col-span-4 self-center text-center text-xs text-ink-500">No references yet — generate from the look paragraph or drop images here.</div>}
          {c.refs.map(r => (
            <div key={r.id} className={cx('card overflow-hidden group relative', r.is_primary && 'border-gold-500/70 ring-1 ring-gold-500/30')}>
              <img src={mediaUrl(r.path)} alt="" className="aspect-square w-full object-cover bg-ink-900" />
              <div className="absolute top-1.5 left-1.5 flex gap-1">
                {r.is_primary && <span className="chip chip-on"><Star size={9} className="fill-gold-300" /> primary</span>}
                {r.approved && <span className="chip border-emerald-500/60 bg-emerald-500/20 text-emerald-200"><Check size={9} /> approved</span>}
              </div>
              <div className="px-2 py-1.5 flex items-center gap-1 text-2xs text-ink-400">
                <span className="font-mono truncate flex-1" title={r.prompt}>{r.provider}</span>
                <button className={cx('btn btn-sm btn-icon', r.approved && 'text-emerald-300 border-emerald-500/50')} title={r.approved ? 'Un-approve' : 'Approve'} onClick={() => saveRef.mutate({ cid: c.id, rid: r.id, approved: !r.approved })}><Check size={11} /></button>
                <button className={cx('btn btn-sm btn-icon', r.is_primary && 'text-gold-300 border-gold-500/50')} title={r.is_primary ? 'Primary' : 'Make primary'} onClick={() => !r.is_primary && saveRef.mutate({ cid: c.id, rid: r.id, is_primary: true })}><Star size={11} className={r.is_primary ? 'fill-gold-300' : ''} /></button>
                <button className="btn btn-sm btn-icon btn-danger opacity-0 group-hover:opacity-100" title="Delete" onClick={() => confirm('Delete this reference?') && delRef.mutate(r.id)}><Trash2 size={11} /></button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

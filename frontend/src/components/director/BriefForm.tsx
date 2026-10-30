import { useState } from 'react'
import { Clapperboard, Plus, X, ShieldAlert, CheckCircle2, AlertTriangle, Lock, Unlock, Layers, UserPlus } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { cx, Field } from '@/components/ui'
import { useCharacters, useApiMutation, type JobResp } from '@/api/hooks'
import { api } from '@/api/client'
import { toast } from '@/store/toasts'
import { AGE_TONE, SWATCH, type Age, type Brief, type BriefCheck, type DChapterDetail, type Estimate, type RunSettings } from './api'

const AGES: Age[] = ['treta', 'dwapara', 'kali']

export function PaletteChips({ palette, className }: { palette: string[]; className?: string }) {
  return (
    <div className={cx('flex flex-wrap gap-1', className)}>
      {palette.map(p => <span key={p} className="chip gap-1" title={p}><span className="w-2.5 h-2.5 rounded-sm border border-black/30" style={{ background: SWATCH[p] ?? '#777' }} />{p}</span>)}
    </div>
  )
}

export function BriefForm({ ch, brief, setBrief, check, est, settings, setSettings, onDirect, onDirectN, busy }: {
  ch: DChapterDetail; brief: Brief; setBrief: (b: Brief) => void; check: BriefCheck | null; est: Estimate | null
  settings: RunSettings; setSettings: (s: RunSettings) => void; onDirect: () => void; onDirectN: (n: number) => void; busy: boolean
}) {
  const { data: chars = [] } = useCharacters()
  const nav = useNavigate()
  const [charInput, setCharInput] = useState('')
  const [nextN, setNextN] = useState(3)
  const set = (p: Partial<Brief>) => setBrief({ ...brief, ...p })
  const addChar = (k: string) => { const key = k.trim(); if (key && !brief.characters.includes(key)) set({ characters: [...brief.characters, key] }); setCharInput('') }
  const lineCheck = (i: number) => check?.lines[i]
  const charCheck = (k: string) => check?.characters.find(c => c.key === k)
  const refJob = useApiMutation((cid: number) => api.post<JobResp>(`/api/characters/${cid}/refs/generate`, { provider: settings.provider ?? 'sunburst', n: 2 }), [['jobs'], ['characters']],
    () => toast('ok', 'Reference sheet started', 'Approve one as primary on Characters, then lock — the Director paints only locked characters.'))
  const age = check?.age ?? ch.age
  return (
    <div className="flex flex-col gap-3 p-3 text-xs">
      <div>
        <div className="label mb-1">Manuscript chapter</div>
        <div className="font-book text-sm text-ink-100">{ch.label}</div>
        <div className="text-2xs text-ink-500">Book {ch.volume}{ch.manuscript.book_title ? ` · ${ch.manuscript.book_title}` : ''} · studio chapter {ch.volume}.{ch.studio_number}</div>
      </div>

      <Field label="Page">
        <select className="select" value={brief.page_id ?? `new:${brief.page_number ?? ch.next_page_number}`} onChange={(e) => {
          const v = e.target.value
          if (v.startsWith('new:')) set({ page_id: null, page_number: Number(v.slice(4)) })
          else { const pg = ch.pages_list.find(p => p.id === Number(v)); set({ page_id: Number(v), page_number: pg?.number ?? null }) }
        }}>
          <option value={`new:${ch.next_page_number}`}>new page {ch.next_page_number}</option>
          {ch.pages_list.map(p => <option key={p.id} value={p.id} disabled={p.status === 'approved'}>page {p.number} · {p.status}{p.panels ? ` · ${p.panels} panels` : ''}</option>)}
        </select>
      </Field>

      <Field label="Exact action" hint={<span className="normal-case tracking-normal text-ink-500">what happens in this illustration</span>}>
        <textarea className="textarea min-h-[3.5rem]" value={brief.action} placeholder="e.g. Kalki steps out of the tent while Ravana speaks from every screen" onChange={(e) => set({ action: e.target.value })} />
      </Field>

      <div className="flex flex-col gap-1">
        <span className="label">Characters present <span className="normal-case tracking-normal text-ink-500">(studio form keys; locked only)</span></span>
        <div className="flex flex-wrap gap-1">
          {brief.characters.map(k => {
            const c = charCheck(k)
            const tone = !c ? 'border-ink-600' : !c.exists ? 'border-red-500/60 text-red-200' : c.locked ? 'border-emerald-500/50 text-emerald-200' : 'border-amber-500/60 text-amber-200'
            return (
              <span key={k} className={cx('chip', tone)} title={c && !c.exists ? `unknown — ${c.suggestions.join(', ')}` : c?.locked ? 'locked' : 'not locked'}>
                {c?.exists === false ? <AlertTriangle size={9} /> : c?.locked ? <Lock size={9} /> : <Unlock size={9} />}{k}
                <button className="ml-0.5 hover:text-white" onClick={() => set({ characters: brief.characters.filter(x => x !== k) })}><X size={9} /></button>
              </span>
            )
          })}
        </div>
        <div className="flex gap-1">
          <input className="input" list="dir-char-keys" value={charInput} placeholder="add a form key…" onChange={(e) => setCharInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') addChar(charInput) }} />
          <datalist id="dir-char-keys">{chars.map(c => <option key={c.form_key} value={c.form_key}>{c.name}{c.locked ? ' (locked)' : ''}</option>)}</datalist>
          <button className="btn btn-sm h-7" onClick={() => addChar(charInput)}><Plus size={11} /></button>
        </div>
        {ch.cast.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-0.5">
            <span className="text-2xs text-ink-500 mr-1">in this chapter:</span>
            {ch.cast.flatMap(c => c.keys.slice(0, 3).map(k => (
              <button key={k.key} className={cx('chip hover:border-ink-400', brief.characters.includes(k.key) && 'opacity-40')} onClick={() => addChar(k.key)} title={`${c.name} · ${c.mentions} mentions`}>
                {k.locked ? <Lock size={8} className="text-emerald-300" /> : <Unlock size={8} className="text-ink-500" />}{k.key}
              </button>
            )))}
          </div>
        )}
        {check?.characters.filter(c => !c.exists && c.suggestions.length).map(c => (
          <div key={c.key} className="text-2xs text-red-300">Unknown “{c.key}” — did you mean {c.suggestions.map((s, i) => <button key={s} className="underline mx-0.5" onClick={() => set({ characters: brief.characters.map(x => x === c.key ? s : x) })}>{s}{i < c.suggestions.length - 1 ? ',' : ''}</button>)}?</div>
        ))}
        {check && check.needs_reference.length > 0 && (
          <div className="mt-1 p-2 rounded border border-amber-500/40 bg-amber-500/10 text-2xs text-amber-100 flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5"><ShieldAlert size={12} />Lock gate: the Director paints only locked characters. Create the canonical reference sheet first:</div>
            {check.needs_reference.map(n => (
              <div key={n.key} className="flex items-center gap-2">
                <span className="font-mono">{n.key}</span>
                <button className="btn btn-sm" disabled={refJob.isPending} onClick={() => refJob.mutate(n.character_id)}><UserPlus size={10} /> Generate reference sheet</button>
                <button className="btn btn-sm btn-ghost" onClick={() => nav(`/characters/${n.character_id}`)}>Open in Characters →</button>
              </div>
            ))}
          </div>
        )}
      </div>

      <Field label="Setting" hint={<button className="normal-case tracking-normal text-ink-500 underline" onClick={() => set({ setting: ch.setting })}>prefill from the chapter</button>}>
        <textarea className="textarea min-h-[4rem] text-2xs" value={brief.setting} onChange={(e) => set({ setting: e.target.value })} />
      </Field>

      <div className="flex flex-col gap-1.5">
        <span className="label">Dialogue / narration to reproduce <span className="normal-case tracking-normal text-ink-500">— select text in the manuscript to insert it</span></span>
        {brief.lines.length === 0 && <div className="text-2xs text-ink-500 italic">None: the plan will choose verbatim callouts from the chapter.</div>}
        {brief.lines.map((ln, i) => {
          const c = lineCheck(i)
          return (
            <div key={i} className={cx('rounded border p-1.5 flex flex-col gap-1', c ? (c.verbatim ? 'border-emerald-600/40' : c.adapted_approved ? 'border-amber-500/40' : 'border-red-500/50') : 'border-ink-700')}>
              <div className="flex items-center gap-1.5">
                <select className="select h-6 w-auto text-2xs" value={ln.kind} onChange={(e) => set({ lines: brief.lines.map((x, j) => j === i ? { ...x, kind: e.target.value as 'dialogue' | 'narration' } : x) })}><option value="dialogue">dialogue</option><option value="narration">narration</option></select>
                {ln.kind === 'dialogue' && <input className="input h-6 w-28 text-2xs" placeholder="speaker" value={ln.speaker ?? ''} onChange={(e) => set({ lines: brief.lines.map((x, j) => j === i ? { ...x, speaker: e.target.value || null } : x) })} />}
                {c && <span className={cx('chip', c.verbatim ? 'border-emerald-500/50 text-emerald-300' : c.adapted_approved ? 'border-amber-500/50 text-amber-300' : 'border-red-500/60 text-red-300')}>{c.verbatim ? <CheckCircle2 size={9} /> : <AlertTriangle size={9} />}{c.status}</span>}
                <button className="btn btn-ghost btn-sm btn-icon ml-auto" onClick={() => set({ lines: brief.lines.filter((_, j) => j !== i) })}><X size={11} /></button>
              </div>
              <textarea className="textarea text-2xs min-h-[2.25rem]" value={ln.text} onChange={(e) => set({ lines: brief.lines.map((x, j) => j === i ? { ...x, text: e.target.value } : x) })} />
              {c && !c.verbatim && (
                <div className="flex flex-col gap-0.5 text-2xs">
                  {c.closest && <span className="text-ink-400">closest in the manuscript: <span className="font-book italic">{c.closest}</span></span>}
                  <label className="flex items-center gap-1.5 text-amber-200"><input type="checkbox" checked={ln.adapted_approved} onChange={(e) => set({ lines: brief.lines.map((x, j) => j === i ? { ...x, adapted_approved: e.target.checked } : x) })} />adapted, approved by the author</label>
                </div>
              )}
            </div>
          )
        })}
        <button className="btn btn-sm self-start" onClick={() => set({ lines: [...brief.lines, { text: '', kind: 'dialogue', speaker: null, adapted_approved: false }] })}><Plus size={10} /> Line</button>
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="label">Age &amp; palette <span className="normal-case tracking-normal text-ink-500">(auto from the chapter: {ch.age_name}, by {ch.age_source})</span></span>
        <div className="flex gap-1">
          <button className={cx('chip', !brief.age && 'chip-on')} onClick={() => set({ age: null })}>auto</button>
          {AGES.map(a => <button key={a} className={cx('chip uppercase', brief.age === a ? AGE_TONE[a] : '')} onClick={() => set({ age: a })}>{a}</button>)}
          <label className="ml-auto flex items-center gap-1 text-2xs text-ink-300" title="Master prompt §6: occasional full-page illustrations for major revelations, divine encounters and dramatic transitions"><input type="checkbox" checked={brief.full_page} onChange={(e) => set({ full_page: e.target.checked })} /><Layers size={10} /> full-page plate</label>
        </div>
        <PaletteChips palette={check?.palette ?? ch.palette} />
        <div className={cx('text-2xs', AGE_TONE[age], 'border rounded px-1.5 py-0.5 self-start')}>{check?.age_name ?? ch.age_name}</div>
      </div>

      {check && (check.errors.length > 0 || check.warnings.length > 0) && (
        <div className="flex flex-col gap-1">
          {check.errors.map((e, i) => <div key={i} className="text-2xs text-red-300 flex gap-1.5"><ShieldAlert size={11} className="shrink-0 mt-0.5" />{e}</div>)}
          {check.warnings.map((e, i) => <div key={i} className="text-2xs text-amber-300 flex gap-1.5"><AlertTriangle size={11} className="shrink-0 mt-0.5" />{e}</div>)}
        </div>
      )}

      <div className="rounded border border-ink-700 p-2 flex flex-col gap-2 bg-ink-900">
        <div className="grid grid-cols-3 gap-2">
          <Field label="Candidates"><select className="select h-6 text-2xs" value={settings.candidates} onChange={(e) => setSettings({ ...settings, candidates: Number(e.target.value) })}>{[1, 2, 3, 4].map(n => <option key={n}>{n}</option>)}</select></Field>
          <Field label="Auto-revisions"><select className="select h-6 text-2xs" value={settings.retries} onChange={(e) => setSettings({ ...settings, retries: Number(e.target.value) })}>{[0, 1, 2].map(n => <option key={n}>{n}</option>)}</select></Field>
          <Field label="Budget cap $"><input className="input h-6 text-2xs" type="number" min={0} step={0.5} value={settings.budget_usd} onChange={(e) => setSettings({ ...settings, budget_usd: Number(e.target.value) })} /></Field>
        </div>
        <div className="flex items-center gap-2 text-2xs text-ink-300">
          <select className="select h-6 w-auto text-2xs" value={settings.provider ?? ''} onChange={(e) => setSettings({ ...settings, provider: e.target.value || null })}><option value="">image: project default</option><option value="sunburst">Sunburst</option><option value="gemini-nb21">Gemini NB 2.1</option><option value="gemini-pro">Gemini Pro</option></select>
          <label className="flex items-center gap-1"><input type="checkbox" checked={settings.run_critic} onChange={(e) => setSettings({ ...settings, run_critic: e.target.checked })} />critic</label>
        </div>
        {est && (
          <div className="text-2xs text-ink-400 font-mono leading-4">
            ≈ {est.panels} panels × {settings.candidates} = {est.images} images · <span className="text-ink-200">${est.usd.toFixed(2)}</span> (worst ${est.usd_worst.toFixed(2)} with revisions) · {est.provider}{est.dry_run ? ' · DRY RUN (no key)' : ''}
            <br />planner {est.planner_model}{est.planner_live ? '' : ' (no key → deterministic)'} · critic {est.critic_model}{est.critic_live ? '' : ' (no key → flagged for you)'}
          </div>
        )}
        <button className="btn btn-primary h-10 text-sm justify-center" disabled={busy || !check?.can_paint} onClick={onDirect} title={check?.can_paint ? 'Plan, paint, critique and assemble this page' : 'Fix the brief first'}>
          <Clapperboard size={15} /> Direct this page
        </button>
        <div className="flex items-center gap-1.5">
          <button className="btn btn-sm flex-1 justify-center" disabled={busy || ch.no_manuscript} onClick={() => onDirectN(nextN)} title="Each page gets a brief from the next manuscript passage; pages with unlocked characters are skipped">Direct next {nextN} pages</button>
          <select className="select h-6 w-14 text-2xs" value={nextN} onChange={(e) => setNextN(Number(e.target.value))}>{[1, 2, 3, 5, 8, 10].map(n => <option key={n}>{n}</option>)}</select>
        </div>
      </div>
    </div>
  )
}

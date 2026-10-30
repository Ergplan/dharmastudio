import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Clapperboard, BookOpenText, ShieldCheck, Activity, Image as ImageIcon } from 'lucide-react'
import { cx, Spinner } from '@/components/ui'
import type { ID } from '@/api/types'
import { useEditor } from '@/store/editor'
import { checkBrief, estimateRun, useDChapter, useDChapters, useDirect, useDirectChapter, useRun, useRuns, AGE_TONE, type Brief, type BriefCheck, type Estimate, type RunSettings } from '@/components/director/api'
import { ChapterPicker } from '@/components/director/ChapterPicker'
import { ManuscriptPane } from '@/components/director/ManuscriptPane'
import { BriefForm, PaletteChips } from '@/components/director/BriefForm'
import { RunTimeline, RunBadge } from '@/components/director/RunTimeline'
import { GuardrailPanel } from '@/components/director/GuardrailPanel'
import { Covers } from '@/components/director/Covers'

const EMPTY = (chapter_id: ID): Brief => ({ chapter_id, action: '', characters: [], setting: '', lines: [], page_id: null, page_number: null, age: null, full_page: false })

export default function DirectorScreen() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'covers' ? 'covers' : 'direct'
  const ed = useEditor()
  const { data: chapters } = useDChapters()
  const [chapterId, setChapterId] = useState<ID | null>(Number(params.get('chapter')) || null)
  useEffect(() => {
    if (chapterId || !chapters) return
    const all = chapters.books.flatMap(b => b.chapters)
    setChapterId((ed.chapterId && all.find(c => c.id === ed.chapterId)?.id) || all[0]?.id || null)
  }, [chapters]) // eslint-disable-line react-hooks/exhaustive-deps
  const { data: ch } = useDChapter(chapterId)
  const [brief, setBrief] = useState<Brief | null>(null)
  const [check, setCheck] = useState<BriefCheck | null>(null)
  const [est, setEst] = useState<Estimate | null>(null)
  const [settings, setSettings] = useState<RunSettings>({ candidates: 2, retries: 2, budget_usd: 3, run_critic: true, provider: null })
  const [centre, setCentre] = useState<'manuscript' | 'run' | 'guardrails'>(params.get('run') ? 'run' : 'manuscript')
  const [runId, setRunId] = useState<ID | null>(Number(params.get('run')) || null)
  const { data: runs = [] } = useRuns(chapterId)
  const { data: activeRun } = useRun(runId)
  const reuse = () => { if (activeRun && activeRun.chapter_id === chapterId && brief) setBrief({ ...brief, ...activeRun.brief, page_id: null, page_number: ch?.next_page_number ?? null } as Brief) }

  // a fresh brief per chapter; ?page= pre-selects the page (from the Pages screen's "Direct with Art Director")
  useEffect(() => {
    if (!ch) return
    const restoring = !!(activeRun && activeRun.chapter_id === ch.id && activeRun.brief?.action && Number(params.get('run')) === activeRun.id && !brief?.action)
    if (brief?.chapter_id === ch.id && !restoring) return
    const pid = Number(params.get('page')) || null
    const pg = ch.pages_list.find(p => p.id === pid)
    const fromRun = restoring ? activeRun!.brief : null  // ?run= restores the brief that made it
    setBrief({ ...EMPTY(ch.id), setting: ch.setting.slice(0, 1200), ...(fromRun ?? {}), page_id: pg?.id ?? null, page_number: pg?.number ?? ch.next_page_number } as Brief)
    setCheck(null)
  }, [ch, activeRun?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // live deterministic check + estimate (debounced)
  useEffect(() => {
    if (!brief) return
    const t = setTimeout(() => {
      checkBrief(brief).then(setCheck).catch(() => setCheck(null))
      estimateRun(brief, settings).then(setEst).catch(() => setEst(null))
    }, 350)
    return () => clearTimeout(t)
  }, [brief, settings])

  const started = (r: { run: { id: ID } }) => { setRunId(r.run.id); setCentre('run') }
  const direct = useDirect(started)
  const directN = useDirectChapter(started)
  const highlights = useMemo(() => (brief?.lines ?? []).map(l => l.text), [brief])

  const setTab = (t: 'direct' | 'covers') => { const p = new URLSearchParams(params); p.set('tab', t); setParams(p, { replace: true }) }
  const pickChapter = (id: ID) => { setChapterId(id); setBrief(null); setRunId(null); setCentre('manuscript'); const p = new URLSearchParams(params); p.set('chapter', String(id)); p.delete('page'); p.delete('run'); setParams(p, { replace: true }) }

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="h-9 shrink-0 border-b border-ink-800 bg-ink-900 flex items-center gap-1 px-2">
        <Clapperboard size={13} className="text-gold-300 mr-1" />
        <span className="text-xs font-medium text-ink-100 mr-3">Art Director</span>
        {(['direct', 'covers'] as const).map(t => <button key={t} className={cx('h-7 px-3 rounded text-xs', tab === t ? 'bg-gold-500/15 text-gold-300' : 'text-ink-400 hover:bg-ink-800')} onClick={() => setTab(t)}>{t === 'direct' ? 'Direct pages' : 'Covers & posters'}</button>)}
        <span className="ml-auto text-2xs text-ink-500">the master prompt stays constant · each illustration adds one short scene brief</span>
      </div>
      {tab === 'covers' ? <div className="flex-1 min-h-0"><Covers /></div> : (
        <div className="flex-1 min-h-0 flex">
          <div className="w-[16.5rem] shrink-0 border-r border-ink-800 overflow-auto bg-ink-900/40">
            <ChapterPicker value={chapterId} onChange={pickChapter} />
          </div>
          <div className="flex-1 min-w-0 flex flex-col min-h-0">
            {ch && (
              <div className="shrink-0 border-b border-ink-800 bg-ink-900 px-3 py-1.5 flex items-center gap-2 flex-wrap">
                <span className="font-book text-sm text-ink-100">{ch.label}</span>
                <span className={cx('chip uppercase', AGE_TONE[check?.age ?? ch.age])}>{check?.age_name ?? ch.age_name}</span>
                <PaletteChips palette={check?.palette ?? ch.palette} />
                <div className="ml-auto flex rounded border border-ink-600 overflow-hidden">
                  {([['manuscript', BookOpenText, 'Manuscript'], ['run', Activity, 'Run timeline'], ['guardrails', ShieldCheck, 'Guardrails']] as const).map(([k, Icon, label]) => (
                    <button key={k} className={cx('h-6 px-2.5 text-2xs flex items-center gap-1', centre === k ? 'bg-gold-500/20 text-gold-300' : 'text-ink-400 hover:bg-ink-800')} onClick={() => setCentre(k)}><Icon size={11} />{label}</button>
                  ))}
                </div>
              </div>
            )}
            <div className="flex-1 min-h-0">
              {!ch ? <Spinner /> : centre === 'manuscript' ? (
                <ManuscriptPane ch={ch} highlight={highlights} onAdd={(text, kind) => {
                  if (!brief) return
                  if (kind === 'action') setBrief({ ...brief, action: brief.action ? `${brief.action} ${text}` : text })
                  else setBrief({ ...brief, lines: [...brief.lines, { text, kind, speaker: null, adapted_approved: false }] })
                }} />
              ) : centre === 'run' ? (
                <div className="h-full flex min-h-0">
                  <div className="flex-1 min-w-0"><RunTimeline runId={runId} onPickRun={setRunId} onReuse={reuse} /></div>
                  <div className="w-[13rem] shrink-0 border-l border-ink-800 overflow-auto p-2 flex flex-col gap-1">
                    <div className="label mb-1">Runs in this chapter</div>
                    {runs.length === 0 && <div className="text-2xs text-ink-500 italic">none yet</div>}
                    {runs.map(r => (
                      <button key={r.id} onClick={() => setRunId(r.id)} className={cx('text-left rounded border px-1.5 py-1 text-2xs', r.id === runId ? 'border-gold-500/60 bg-gold-500/10' : 'border-ink-700 hover:border-ink-500')}>
                        <div className="flex items-center gap-1"><span className="font-mono text-ink-300">#{r.id}</span><RunBadge status={r.status} /></div>
                        <div className="text-ink-400">{r.kind === 'chapter' ? 'batch' : `page ${r.page_number ?? '—'}`} · {r.panels ?? 0} panels · ${r.cost_usd.toFixed(2)}</div>
                      </button>
                    ))}
                  </div>
                </div>
              ) : <GuardrailPanel age={check?.age ?? ch.age} />}
            </div>
          </div>
          <div className="w-[25rem] shrink-0 border-l border-ink-800 overflow-auto bg-ink-900/40">
            {ch && brief ? (
              <BriefForm ch={ch} brief={brief} setBrief={setBrief} check={check} est={est} settings={settings} setSettings={setSettings} busy={direct.isPending || directN.isPending}
                onDirect={() => direct.mutate({ brief, settings })} onDirectN={(n) => directN.mutate({ chapter_id: ch.id, next: n, settings })} />
            ) : <Spinner />}
            {ch && <div className="px-3 pb-3 text-2xs text-ink-500 flex items-center gap-1"><ImageIcon size={10} />Pages land in <b className="text-ink-300 mx-0.5">review</b>; the author approves on Pages.</div>}
          </div>
        </div>
      )}
    </div>
  )
}

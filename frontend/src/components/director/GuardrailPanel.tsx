import { useState } from 'react'
import { ShieldCheck, Ban, ListChecks, ScrollText } from 'lucide-react'
import { cx, Spinner } from '@/components/ui'
import { AGE_TONE, useGuardrails, type Age } from './api'
import { PaletteChips } from './BriefForm'

/** The author's master prompt as the Director enforces it: the full text (verbatim), the ages, the negative list,
 *  the 10-point final quality test, and which checks are deterministic vs judged by the critic model. */
export function GuardrailPanel({ age }: { age?: Age }) {
  const { data: g, isLoading } = useGuardrails()
  const [raw, setRaw] = useState(false)
  if (isLoading || !g) return <Spinner />
  return (
    <div className="h-full overflow-auto p-4 flex flex-col gap-4 text-xs">
      <div className="flex items-center gap-2">
        <ShieldCheck size={15} className="text-gold-300" />
        <span className="text-sm text-ink-100 font-medium">Master art direction — the constant style authority</span>
        <span className="font-mono text-2xs text-ink-500" title="sha256 of engine/director/master_prompt.md">{g.sha256.slice(0, 12)}</span>
        <button className={cx('btn btn-sm ml-auto', raw && 'chip-on')} onClick={() => setRaw(!raw)}><ScrollText size={11} /> {raw ? 'Structured' : 'Full master prompt'}</button>
      </div>
      {raw ? (
        <pre className="whitespace-pre-wrap font-book text-[0.8rem] leading-6 text-ink-200 bg-ink-900 border border-ink-800 rounded p-4">{g.raw}</pre>
      ) : (
        <>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-2">
            {(Object.keys(g.ages) as Age[]).map(k => {
              const a = g.ages[k]
              return (
                <div key={k} className={cx('card p-2.5 flex flex-col gap-1.5', age === k && 'ring-1 ring-gold-500/50')}>
                  <div className="flex items-center gap-1.5"><span className={cx('chip uppercase', AGE_TONE[k])}>{a.name}</span><span className="text-2xs text-ink-400">{a.subtitle}</span></div>
                  <PaletteChips palette={a.palette} />
                  <div className="text-2xs text-ink-300 leading-4">{a.visual_language}</div>
                  {Object.entries(a.directives).map(([who, ss]) => <div key={who} className="text-2xs leading-4"><span className="text-gold-300">{who}</span> <span className="text-ink-300">{ss.join(' ')}</span></div>)}
                </div>
              )
            })}
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-2">
            <div className="card p-2.5">
              <div className="flex items-center gap-1.5 mb-1.5"><Ban size={12} className="text-red-300" /><span className="label">Strict negative directions (in every prompt, verbatim)</span></div>
              <ul className="text-2xs leading-5 text-ink-200 columns-1 2xl:columns-2">{g.negatives.map(n => <li key={n}>{n}</li>)}</ul>
            </div>
            <div className="card p-2.5">
              <div className="flex items-center gap-1.5 mb-1.5"><ListChecks size={12} className="text-emerald-300" /><span className="label">Final quality test (the critic scores each 0–10; pass ≥ 6 each, mean ≥ 7)</span></div>
              <ol className="text-2xs leading-5 text-ink-200 list-decimal pl-4">{g.quality_test.map(q => <li key={q}>{q}</li>)}</ol>
            </div>
          </div>
          <div className="card p-2.5 text-2xs leading-5">
            <div className="label mb-1">How each guardrail is enforced</div>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
              <div><div className="text-emerald-300 mb-0.5">Deterministic (code, every run)</div><ul className="list-disc pl-4 text-ink-300">
                <li>callouts verbatim from the manuscript (or ticked “adapted, approved”)</li><li>character keys exist; every character locked (the studio's lock gate)</li>
                <li>{g.page_architecture.min_panels}–{g.page_architecture.max_panels} panels: 1 dominant, 2–3 narrative, 1 detail (or one full-page plate)</li>
                <li>era palette chosen from the chapter; no text asked of the image model; the full negative list in every prompt (lint)</li>
                <li>image size and aspect; near-duplicate panels (perceptual hash); in-image text by OCR when installed</li>
                <li>budget cap, stop, at most 2 auto-revisions; never auto-approved; failures flagged</li>
                <li>cover title “{g.typography.series_title}” and “{g.typography.author_credit}” typeset by the studio, exact spelling</li></ul></div>
              <div><div className="text-amber-300 mb-0.5">Judged by the critic model (vision)</div><ul className="list-disc pl-4 text-ink-300">
                <li>the ten points of the final quality test</li><li>consistency against the attached locked reference sheets</li>
                <li>anatomy, hands, head count (Ravana: golden head = {g.ravana_heads.golden}, crimson head = {g.ravana_heads.crimson})</li>
                <li>period detail and palette for the age; no superhero / anime / plastic look; proportion rule</li></ul></div>
            </div>
          </div>
          <div className="card p-2.5 text-2xs leading-5 text-ink-300">
            <div className="label mb-1">Page architecture</div>
            {g.page_architecture.hierarchy.map(h => <div key={h}>• {h}</div>)}
            <div className="mt-1">Full / double page for: {g.page_architecture.full_page_for.join(', ')}.</div>
          </div>
        </>
      )}
    </div>
  )
}

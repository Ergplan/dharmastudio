import { useEffect, useRef, useState } from 'react'
import { Wand2, Paintbrush, Type, Upload, Download, CheckCircle2 } from 'lucide-react'
import { cx, Field, JobProgress, Spinner } from '@/components/ui'
import { mediaUrl } from '@/api/client'
import type { ID } from '@/api/types'
import { useComposeCover, useCovers, usePaintCover, useSaveCover, useTypesetCover, useUploadCoverRef } from './api'

/** Covers & posters per volume (master prompt §7–§9): the poster art is painted with NO text; the studio typesets
 *  THE CYCLE OF DHARMA, the volume line, RACHIT AGARWAL and the publisher line in Cinzel — exact spelling. */
export function Covers() {
  const { data: covers, isLoading } = useCovers()
  const [vid, setVid] = useState<ID | null>(null)
  useEffect(() => { if (covers?.length && !vid) setVid((covers.find(c => c.volume === 2) ?? covers[0]).volume_id) }, [covers, vid])
  const c = covers?.find(x => x.volume_id === vid)
  const compose = useComposeCover()
  const [job, setJob] = useState<number | null>(null)
  const paint = usePaintCover((r) => setJob(r.job_id))
  const save = useSaveCover()
  const typeset = useTypesetCover()
  const upload = useUploadCoverRef()
  const file = useRef<HTMLInputElement>(null)
  const [pub, setPub] = useState('')
  useEffect(() => { if (c) setPub(c.publisher) }, [c?.volume_id]) // eslint-disable-line react-hooks/exhaustive-deps
  if (isLoading || !covers) return <Spinner />
  if (!c) return null
  const exp = c.exports
  return (
    <div className="h-full flex min-h-0">
      <style>{`@font-face{font-family:'Cinzel Decorative';src:url(/api/fonts/CinzelDecorative-Bold.ttf);font-weight:700}@font-face{font-family:'Cinzel';src:url(/api/fonts/Cinzelwght.ttf);font-weight:400 900}`}</style>
      <div className="w-[26rem] shrink-0 border-r border-ink-800 overflow-auto p-3 flex flex-col gap-3 text-xs">
        <div className="flex gap-1">{covers.map(v => <button key={v.volume_id} className={cx('chip', v.volume_id === vid && 'chip-on')} onClick={() => setVid(v.volume_id)}>Volume {v.volume}</button>)}</div>
        <div>
          <div className="font-book text-base text-ink-100">{c.text.volume_line}</div>
          <div className="text-2xs text-ink-500">{c.range ? `manuscript chapters ${c.range[0]}–${c.range[1]}` : 'chapters from the studio'} · vertical 2:3 poster (§9)</div>
        </div>
        <div className="card p-2 flex flex-col gap-1.5">
          <div className="label">Typeset by the studio (exact strings)</div>
          {(['title', 'volume_line', 'author'] as const).map(k => <div key={k} className="flex items-center gap-1.5"><CheckCircle2 size={11} className="text-emerald-400" /><span className="font-mono text-2xs text-ink-500 w-16">{k.replace('_', ' ')}</span><span className="text-ink-100 tracking-wide" style={{ fontFamily: 'Cinzel, serif' }}>{c.text[k]}</span></div>)}
          <Field label="Publisher line"><div className="flex gap-1"><input className="input" value={pub} onChange={(e) => setPub(e.target.value)} /><button className="btn btn-sm h-7" disabled={pub === c.publisher} onClick={() => save.mutate({ vid: c.volume_id, publisher: pub })}>Save</button></div></Field>
        </div>
        <div className="card p-2 flex flex-col gap-1.5">
          <div className="flex items-center gap-2"><span className="label">Poster art prompt</span>{c.prompt_source && <span className="chip">{c.prompt_source}</span>}
            <button className="btn btn-sm ml-auto" disabled={compose.isPending} onClick={() => compose.mutate(c.volume_id)}><Wand2 size={11} /> {c.prompt ? 'Recompose' : 'Compose from the chapters'}</button></div>
          {c.facts.principal && <div className="text-2xs text-ink-400">principal: <span className="text-ink-200">{c.facts.principal.join(', ')}</span></div>}
          {c.prompt ? <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-2xs leading-4 text-ink-300 bg-ink-950 border border-ink-800 rounded p-2">{c.prompt}</pre> : <div className="text-2xs text-ink-500 italic">Compose to build the prompt from the volume's actual chapters (Volume Two: 22–41).</div>}
          <button className="btn btn-primary justify-center" disabled={paint.isPending} onClick={() => paint.mutate({ vid: c.volume_id, n: 2 })}><Paintbrush size={12} /> Paint 2 art candidates (no text)</button>
          {job && <JobProgress jobId={job} compact />}
        </div>
        <div className="card p-2 flex flex-col gap-1.5">
          <div className="label">Current cover (author's upload — reference only, kept on this Mac)</div>
          <input ref={file} type="file" accept="image/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate({ vid: c.volume_id, file: f }); e.target.value = '' }} />
          <div className="flex items-center gap-2">
            {c.reference_url ? <img src={mediaUrl(c.reference_url)} className="h-24 rounded border border-ink-700" alt="current cover" /> : <span className="text-2xs text-ink-500 italic">none uploaded</span>}
            <button className="btn btn-sm" onClick={() => file.current?.click()}><Upload size={11} /> Upload</button>
          </div>
        </div>
        <div className="card p-2 flex flex-col gap-1.5">
          <div className="label">Typeset &amp; export (PNG + PDF at 300 ppi)</div>
          <div className="flex gap-1">
            <button className="btn btn-sm" disabled={!c.art_path || typeset.isPending} onClick={() => typeset.mutate({ vid: c.volume_id, art: 'painted' })}><Type size={11} /> on painted art</button>
            <button className="btn btn-sm" disabled={!c.reference_path || typeset.isPending} onClick={() => typeset.mutate({ vid: c.volume_id, art: 'reference' })}><Type size={11} /> on uploaded cover</button>
            <button className="btn btn-sm" disabled={typeset.isPending} onClick={() => typeset.mutate({ vid: c.volume_id, art: 'none' })}>title only</button>
          </div>
          {exp.png && (
            <div className="text-2xs text-ink-400 flex flex-wrap gap-2 items-center">
              {exp.size_px?.join('×')} px · {exp.mm?.join('×')} mm · {exp.ppi} ppi · art: {exp.art}
              <a className="btn btn-sm" href={mediaUrl(exp.png)} download><Download size={10} /> PNG</a>
              <a className="btn btn-sm" href={mediaUrl(exp.pdf)} download><Download size={10} /> PDF</a>
            </div>
          )}
        </div>
      </div>
      <div className="flex-1 min-w-0 overflow-auto p-5 flex gap-5 bg-[radial-gradient(ellipse_at_center,#1a1a1f_0%,#0d0d0f_70%)]">
        <div className="flex flex-col gap-2 items-center">
          <div className="label">{exp.png ? 'Typeset cover' : 'Typeset preview'}</div>
          {exp.png
            ? <img src={`${mediaUrl(exp.png)}?t=${encodeURIComponent(exp.at ?? '')}`} className="h-[34rem] aspect-[2/3] rounded shadow-2xl shadow-black border border-ink-700" alt="cover" />
            : <div className="h-[34rem] aspect-[2/3] rounded border border-ink-700 bg-[#2c2019] overflow-hidden relative">
                {c.art_url && <img src={mediaUrl(c.art_url)} className="absolute inset-0 w-full h-full object-cover" alt="" />}
                <div className="absolute inset-0" dangerouslySetInnerHTML={{ __html: c.svg.replace(/width="\d+" height="\d+"/, 'width="100%" height="100%"').replace(/<image[^>]*\/>/, '') }} />
              </div>}
          {exp.thumb && <div className="flex items-center gap-2 text-2xs text-ink-500"><img src={`${mediaUrl(exp.thumb)}?t=${encodeURIComponent(exp.at ?? '')}`} className="h-20 rounded border border-ink-700" alt="thumbnail" />thumbnail test (§9)</div>}
        </div>
        <div className="flex flex-col gap-2 min-w-[12rem]">
          <div className="label">Painted art (no text)</div>
          <div className="grid grid-cols-2 gap-2">
            {c.art_candidates.map(a => (
              <button key={a.path} onClick={() => save.mutate({ vid: c.volume_id, art_path: a.path })} className={cx('rounded border overflow-hidden', a.path === c.art_path ? 'border-gold-500 ring-1 ring-gold-500/40' : 'border-ink-700')}>
                <img src={mediaUrl(a.url)} className="w-36 aspect-[2/3] object-cover" alt="" />
                <div className="text-2xs text-ink-400 px-1 py-0.5 text-left">{a.provider}{a.dry_run ? ' · dry run' : ''}</div>
              </button>
            ))}
            {!c.art_candidates.length && <div className="text-2xs text-ink-500 italic col-span-2">Paint candidates to choose the poster art.</div>}
          </div>
        </div>
      </div>
    </div>
  )
}

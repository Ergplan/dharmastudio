import type { Metadata } from 'next'
import { notFound, redirect } from 'next/navigation'
import Top from '@/components/Top'
import Player from '@/components/Player'
import { BOOK_HI, CODE_RE, findLink, findMoment, getManifest, SITE_URL } from '@/lib/manifest'
import MomentCards from '@/components/MomentCards'

export const revalidate = 300
export const dynamicParams = true

type Props = { params: Promise<{ code: string }> }

export async function generateStaticParams() {
  const m = await getManifest()
  return m.links.map(l => ({ code: l.code }))
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { code } = await params
  const m = await getManifest()
  const mo = findMoment(m, code)
  if (!mo) return { title: 'Coming soon', robots: { index: false } }
  const from = `From The Cycle of Dharma — Book ${mo.volume}, page ${mo.page}`
  const url = `${SITE_URL}/v/${code}`
  return {
    title: mo.title_en,
    description: mo.caption_en.slice(0, 200) || from,
    alternates: { canonical: url },
    openGraph: {
      type: 'video.other', url, title: `${mo.title_en} — The Cycle of Dharma`, description: from,
      images: [{ url: mo.media.poster, width: 1920, height: 1080 }],
      videos: [{ url: mo.media.en_16x9, type: 'video/mp4', width: 1920, height: 1080 }],
    },
    twitter: { card: 'summary_large_image', title: mo.title_en, description: from, images: [mo.media.poster] },
  }
}

function ComingSoon({ code }: { code: string }) {
  return (
    <div className="wrap">
      <Top />
      <div className="soon">
        <div className="kicker">cycleofdharma.world/v/{code}</div>
        <h1 className="only-en">This moment is still being painted</h1>
        <h1 className="only-hi hi" lang="hi">यह क्षण अभी रचा जा रहा है</h1>
        <p className="only-en">The film for this page is coming soon. Keep the book close — the code you scanned will light up here.</p>
        <p className="only-hi hi" lang="hi">इस पृष्ठ की फ़िल्म जल्द आ रही है। आपने जो कोड स्कैन किया है, वह यहीं जीवंत होगा।</p>
      </div>
    </div>
  )
}

export default async function Watch({ params }: Props) {
  const { code } = await params
  if (!CODE_RE.test(code)) notFound()
  const m = await getManifest()
  const link = findLink(m, code)
  if (!link) notFound()
  if (link.kind === 'redirect' && link.destination) redirect(link.destination) // the proxy normally answers first, with a 302
  if (link.kind === 'chapter') {
    const ch = link.chapter
    return (
      <div className="wrap">
        <Top />
        <div className="kicker">Book {ch?.volume} · Chapter {ch?.number}</div>
        <h1>{ch?.title}</h1>
        <MomentCards moments={m.moments.filter(x => link.moments?.includes(x.code))} />
      </div>
    )
  }
  const mo = link.kind === 'moment' ? findMoment(m, link.moment || code) : undefined
  if (!mo) return <ComingSoon code={code} />
  return (
    <div className="wrap">
      <Top />
      <div className="kicker">Book {mo.volume} · {mo.chapter_title}</div>
      <h1 className="only-en">{mo.title_en}</h1>
      <h1 className="only-hi hi" lang="hi">{mo.title_hi || mo.title_en}</h1>
      <Player media={mo.media} />
      <p className="from only-en">From The Cycle of Dharma — Book {mo.volume}, page {mo.page}</p>
      <p className="from only-hi hi" lang="hi">{BOOK_HI} से — पुस्तक {mo.volume}, पृष्ठ {mo.page}</p>
      <p className="caption only-en">{mo.caption_en}</p>
      <p className="caption only-hi hi" lang="hi">{mo.caption_hi || mo.caption_en}</p>
      {mo.verse && (
        <section className="verse" aria-label="Verse">
          <div className="lines" lang="sa">{mo.verse.lines.join('\n')}</div>
          <div className="meaning">{mo.verse.meaning}</div>
          {mo.verse.source && <div className="src">{mo.verse.source}</div>}
        </section>
      )}
      <div className="rule" />
      <footer><a href="/">cycleofdharma.world</a> · {m.book.author}</footer>
    </div>
  )
}

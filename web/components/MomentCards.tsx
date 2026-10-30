import Link from 'next/link'
import type { MomentEntry } from '@/lib/manifest'

export default function MomentCards({ moments }: { moments: MomentEntry[] }) {
  return (
    <div className="grid">
      {moments.map(m => (
        <Link key={m.code} className="card" href={`/v/${m.code}`}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img loading="lazy" src={m.media.poster} alt="" />
          <div>
            <b className="only-en">{m.title_en}</b>
            <b className="only-hi hi" lang="hi">{m.title_hi || m.title_en}</b>
            <span>Book {m.volume} · page {m.page}</span>
          </div>
        </Link>
      ))}
    </div>
  )
}

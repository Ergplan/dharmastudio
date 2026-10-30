import LangSwitch from '@/components/LangSwitch'
import MomentCards from '@/components/MomentCards'
import { getManifest } from '@/lib/manifest'

export const revalidate = 300

export default async function Home() {
  const m = await getManifest()
  const b = m.book
  return (
    <div className="wrap">
      <header className="top"><span className="kicker">cycleofdharma.world</span><LangSwitch /></header>
      <h1>{b.title}</h1>
      <div className="hi" lang="hi" style={{ fontSize: 24 }}>{b.title_hi}</div>
      <p className="from">A graphic novel in three books by {b.author}. Scan a page — watch its moment.</p>
      <div className="books">
        {b.books.map(x => (
          <div className="book" key={x.number}>
            <div className="kicker">Book {x.number}</div>
            <b>{x.title}</b>
            <div className="hi" lang="hi">{x.title_hi}</div>
            <small>{x.moments ?? 0} moment{x.moments === 1 ? '' : 's'}</small>
          </div>
        ))}
      </div>
      <div className="rule" />
      <h2 className="kicker">Moments</h2>
      {m.moments.length ? <MomentCards moments={m.moments} /> : <p>The first moments are being painted.</p>}
      <footer>© {b.author}</footer>
    </div>
  )
}

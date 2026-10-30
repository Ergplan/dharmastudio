import Link from 'next/link'
import LangSwitch from './LangSwitch'

export default function Top() {
  return (
    <header className="top">
      <Link className="home" href="/">The Cycle of Dharma</Link>
      <LangSwitch />
    </header>
  )
}

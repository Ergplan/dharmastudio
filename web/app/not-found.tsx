import Top from '@/components/Top'

export default function NotFound() {
  return (
    <div className="wrap">
      <Top />
      <div className="soon">
        <h1>This page is not in the book</h1>
        <p>Check the code under the QR, or <a href="/">start at the beginning</a>.</p>
      </div>
    </div>
  )
}

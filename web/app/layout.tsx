import type { Metadata, Viewport } from 'next'
import { Analytics } from '@vercel/analytics/next'
import { imFell, spectral, tiro } from './fonts'
import { SITE_URL } from '@/lib/manifest'
import './globals.css'

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: 'The Cycle of Dharma', template: '%s — The Cycle of Dharma' },
  description: 'The Cycle of Dharma — a bilingual graphic novel by Rachit Agarwal. Scan a page, watch the moment.',
}
export const viewport: Viewport = { width: 'device-width', initialScale: 1, themeColor: '#efe4c9' }

// No trackers. Vercel Web Analytics only when NEXT_PUBLIC_VERCEL_ANALYTICS=1 (off by default).
const analytics = process.env.NEXT_PUBLIC_VERCEL_ANALYTICS === '1'

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${imFell.variable} ${tiro.variable} ${spectral.variable}`} suppressHydrationWarning>
      <body>
        {children}
        {analytics && <Analytics />}
      </body>
    </html>
  )
}

import localFont from 'next/font/local'

// The engine's faces (OFL, licences alongside), self-hosted by next/font.
export const imFell = localFont({
  src: [{ path: './fonts/IMFeENrm28P.ttf', style: 'normal', weight: '400' }, { path: './fonts/IMFeENit28P.ttf', style: 'italic', weight: '400' }],
  variable: '--font-fell', display: 'swap',
})
export const tiro = localFont({ src: './fonts/TiroDevanagariHindi-Regular.ttf', variable: '--font-tiro', display: 'swap', preload: false })
export const spectral = localFont({ src: './fonts/Spectral-Regular.ttf', variable: '--font-spectral', display: 'swap' })

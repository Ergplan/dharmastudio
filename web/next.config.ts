import type { NextConfig } from 'next'

const config: NextConfig = {
  poweredByHeader: false,
  trailingSlash: false,
  async headers() {
    return [
      { source: '/textures/:path*', headers: [{ key: 'Cache-Control', value: 'public, max-age=31536000, immutable' }] },
    ]
  },
}

export default config

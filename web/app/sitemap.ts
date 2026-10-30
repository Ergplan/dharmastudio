import type { MetadataRoute } from 'next'
import { getManifest, SITE_URL } from '@/lib/manifest'

export const revalidate = 300

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const m = await getManifest()
  return [
    { url: `${SITE_URL}/`, changeFrequency: 'weekly', priority: 1 },
    ...m.moments.map(x => ({ url: `${SITE_URL}/v/${x.code}`, lastModified: x.published_at ?? undefined, changeFrequency: 'monthly' as const, priority: 0.8 })),
  ]
}

# cycleofdharma.world

The public site for *The Cycle of Dharma*: a Next.js (App Router) app that Vercel builds from this folder on every push
to `main`. The **code** lives here in git; the **content** does not — Dharma Studio publishes `manifest.json` and the
media (MP4s, posters) to **Vercel Blob**, then calls this site's `POST /api/revalidate`, so a new moment is live within
seconds without a deploy.

```
app/page.tsx              landing: title, the three books, the published moments
app/v/[code]/page.tsx     watch page (EN | हिंदी, 16:9 / 9:16, poster, caption, the page's Sanskrit verse + meaning,
                          Open Graph / Twitter tags), the coming-soon page for disabled or unpublished links, chapter pages
proxy.ts                  short links: /{code} → /v/{code}; destination overrides (e.g. YouTube) → 302
app/api/revalidate        POST {secret} (or header x-revalidate-secret) → expires the cached manifest
app/robots.ts, sitemap.ts, not-found.tsx
lib/manifest.ts           reads MANIFEST_URL (ISR: 5 min, tag "manifest")
lib/manifest.schema.json  the manifest contract, shared with the studio (a studio test validates every manifest)
app/fonts/                IM Fell English, Tiro Devanagari Hindi, Spectral (OFL — licences alongside), via next/font
public/textures/          the parchment
```

Printed QR codes only ever point at `https://cycleofdharma.world/v/{code}`. Those URLs are permanent: once a page
carrying a QR is exported for print, the studio locks that code for ever (its destination can still change).

## One-time setup (the author)

1. **Vercel → Add New → Project → import `Ergplan/dharmastudio`.**
   *Root Directory:* `web` · *Framework Preset:* Next.js · leave the build settings at their defaults.
2. **Vercel → Storage → Create → Blob.** Connect it to the project (any environment), open the store and copy its
   **read-write token** into the studio: *Motion → Site → Set keys…* → `BLOB_READ_WRITE_TOKEN`. (The site itself does
   not need this token — it only reads public URLs.)
3. In the studio, *Motion → Site → Generate revalidate secret*. It is shown once: copy it.
4. In the studio, publish once (*Publish* on a moment, or *Motion → Site → Publish*). The panel then shows the
   **manifest URL** (`https://<store>.public.blob.vercel-storage.com/manifest.json`).
5. **Vercel → Project → Settings → Environment Variables** (Production, and Preview if you like):
   - `MANIFEST_URL` = the manifest URL from step 4
   - `REVALIDATE_SECRET` = the secret from step 3
   - optional: `SITE_URL` (defaults to `https://cycleofdharma.world`), `NEXT_PUBLIC_VERCEL_ANALYTICS=1` to turn on
     Vercel Web Analytics (off by default; there are no other trackers)

   Then *Deployments → Redeploy* once so the variables take effect.
6. **Vercel → Project → Settings → Domains → Add `cycleofdharma.world`** (and `www.cycleofdharma.world`, redirecting to
   the apex). Set the DNS records Vercel shows at your registrar and wait for the certificate.

After that: publishing from the studio uploads only changed media (by SHA-1) plus `manifest.json`, then pings
`/api/revalidate`. Pages refresh within seconds (worst case: Blob's 60 s edge cache on `manifest.json`).

Media can later move off Blob (R2, S3, …) without touching any link: set *External media base URL* in the studio; the
pathnames stay `moments/{code}/en-16x9.mp4` etc.

## Local

```bash
cd web && npm ci
MANIFEST_URL=http://127.0.0.1:8787/site-preview/manifest.json npm run dev   # after "Preview site locally" in the studio
npm run build && npm start
```

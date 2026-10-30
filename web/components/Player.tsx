'use client'

import { useEffect, useRef, useState } from 'react'
import type { Media } from '@/lib/manifest'
import { useLang } from './LangSwitch'

/** HTML5 video: EN | हिंदी from the switch, 16:9 on wide screens and 9:16 on narrow ones; keeps the time on switch. */
export default function Player({ media }: { media: Media }) {
  const [lang] = useLang()
  const [portrait, setPortrait] = useState(false)
  const ref = useRef<HTMLVideoElement>(null)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 640px)')
    const f = () => setPortrait(mq.matches)
    f()
    mq.addEventListener('change', f)
    return () => mq.removeEventListener('change', f)
  }, [])
  const src = media[`${lang}_${portrait ? '9x16' : '16x9'}` as keyof Media] || media.en_16x9
  const poster = portrait && media.poster_9x16 ? media.poster_9x16 : media.poster
  useEffect(() => {
    const v = ref.current
    if (!v || v.getAttribute('src') === src) return
    const t = v.currentTime
    const playing = !v.paused
    v.src = src
    if (t) v.addEventListener('loadedmetadata', () => { v.currentTime = t }, { once: true })
    if (playing) void v.play()
  }, [src])
  return (
    <div className="player">
      <video ref={ref} controls playsInline preload="metadata" poster={poster} src={media.en_16x9} />
    </div>
  )
}

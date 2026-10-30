import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import { Rail, Header, Toasts } from './components/Shell'
import { UpdateBanner } from './components/Updater'
import ProjectScreen from './screens/Project'
import CharactersScreen from './screens/Characters'
import CanvasScreen from './screens/Canvas'
import TypographyScreen from './screens/Typography'
import ScriptScreen from './screens/Script'
import PagesScreen from './screens/Pages'
import DirectorScreen from './screens/Director'
import SilhouettesScreen from './screens/Silhouettes'
import ExportScreen from './screens/Export'
import MotionScreen from './screens/Motion'

export default function App() {
  const nav = useNavigate()
  // Global navigation shortcuts: Alt+1..9 and Alt+0 switch screens (plain digits are reserved for panel selection on Pages).
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey) return
      const i = e.key === '0' ? 9 : Number(e.key) - 1  // Alt+0 is the tenth screen
      const routes = ['/project', '/characters', '/canvas', '/typography', '/script', '/pages', '/director', '/silhouettes', '/export', '/motion']
      if (i >= 0 && i < routes.length) { e.preventDefault(); nav(routes[i]) }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [nav])
  return (
    <div className="h-full flex bg-ink-950">
      <Rail />
      <div className="flex-1 min-w-0 flex flex-col">
        <UpdateBanner />
        <Header />
        <main className="flex-1 min-h-0 overflow-hidden">
          <Routes>
            <Route path="/" element={<Navigate to="/project" replace />} />
            <Route path="/project" element={<ProjectScreen />} />
            <Route path="/characters" element={<CharactersScreen />} />
            <Route path="/characters/:id" element={<CharactersScreen />} />
            <Route path="/canvas" element={<CanvasScreen />} />
            <Route path="/typography" element={<TypographyScreen />} />
            <Route path="/script" element={<ScriptScreen />} />
            <Route path="/pages" element={<PagesScreen />} />
            <Route path="/director" element={<DirectorScreen />} />
            <Route path="/silhouettes" element={<SilhouettesScreen />} />
            <Route path="/export" element={<ExportScreen />} />
            <Route path="/motion" element={<MotionScreen />} />
            <Route path="*" element={<Navigate to="/project" replace />} />
          </Routes>
        </main>
      </div>
      <Toasts />
    </div>
  )
}

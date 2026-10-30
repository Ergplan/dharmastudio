import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import { Rail, Header, Toasts } from './components/Shell'
import ProjectScreen from './screens/Project'
import CharactersScreen from './screens/Characters'
import CanvasScreen from './screens/Canvas'
import ScriptScreen from './screens/Script'
import PagesScreen from './screens/Pages'
import SilhouettesScreen from './screens/Silhouettes'
import ExportScreen from './screens/Export'

export default function App() {
  const nav = useNavigate()
  // Global navigation shortcuts: Alt+1..7 switch screens (plain digits are reserved for panel selection on Pages).
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey) return
      const i = Number(e.key) - 1
      const routes = ['/project', '/characters', '/canvas', '/script', '/pages', '/silhouettes', '/export']
      if (i >= 0 && i < routes.length) { e.preventDefault(); nav(routes[i]) }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [nav])
  return (
    <div className="h-full flex bg-ink-950">
      <Rail />
      <div className="flex-1 min-w-0 flex flex-col">
        <Header />
        <main className="flex-1 min-h-0 overflow-hidden">
          <Routes>
            <Route path="/" element={<Navigate to="/project" replace />} />
            <Route path="/project" element={<ProjectScreen />} />
            <Route path="/characters" element={<CharactersScreen />} />
            <Route path="/characters/:id" element={<CharactersScreen />} />
            <Route path="/canvas" element={<CanvasScreen />} />
            <Route path="/script" element={<ScriptScreen />} />
            <Route path="/pages" element={<PagesScreen />} />
            <Route path="/silhouettes" element={<SilhouettesScreen />} />
            <Route path="/export" element={<ExportScreen />} />
            <Route path="*" element={<Navigate to="/project" replace />} />
          </Routes>
        </main>
      </div>
      <Toasts />
    </div>
  )
}

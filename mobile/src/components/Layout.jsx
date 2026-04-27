import { Outlet } from 'react-router-dom'
import BottomNav from './BottomNav'

export default function Layout() {
  return (
    <div className="flex flex-col min-h-dvh" style={{ background: 'var(--color-bg)' }}>
      <main className="flex-1 overflow-y-auto" style={{ paddingTop: '56px', paddingBottom: '72px' }}>
        <Outlet />
      </main>
      <BottomNav />
    </div>
  )
}

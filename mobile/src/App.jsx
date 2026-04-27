import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store/useAuthStore'
import { useEffect } from 'react'
import { api } from '@/services/api'

import Layout from '@/components/Layout'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import Signals from '@/pages/Signals'
import Screener from '@/pages/Screener'
import CopyTrading from '@/pages/CopyTrading'
import Analytics from '@/pages/Analytics'
import Heatmap from '@/pages/Heatmap'
import Backtest from '@/pages/Backtest'
import Macro from '@/pages/Macro'
import More from '@/pages/More'
import Profile from '@/pages/Profile'
import Charts from '@/pages/Charts'
import PreSignals from '@/pages/PreSignals'
import MarketAnalytics from '@/pages/MarketAnalytics'
import Referral from '@/pages/Referral'
import Pricing from '@/pages/Pricing'
import Support from '@/pages/Support'
import Lab from '@/pages/Lab'
import Account from '@/pages/Account'

function AuthGuard({ children }) {
  const { user, isLoading } = useAuthStore()
  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-dvh" style={{ background: 'var(--color-bg)' }}>
        <div className="flex flex-col items-center gap-4">
          <span className="font-display text-2xl font-bold text-gold">ANUNNAKI</span>
          <div className="w-8 h-8 rounded-full border-2 border-gold border-t-transparent animate-spin" />
        </div>
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  const { setUser, setLoading } = useAuthStore()

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) { setLoading(false); return }
    api.get('/api/auth/me')
      .then(r => { setUser(r.data.user); setLoading(false) })
      .catch(() => { localStorage.removeItem('token'); setLoading(false) })
  }, [])

  return (
    <BrowserRouter basename="/mobile">
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<AuthGuard><Layout /></AuthGuard>}>
          <Route index element={<Dashboard />} />
          <Route path="signals" element={<Signals />} />
          <Route path="screener" element={<Screener />} />
          <Route path="copy-trading" element={<CopyTrading />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="heatmap" element={<Heatmap />} />
          <Route path="backtest" element={<Backtest />} />
          <Route path="macro" element={<Macro />} />
          <Route path="charts" element={<Charts />} />
          <Route path="presignals" element={<PreSignals />} />
          <Route path="market-analytics" element={<MarketAnalytics />} />
          <Route path="referral" element={<Referral />} />
          <Route path="pricing" element={<Pricing />} />
          <Route path="support" element={<Support />} />
          <Route path="lab" element={<Lab />} />
          <Route path="account" element={<Account />} />
          <Route path="more" element={<More />} />
          <Route path="profile" element={<Profile />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

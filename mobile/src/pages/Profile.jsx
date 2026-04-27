import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { tierColor, tierLabel } from '@/utils/helpers'
import { User, Shield, Key } from 'lucide-react'

export default function Profile() {
  const { user } = useAuthStore()

  const { data: ctConfig, isLoading } = useQuery({
    queryKey: ['ct-config'],
    queryFn: () => api.get('/api/copy-trading/config').then(r => r.data),
  })

  return (
    <>
      <TopBar title="Profile" />
      
      <div className="px-4 pt-4 pb-20">
        
        {/* User Info */}
        <div className="card p-5 mb-4 text-center">
          <div style={{
            width: 80, height: 80, borderRadius: '50%', margin: '0 auto 16px',
            background: 'rgba(228,195,117,0.1)', border: '2px solid rgba(228,195,117,0.3)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 32, fontWeight: 800, color: 'var(--color-gold)'
          }}>
            {(user?.username?.[0] ?? 'A').toUpperCase()}
          </div>
          
          <h2 style={{ fontSize: 22, fontWeight: 800, marginBottom: 4 }}>{user?.username}</h2>
          <div style={{ fontSize: 14, color: 'var(--color-dim)', marginBottom: 12 }}>{user?.email}</div>
          
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 12px', borderRadius: 20,
            background: 'rgba(255,255,255,0.05)', color: tierColor(user?.tier), fontSize: 13, fontWeight: 700
          }}>
            {user?.is_admin && <Shield size={14} />}
            {user?.is_admin ? 'Administrator' : `${tierLabel(user?.tier)} Plan`}
          </div>
        </div>

        {/* Subscription Info */}
        <div className="card p-4 mb-4">
          <h3 style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase', marginBottom: 12 }}>Subscription</h3>
          
          <div className="flex justify-between items-center py-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
            <span style={{ fontSize: 14 }}>Status</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-green)' }}>Active</span>
          </div>
          
          <div className="flex justify-between items-center py-2">
            <span style={{ fontSize: 14 }}>Expires</span>
            <span style={{ fontSize: 14, fontWeight: 700 }}>
              {user?.tier_expires ? new Date(user.tier_expires * 1000).toLocaleDateString() : 'Never'}
            </span>
          </div>
        </div>

        {/* API Link Info */}
        <div className="card p-4 mb-4">
          <h3 style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase', marginBottom: 12 }}>Copy Trading Link</h3>
          
          {isLoading ? (
            <PageSpinner />
          ) : (
            <>
              <div className="flex justify-between items-center py-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
                <span style={{ fontSize: 14 }}>API Key</span>
                <span style={{ fontSize: 14, fontWeight: 700, color: ctConfig?.api_key ? 'var(--color-green)' : 'var(--color-red)' }}>
                  {ctConfig?.api_key ? 'Linked' : 'Not Linked'}
                </span>
              </div>
              
              <div className="flex justify-between items-center py-2">
                <span style={{ fontSize: 14 }}>Account Size</span>
                <span style={{ fontSize: 14, fontWeight: 700 }} className="font-mono">
                  {ctConfig?.total_margin_balance ? `$${ctConfig.total_margin_balance.toFixed(2)}` : '—'}
                </span>
              </div>
            </>
          )}
        </div>

      </div>
    </>
  )
}

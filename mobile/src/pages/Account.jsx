import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { LogOut, Laptop, Smartphone, Key, Shield, AlertTriangle } from 'lucide-react'

function DeviceRow({ d, onRevoke, isCurrent }) {
  const isMobile = d.user_agent?.toLowerCase().includes('mobile')
  
  return (
    <div className="flex items-center gap-3 py-3" style={{ borderBottom: '1px solid var(--color-border)' }}>
      <div style={{ color: isCurrent ? 'var(--color-gold)' : 'var(--color-dim)' }}>
        {isMobile ? <Smartphone size={20} /> : <Laptop size={20} />}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="font-bold text-sm" style={{ color: isCurrent ? 'var(--color-gold)' : 'var(--color-text)' }}>
            {d.ip_address} {isCurrent && '(This device)'}
          </span>
          {d.is_trusted && (
            <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, background: 'rgba(16,185,129,0.15)', color: 'var(--color-green)' }}>
              TRUSTED
            </span>
          )}
        </div>
        <div style={{ fontSize: '11px', color: 'var(--color-dim)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {d.user_agent}
        </div>
        <div style={{ fontSize: '10px', color: 'var(--color-dimmer)', marginTop: 2 }}>
          Last seen: {new Date(d.last_seen * 1000).toLocaleString()}
        </div>
      </div>
      {!isCurrent && (
        <button
          onClick={() => onRevoke(d.id)}
          style={{ fontSize: 10, fontWeight: 700, padding: '4px 8px', borderRadius: 6, background: 'rgba(239,68,68,0.1)', color: 'var(--color-red)', border: '1px solid rgba(239,68,68,0.3)' }}
        >
          Revoke
        </button>
      )}
    </div>
  )
}

export default function Account() {
  const { user, logout } = useAuthStore()
  const qc = useQueryClient()
  const [pwdForm, setPwdForm] = useState({ current_password: '', new_password: '', confirm_password: '' })
  const [pwdMsg, setPwdMsg] = useState({ text: '', type: '' })

  const { data: devices, isLoading: devLoading } = useQuery({
    queryKey: ['devices'],
    queryFn: () => api.get('/api/devices').then(r => r.data),
  })

  const { data: ctConfig } = useQuery({
    queryKey: ['ct-config'],
    queryFn: () => api.get('/api/copy-trading/config').then(r => r.data),
  })

  const revokeMutation = useMutation({
    mutationFn: (deviceId) => api.delete(`/api/devices/${deviceId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices'] }),
  })

  const pwdMutation = useMutation({
    mutationFn: (data) => api.post('/api/auth/change-password', data),
    onSuccess: () => {
      setPwdMsg({ text: 'Password changed successfully', type: 'success' })
      setPwdForm({ current_password: '', new_password: '', confirm_password: '' })
      setTimeout(() => logout(), 2000)
    },
    onError: (err) => {
      setPwdMsg({ text: err.response?.data?.detail || 'Failed to change password', type: 'error' })
    }
  })

  const handlePwdSubmit = (e) => {
    e.preventDefault()
    if (pwdForm.new_password !== pwdForm.confirm_password) {
      return setPwdMsg({ text: 'Passwords do not match', type: 'error' })
    }
    if (pwdForm.new_password.length < 8) {
      return setPwdMsg({ text: 'Password must be at least 8 characters', type: 'error' })
    }
    pwdMutation.mutate(pwdForm)
  }

  // Check API key age
  const keyAgeDays = ctConfig?.created_at ? Math.floor((Date.now() / 1000 - ctConfig.created_at) / 86400) : 0
  const needsRotation = keyAgeDays > 90

  return (
    <>
      <TopBar title="Account & Security" />
      
      <div className="px-4 pt-4 pb-20">
        
        {/* Profile Card */}
        <div className="card p-4 mb-4">
          <div className="flex justify-between items-center mb-2">
            <h3 style={{ fontSize: 16, fontWeight: 800 }}>{user?.username || user?.email}</h3>
            <span style={{ fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 12, background: 'var(--color-surface-3)', textTransform: 'uppercase' }}>
              {user?.tier} Plan
            </span>
          </div>
          <div style={{ fontSize: 13, color: 'var(--color-dim)' }}>
            {user?.email}
          </div>
          {user?.subscription_end && (
            <div style={{ fontSize: 12, color: 'var(--color-gold)', marginTop: 8 }}>
              Valid until: {new Date(user.subscription_end * 1000).toLocaleDateString()}
            </div>
          )}
        </div>

        {/* API Key Rotation Warning */}
        {needsRotation && (
          <div className="card p-4 mb-4" style={{ border: '1px solid rgba(240,185,11,0.3)', background: 'rgba(240,185,11,0.05)' }}>
            <div className="flex items-center gap-2 mb-2" style={{ color: 'var(--color-gold)' }}>
              <AlertTriangle size={18} />
              <h3 style={{ fontSize: 14, fontWeight: 800 }}>API Key Rotation Recommended</h3>
            </div>
            <p style={{ fontSize: 12, color: 'var(--color-text)', lineHeight: 1.4 }}>
              Your Binance API keys are {keyAgeDays} days old. For maximum security, we recommend rotating them every 90 days.
            </p>
          </div>
        )}

        {/* Change Password */}
        <div className="card p-4 mb-4">
          <div className="flex items-center gap-2 mb-4">
            <Key size={18} style={{ color: 'var(--color-dim)' }} />
            <h3 style={{ fontSize: 14, fontWeight: 700 }}>Change Password</h3>
          </div>
          <form onSubmit={handlePwdSubmit} className="flex flex-col gap-3">
            <input 
              type="password" 
              placeholder="Current Password" 
              className="input-field" 
              value={pwdForm.current_password} 
              onChange={e => setPwdForm({...pwdForm, current_password: e.target.value})} 
              required 
            />
            <input 
              type="password" 
              placeholder="New Password" 
              className="input-field" 
              value={pwdForm.new_password} 
              onChange={e => setPwdForm({...pwdForm, new_password: e.target.value})} 
              required 
            />
            <input 
              type="password" 
              placeholder="Confirm New Password" 
              className="input-field" 
              value={pwdForm.confirm_password} 
              onChange={e => setPwdForm({...pwdForm, confirm_password: e.target.value})} 
              required 
            />
            {pwdMsg.text && (
              <div style={{ fontSize: 12, color: pwdMsg.type === 'error' ? 'var(--color-red)' : 'var(--color-green)', marginTop: 4 }}>
                {pwdMsg.text}
              </div>
            )}
            <button type="submit" className="btn-gold mt-2" disabled={pwdMutation.isPending}>
              {pwdMutation.isPending ? 'Updating...' : 'Update Password'}
            </button>
          </form>
        </div>

        {/* Active Devices */}
        <div className="card p-4 mb-4">
          <div className="flex items-center gap-2 mb-4">
            <Shield size={18} style={{ color: 'var(--color-dim)' }} />
            <h3 style={{ fontSize: 14, fontWeight: 700 }}>Active Devices</h3>
          </div>
          {devLoading ? (
            <PageSpinner />
          ) : !devices?.length ? (
            <p style={{ fontSize: 13, color: 'var(--color-dim)' }}>No active devices.</p>
          ) : (
            <div>
              {devices.map(d => (
                <DeviceRow 
                  key={d.id} 
                  d={d} 
                  isCurrent={d.is_current} 
                  onRevoke={(id) => {
                    if (confirm('Revoke access for this device?')) revokeMutation.mutate(id)
                  }}
                />
              ))}
            </div>
          )}
        </div>

        <button 
          onClick={() => {
            if (confirm('Are you sure you want to log out?')) logout()
          }}
          className="w-full flex items-center justify-center gap-2 p-4 rounded-xl"
          style={{ background: 'rgba(239,68,68,0.1)', color: 'var(--color-red)', fontWeight: 800, border: 'none' }}
        >
          <LogOut size={18} /> Log Out
        </button>

      </div>
    </>
  )
}

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import { Eye, EyeOff } from 'lucide-react'

export default function Login() {
  const navigate = useNavigate()
  const { setUser } = useAuthStore()
  const [form, setForm] = useState({ username: '', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await api.post('/api/auth/login', { username: form.username, email: '', password: form.password })
      localStorage.setItem('token', res.data.access_token)
      setUser(res.data.user)
      navigate('/', { replace: true })
    } catch (err) {
      const msg = err.response?.data?.error ?? 'Login failed'
      if (msg === 'device_limit') {
        setError(`Device limit reached (${err.response.data.current_count}/${err.response.data.limit}). Remove a device from your profile.`)
      } else {
        setError(msg === 'Invalid credentials' ? 'Invalid username or password.' : msg)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="flex flex-col items-center justify-center min-h-dvh px-6"
      style={{ background: 'var(--color-bg)', paddingTop: 'env(safe-area-inset-top)', paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      <div className="w-full max-w-sm">
        <div className="text-center mb-10">
          <img
            src="/static/logo.jpeg"
            alt="Anunnaki World"
            style={{ width: 72, height: 72, borderRadius: '50%', margin: '0 auto 16px', display: 'block', border: '2px solid rgba(228,195,117,0.4)' }}
          />
          <h1 className="font-display text-3xl font-bold text-gold tracking-widest mb-2">ANUNNAKI</h1>
          <p style={{ color: 'var(--color-dim)', fontSize: '13px' }}>We do the math. You make the move.</p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-dim)', letterSpacing: '0.06em', textTransform: 'uppercase', display: 'block', marginBottom: 8 }}>
              Username
            </label>
            <input
              className="input-field"
              type="text"
              placeholder="your username"
              value={form.username}
              onChange={e => setForm(p => ({ ...p, username: e.target.value }))}
              required
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
            />
          </div>

          <div>
            <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-dim)', letterSpacing: '0.06em', textTransform: 'uppercase', display: 'block', marginBottom: 8 }}>
              Password
            </label>
            <div style={{ position: 'relative' }}>
              <input
                className="input-field"
                type={showPw ? 'text' : 'password'}
                placeholder="••••••••"
                value={form.password}
                onChange={e => setForm(p => ({ ...p, password: e.target.value }))}
                required
                autoComplete="current-password"
                style={{ paddingRight: 48 }}
              />
              <button
                type="button"
                onClick={() => setShowPw(p => !p)}
                style={{
                  position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)',
                  background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-dim)',
                  padding: 0, display: 'flex', alignItems: 'center',
                }}
              >
                {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </div>

          {error && (
            <div style={{
              background: 'rgba(239,68,68,0.1)',
              border: '1px solid rgba(239,68,68,0.3)',
              borderRadius: 10,
              padding: '12px 14px',
              color: 'var(--color-red)',
              fontSize: '13px',
            }}>
              {error}
            </div>
          )}

          <button className="btn-gold mt-2" type="submit" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign In'}
          </button>
        </form>

        <div className="text-center mt-4">
          <a href="/reset-password" style={{ color: 'var(--color-dim)', fontSize: '13px' }}>
            Forgot password?
          </a>
        </div>

        <div className="text-center mt-3">
          <a href="/app?signup=1" style={{ color: 'var(--color-dim)', fontSize: '13px' }}>
            No account? <span style={{ color: 'var(--color-gold)' }}>Create one</span>
          </a>
        </div>
      </div>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { Copy, Share2, Link as LinkIcon, Gift } from 'lucide-react'

export default function Referral() {
  const { user } = useAuthStore()

  const { data: codeData } = useQuery({
    queryKey: ['ref-code'],
    queryFn: () => api.get('/api/referral/code').then(r => r.data),
  })

  const { data: statsData, isLoading } = useQuery({
    queryKey: ['ref-stats'],
    queryFn: () => api.get('/api/referral/stats').then(r => r.data),
  })

  const refCode = codeData?.code
  const refUrl = refCode ? `https://anunnakiworld.com/?ref=${refCode}` : 'Loading...'

  const handleCopy = () => {
    if (refCode) {
      navigator.clipboard.writeText(refUrl)
      alert('Referral link copied to clipboard!')
    }
  }

  const handleShare = () => {
    if (refCode && navigator.share) {
      navigator.share({
        title: 'Anunnaki World Signals',
        text: 'Join me on Anunnaki World and get 7 bonus days of Pro signals for free!',
        url: refUrl,
      }).catch(console.error)
    } else {
      handleCopy()
    }
  }

  const stats = statsData || { total_referred: 0, converted: 0, days_earned: 0, pending: 0, events: [] }

  return (
    <>
      <TopBar title="Refer & Earn" />
      
      <div className="px-4 pt-4 pb-20">
        
        {/* Intro Card */}
        <div className="card p-4 mb-4 text-center" style={{ background: 'linear-gradient(135deg, rgba(228,195,117,0.1) 0%, rgba(228,195,117,0.02) 100%)', borderColor: 'rgba(228,195,117,0.3)' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 48, height: 48, borderRadius: '50%', background: 'rgba(228,195,117,0.2)', color: 'var(--color-gold)', marginBottom: 12 }}>
            <Gift size={24} />
          </div>
          <h2 style={{ fontSize: 18, fontWeight: 800, marginBottom: 8 }}>Give 7 Days, Get 7 Days</h2>
          <p style={{ fontSize: 13, color: 'var(--color-text)', lineHeight: 1.5 }}>
            Share your unique link. When someone subscribes, <strong>you both receive 7 bonus days</strong> automatically.
          </p>
        </div>

        {/* Link Card */}
        <div className="card p-4 mb-4">
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 12 }}>
            Your Referral Link
          </div>
          
          <div className="flex gap-2 mb-3">
            <div className="flex-1 flex items-center bg-black border border-gray-800 rounded-lg px-3 overflow-hidden">
              <LinkIcon size={14} style={{ color: 'var(--color-dim)', marginRight: 8, flexShrink: 0 }} />
              <input 
                type="text" 
                readOnly 
                value={refUrl} 
                className="w-full bg-transparent border-none text-sm font-mono focus:outline-none py-3"
                style={{ color: 'var(--color-text)' }}
              />
            </div>
          </div>

          <div className="flex gap-3">
            <button 
              onClick={handleCopy}
              className="flex-1 flex items-center justify-center gap-2 py-3 rounded-lg font-bold text-sm"
              style={{ background: 'rgba(255,255,255,0.1)', color: '#fff' }}
            >
              <Copy size={16} /> Copy
            </button>
            <button 
              onClick={handleShare}
              className="flex-1 flex items-center justify-center gap-2 py-3 rounded-lg font-bold text-sm btn-gold w-auto m-0"
            >
              <Share2 size={16} /> Share
            </button>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 gap-3 mb-5">
          <div className="card p-3 text-center">
            <div style={{ fontSize: 24, fontWeight: 800, color: '#50b4ff' }}>{stats.total_referred}</div>
            <div style={{ fontSize: 11, color: 'var(--color-dim)', marginTop: 2 }}>Total Referred</div>
          </div>
          <div className="card p-3 text-center">
            <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--color-green)' }}>{stats.converted}</div>
            <div style={{ fontSize: 11, color: 'var(--color-dim)', marginTop: 2 }}>Converted</div>
          </div>
          <div className="card p-3 text-center">
            <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--color-gold)' }}>{stats.days_earned}</div>
            <div style={{ fontSize: 11, color: 'var(--color-dim)', marginTop: 2 }}>Bonus Days</div>
          </div>
          <div className="card p-3 text-center">
            <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--color-dim)' }}>{stats.pending}</div>
            <div style={{ fontSize: 11, color: 'var(--color-dim)', marginTop: 2 }}>Pending</div>
          </div>
        </div>

        {/* History */}
        <h3 style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-dim)', textTransform: 'uppercase', marginBottom: 12 }}>History</h3>
        {isLoading ? (
          <PageSpinner />
        ) : stats.events?.length === 0 ? (
          <div className="card p-6 text-center text-sm" style={{ color: 'var(--color-dim)' }}>
            No referrals yet. Share your link to get started!
          </div>
        ) : (
          <div className="card px-4 py-2">
            {stats.events.map((ev, i) => (
              <div key={i} className="flex justify-between items-center py-3" style={{ borderBottom: i === stats.events.length - 1 ? 'none' : '1px solid var(--color-border)' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{ev.type === 'signup' ? 'New Signup' : 'Bonus Rewarded'}</div>
                  <div style={{ fontSize: 11, color: 'var(--color-dim)' }}>{new Date(ev.timestamp * 1000).toLocaleDateString()}</div>
                </div>
                <div style={{ fontSize: 13, fontWeight: 700, color: ev.type === 'signup' ? 'var(--color-dim)' : 'var(--color-gold)' }}>
                  {ev.type === 'reward' ? '+7 Days' : 'Pending'}
                </div>
              </div>
            ))}
          </div>
        )}

      </div>
    </>
  )
}

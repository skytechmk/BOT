import { useQuery } from '@tanstack/react-query'
import { api } from '@/services/api'
import { useAuthStore } from '@/store/useAuthStore'
import TopBar from '@/components/TopBar'
import { PageSpinner } from '@/components/ui/Spinner'
import { Check, Star } from 'lucide-react'

function PlanCard({ plan, isCurrent }) {
  const isPro = plan.id === 'pro'
  
  return (
    <div className="card mb-4" style={{ 
      border: isPro ? '1px solid var(--color-gold)' : '1px solid var(--color-border)',
      background: isPro ? 'rgba(228,195,117,0.05)' : 'var(--color-surface)'
    }}>
      {isPro && (
        <div style={{ background: 'var(--color-gold)', color: '#000', fontSize: 10, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.05em', textAlign: 'center', padding: '4px 0', borderTopLeftRadius: 15, borderTopRightRadius: 15 }}>
          Most Popular
        </div>
      )}
      <div className="p-5">
        <h3 style={{ fontSize: 20, fontWeight: 800, marginBottom: 4, color: isPro ? 'var(--color-gold)' : 'var(--color-text)' }}>
          {plan.name}
        </h3>
        <p style={{ fontSize: 13, color: 'var(--color-dim)', marginBottom: 16 }}>{plan.description}</p>
        
        <div className="flex items-end gap-1 mb-6">
          <span style={{ fontSize: 32, fontWeight: 800 }}>${plan.price}</span>
          <span style={{ fontSize: 13, color: 'var(--color-dim)', paddingBottom: 6 }}>/mo</span>
        </div>

        <a 
          href={isCurrent ? '#' : '/app'} 
          className={isPro ? 'btn-gold' : 'btn-ghost'} 
          style={{ width: '100%', display: 'flex', justifyContent: 'center', marginBottom: 20, opacity: isCurrent ? 0.5 : 1, pointerEvents: isCurrent ? 'none' : 'auto' }}
        >
          {isCurrent ? 'Current Plan' : 'Upgrade'}
        </a>

        <div className="flex flex-col gap-3">
          {plan.features?.map((f, i) => (
            <div key={i} className="flex items-start gap-3">
              <Check size={16} style={{ color: 'var(--color-green)', marginTop: 2, flexShrink: 0 }} />
              <span style={{ fontSize: 13, color: 'var(--color-text)', lineHeight: 1.4 }}>{f}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function Pricing() {
  const { user } = useAuthStore()

  const { data: plans, isLoading } = useQuery({
    queryKey: ['plans'],
    queryFn: () => api.get('/api/plans').then(r => r.data),
  })

  // Hardcoded fallback plans if API isn't exposing them exactly how we want
  const defaultPlans = [
    {
      id: 'free',
      name: 'Free',
      description: 'Test the waters with delayed signals.',
      price: 0,
      features: ['24h delayed signals', 'Basic dashboard', 'End-of-day analytics', 'No copy trading']
    },
    {
      id: 'plus',
      name: 'Plus',
      description: 'Live signals and automation.',
      price: 49,
      features: ['Real-time signals', 'Full automated copy-trading', 'TV Screener access', 'Liquidation Heatmap']
    },
    {
      id: 'pro',
      name: 'Pro',
      description: 'The institutional package.',
      price: 99,
      features: ['Everything in Plus', 'Pre-signal alerts', 'Market Analytics (CVD, MFI)', 'Backtesting Engine', 'VIP Telegram Channel']
    }
  ]

  const displayPlans = plans?.length ? plans : defaultPlans

  return (
    <>
      <TopBar title="Pricing" />
      
      <div className="px-4 pt-4 pb-20">
        
        <div className="text-center mb-6">
          <h2 style={{ fontSize: 24, fontWeight: 800, marginBottom: 8 }}>Upgrade your trading.</h2>
          <p style={{ fontSize: 14, color: 'var(--color-dim)', lineHeight: 1.5, maxWidth: 300, margin: '0 auto' }}>
            Choose the tier that fits your needs. Cancel anytime.
          </p>
        </div>

        {isLoading && !plans ? (
          <PageSpinner />
        ) : (
          <div>
            {displayPlans.map(p => (
              <PlanCard key={p.id} plan={p} isCurrent={user?.tier === p.id} />
            ))}
          </div>
        )}

      </div>
    </>
  )
}

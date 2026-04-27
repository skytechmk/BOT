import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Zap, Bot, LineChart, Grid3x3 } from 'lucide-react'

const tabs = [
  { to: '/',             icon: LayoutDashboard, label: 'Home'     },
  { to: '/signals',      icon: Zap,             label: 'Signals'  },
  { to: '/copy-trading', icon: Bot,             label: 'Copy'     },
  { to: '/charts',       icon: LineChart,       label: 'Charts'   },
  { to: '/more',         icon: Grid3x3,         label: 'More'     },
]

export default function BottomNav() {
  return (
    <nav
      style={{
        background: 'rgba(5,8,15,0.95)',
        backdropFilter: 'blur(20px)',
        borderTop: '1px solid var(--color-border)',
        paddingBottom: 'env(safe-area-inset-bottom)',
      }}
      className="fixed bottom-0 left-0 right-0 z-50 flex"
    >
      {tabs.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          className={({ isActive }) =>
            `flex-1 flex flex-col items-center justify-center gap-1 py-2 transition-colors ${
              isActive ? 'text-gold' : 'text-dimmer'
            }`
          }
        >
          <Icon size={22} strokeWidth={1.8} />
          <span style={{ fontSize: '10px', fontWeight: 600, letterSpacing: '0.04em' }}>
            {label}
          </span>
        </NavLink>
      ))}
    </nav>
  )
}

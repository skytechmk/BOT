import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/useAuthStore'
import { tierLabel, tierColor } from '@/utils/helpers'
import TopBar from '@/components/TopBar'
import {
  Flame, FlaskConical, Activity, LineChart, User,
  LogOut, ExternalLink, ChevronRight, Gift, CreditCard,
  BarChart2, Zap, TrendingUp, BarChart, HelpCircle,
  Beaker, Shield, Diamond, Search
} from 'lucide-react'

function MenuSection({ title, children }) {
  return (
    <div className="mb-4">
      {title && (
        <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--color-dimmer)', textTransform: 'uppercase', letterSpacing: '0.07em', padding: '0 16px 8px' }}>
          {title}
        </div>
      )}
      <div className="card mx-4 overflow-hidden">
        {children}
      </div>
    </div>
  )
}

function MenuItem({ to, href, icon: Icon, iconColor, label, sub, badge, badgeColor, danger, onClick }) {
  const inner = (
    <div
      className="flex items-center gap-4 px-4 py-4"
      style={{ borderBottom: '1px solid var(--color-border)', cursor: 'pointer' }}
      onClick={onClick}
    >
      <div style={{
        width: 36, height: 36, borderRadius: 10, flexShrink: 0,
        background: danger ? 'rgba(239,68,68,0.1)' : iconColor ? `${iconColor}18` : 'rgba(255,255,255,0.05)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <Icon size={17} style={{ color: danger ? 'var(--color-red)' : iconColor ?? 'var(--color-dim)' }} />
      </div>
      <div className="flex-1 min-w-0">
        <div style={{ fontWeight: 600, fontSize: '14px', color: danger ? 'var(--color-red)' : 'var(--color-text)' }}>
          {label}
        </div>
        {sub && <div style={{ fontSize: '12px', color: 'var(--color-dim)', marginTop: 1 }}>{sub}</div>}
      </div>
      {badge && (
        <span style={{
          fontSize: '10px', fontWeight: 800, padding: '2px 8px', borderRadius: 20,
          background: badgeColor ? `${badgeColor}18` : 'rgba(228,195,117,0.15)',
          color: badgeColor ?? 'var(--color-gold)',
          border: `1px solid ${badgeColor ? `${badgeColor}30` : 'rgba(228,195,117,0.25)'}`,
          marginRight: 4, flexShrink: 0,
        }}>{badge}</span>
      )}
      <ChevronRight size={15} style={{ color: 'var(--color-dimmer)', flexShrink: 0 }} />
    </div>
  )

  if (to) return <Link to={to} style={{ textDecoration: 'none' }}>{inner}</Link>
  if (href) return <a href={href} style={{ textDecoration: 'none' }}>{inner}</a>
  return inner
}

export default function More() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  const nextBilling = user?.tier_expires && !user?.is_admin
    ? new Date(user.tier_expires * 1000).toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' })
    : null

  return (
    <>
      <TopBar title="More" />
      <div className="pt-4 pb-8">
        {/* User card */}
        <div className="px-4 mb-5">
          <div className="card p-4 flex items-center gap-4">
            <div style={{
              width: 50, height: 50, borderRadius: '50%', flexShrink: 0,
              background: 'rgba(228,195,117,0.15)',
              border: '2px solid rgba(228,195,117,0.3)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 20, fontWeight: 800, color: 'var(--color-gold)',
            }}>
              {(user?.username?.[0] ?? 'A').toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <div style={{ fontWeight: 800, fontSize: '16px', marginBottom: 1 }}>{user?.username ?? 'User'}</div>
              <div style={{ fontSize: '12px', color: 'var(--color-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginBottom: 4 }}>
                {user?.email}
              </div>
              <span style={{
                display: 'inline-block',
                fontSize: '11px', fontWeight: 700, padding: '2px 10px',
                borderRadius: 20, background: 'rgba(255,255,255,0.07)',
                color: tierColor(user?.tier),
              }}>
                {user?.is_admin ? 'Admin' : `${tierLabel(user?.tier)} Plan`}
              </span>
            </div>
          </div>

          {nextBilling && (
            <div className="mt-2 px-4 py-2.5 rounded-xl flex items-center justify-between"
              style={{ background: 'rgba(228,195,117,0.05)', border: '1px solid rgba(228,195,117,0.15)' }}>
              <span style={{ fontSize: '12px', color: 'var(--color-dim)' }}>Access expires</span>
              <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--color-gold)' }}>{nextBilling}</span>
            </div>
          )}
        </div>

        {/* Trading Tools */}
        <MenuSection title="Trading Tools">
          <MenuItem to="/screener"          icon={Search}     iconColor="var(--color-text)" label="Screener"          sub="Live crypto perpetuals by signal strength" badge="Plus" />
          <MenuItem to="/charts"           icon={BarChart2}  iconColor="#66ccff"         label="Charts"            sub="Price charts, OHLCV, multi-pair"      badge="Plus" />
          <MenuItem to="/presignals"        icon={Zap}        iconColor="#ff6b6b"         label="Pre-Signals"       sub="Early alerts before signal fires"     badge="Pro" />
          <MenuItem to="/market-analytics"  icon={TrendingUp} iconColor="var(--color-gold)" label="Market Analytics" sub="CVD, MFI, L/S, OI, funding rate"      badge="Pro" />
          <MenuItem to="/heatmap"           icon={Flame}      iconColor="#ff8c42"         label="Liq Heatmap"       sub="Live liquidation clusters by pair" />
          <MenuItem to="/macro"             icon={Activity}   iconColor="#a78bfa"         label="Macro State"       sub="Fear & greed, market risk regime" />
          <MenuItem to="/backtest"          icon={FlaskConical} iconColor="var(--color-blue)" label="Backtesting"   sub="Historical signal replay engine"      badge="Pro" />
          <MenuItem to="/analytics"         icon={BarChart}   iconColor="var(--color-green)" label="Analytics"     sub="Win rate, equity curve, top pairs"    badge="Plus" />
        </MenuSection>

        {/* Account */}
        <MenuSection title="Account">
          <MenuItem to="/profile"  icon={User}       iconColor="var(--color-dim)" label="Profile"           sub="Username, plan, expiry" />
          <MenuItem to="/account"  icon={Shield}     iconColor="var(--color-blue)" label="Account & Security" sub="Devices, billing, password" />
          <MenuItem to="/referral" icon={Gift}        iconColor="var(--color-green)" label="Refer & Earn"     sub="7 bonus days per successful referral" />
          <MenuItem to="/pricing"  icon={Diamond}    iconColor="var(--color-gold)" label="Pricing & Plans"   sub="Upgrade or view available plans" />
        </MenuSection>

        {/* Admin section — only visible to admins */}
        {user?.is_admin && (
          <MenuSection title="Admin">
            <MenuItem to="/lab"    icon={Beaker}  iconColor="#ff6b9d" label="Lab Signals"  sub="Experimental signal paths" badge="Admin" badgeColor="#ff6b9d" />
            <MenuItem href="/admin" icon={Shield} iconColor="#ff6b9d" label="Admin Panel"  sub="User management, full control" badge="Admin" badgeColor="#ff6b9d" />
          </MenuSection>
        )}

        {/* Help */}
        <MenuSection title="Help">
          <MenuItem to="/support"  icon={HelpCircle}   iconColor="var(--color-dim)" label="Support & FAQ" sub="Contact, docs, common questions" />
          <MenuItem href="/app"    icon={ExternalLink}  iconColor="var(--color-dim)" label="Full Dashboard" sub="Open desktop web app" />
        </MenuSection>

        {/* Sign out */}
        <MenuSection title="">
          <MenuItem
            icon={LogOut}
            label="Sign Out"
            danger
            onClick={() => { logout(); navigate('/login', { replace: true }) }}
          />
        </MenuSection>

        <div className="text-center mt-2" style={{ color: 'var(--color-dimmer)', fontSize: '11px' }}>
          Anunnaki World · Mobile v1.0
        </div>
      </div>
    </>
  )
}

import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs) {
  return twMerge(clsx(inputs))
}

export function formatPnl(val) {
  if (val == null) return '—'
  const n = parseFloat(val)
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

export function pnlColor(val) {
  if (val == null) return 'var(--color-dim)'
  return parseFloat(val) >= 0 ? 'var(--color-green)' : 'var(--color-red)'
}

export function formatPrice(val, decimals = 4) {
  if (val == null || val === '') return '—'
  const n = parseFloat(val)
  if (isNaN(n)) return '—'
  if (n >= 10000) return n.toLocaleString('en-US', { maximumFractionDigits: 0 })
  if (n >= 1) return n.toFixed(2)
  return n.toFixed(decimals)
}

export function timeAgo(ts) {
  if (!ts) return '—'
  const sec = Math.floor((Date.now() - ts * 1000) / 1000)
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}

export function cleanPair(pair) {
  return pair?.replace('USDT', '') ?? pair
}

export function tierLabel(tier) {
  const map = { free: 'Free', plus: 'Plus', pro: 'Pro', elite: 'Elite', ultra: 'Admin' }
  return map[tier] ?? tier
}

export function tierColor(tier) {
  const map = {
    free: 'var(--color-dim)',
    plus: 'var(--color-blue)',
    pro: 'var(--color-gold)',
    elite: 'var(--color-purple)',
    ultra: '#ff6b6b',
  }
  return map[tier] ?? 'var(--color-dim)'
}

const TIER_RANK = { free: 0, plus: 1, pro: 2, elite: 3, ultra: 99 }

export function hasTier(user, minTier) {
  if (!user) return false
  if (user.is_admin) return true
  return (TIER_RANK[user.tier] ?? 0) >= (TIER_RANK[minTier] ?? 0)
}

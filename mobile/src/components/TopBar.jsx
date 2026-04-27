import { useAuthStore } from '@/store/useAuthStore'
import { tierLabel, tierColor } from '@/utils/helpers'

export default function TopBar({ title, right }) {
  const { user } = useAuthStore()

  return (
    <header
      style={{
        background: 'rgba(5,8,15,0.9)',
        backdropFilter: 'blur(20px)',
        borderBottom: '1px solid var(--color-border)',
        paddingTop: 'env(safe-area-inset-top)',
      }}
      className="fixed top-0 left-0 right-0 z-40"
    >
      <div className="flex items-center justify-between px-4 h-14">
        <div className="flex items-center gap-2">
          <span className="font-display font-bold text-lg text-gold tracking-wider">
            {title ?? 'ANUNNAKI'}
          </span>
          {!title && user && (
            <span
              className="text-xs font-bold px-2 py-0.5 rounded-full"
              style={{
                background: 'rgba(255,255,255,0.06)',
                color: tierColor(user.tier),
              }}
            >
              {tierLabel(user.tier)}
            </span>
          )}
        </div>
        {right && <div className="flex items-center gap-2">{right}</div>}
      </div>
    </header>
  )
}

export default function Spinner({ size = 24 }) {
  return (
    <div
      className="rounded-full border-2 border-t-transparent animate-spin"
      style={{
        width: size,
        height: size,
        borderColor: 'var(--color-gold)',
        borderTopColor: 'transparent',
      }}
    />
  )
}

export function PageSpinner() {
  return (
    <div className="flex items-center justify-center h-48">
      <Spinner size={32} />
    </div>
  )
}

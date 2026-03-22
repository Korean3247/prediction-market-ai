import clsx from 'clsx'

type BadgeVariant =
  | 'buy'
  | 'skip'
  | 'observe'
  | 'active'
  | 'resolved'
  | 'positive'
  | 'negative'
  | 'neutral'

interface BadgeProps {
  variant: BadgeVariant
  label: string
}

const variantMap: Record<BadgeVariant, string> = {
  buy: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30',
  skip: 'bg-rose-500/20 text-rose-400 border border-rose-500/30',
  observe: 'bg-amber-500/20 text-amber-400 border border-amber-500/30',
  active: 'bg-sky-500/20 text-sky-400 border border-sky-500/30',
  resolved: 'bg-gray-500/20 text-gray-400 border border-gray-500/30',
  positive: 'bg-emerald-500/10 text-emerald-400',
  negative: 'bg-rose-500/10 text-rose-400',
  neutral: 'bg-gray-500/10 text-gray-400'
}

export default function Badge({ variant, label }: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide',
        variantMap[variant]
      )}
    >
      {label}
    </span>
  )
}

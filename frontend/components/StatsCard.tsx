import { type LucideIcon } from 'lucide-react'
import clsx from 'clsx'

interface StatsCardProps {
  title: string
  value: string | number
  subtitle?: string
  icon: LucideIcon
  trend?: number
  color?: 'blue' | 'green' | 'red' | 'yellow' | 'purple'
}

const colorMap: Record<string, { gradient: string; iconBg: string; icon: string }> = {
  blue: {
    gradient: 'from-sky-600 to-sky-800',
    iconBg: 'bg-sky-500/30',
    icon: 'text-sky-200'
  },
  green: {
    gradient: 'from-emerald-600 to-emerald-800',
    iconBg: 'bg-emerald-500/30',
    icon: 'text-emerald-200'
  },
  red: {
    gradient: 'from-rose-600 to-rose-800',
    iconBg: 'bg-rose-500/30',
    icon: 'text-rose-200'
  },
  yellow: {
    gradient: 'from-amber-600 to-amber-800',
    iconBg: 'bg-amber-500/30',
    icon: 'text-amber-200'
  },
  purple: {
    gradient: 'from-violet-600 to-violet-800',
    iconBg: 'bg-violet-500/30',
    icon: 'text-violet-200'
  }
}

export default function StatsCard({
  title,
  value,
  subtitle,
  icon: Icon,
  trend,
  color = 'blue'
}: StatsCardProps) {
  const colors = colorMap[color]

  return (
    <div
      className={clsx(
        'relative overflow-hidden rounded-xl bg-gradient-to-br p-6 text-white shadow-lg',
        colors.gradient
      )}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-sm font-medium text-white/70">{title}</p>
          <p className="mt-1 text-3xl font-bold tracking-tight">{value}</p>
          {subtitle && <p className="mt-1 text-sm text-white/60">{subtitle}</p>}
          {trend !== undefined && (
            <p
              className={clsx(
                'mt-2 flex items-center gap-1 text-sm font-medium',
                trend >= 0 ? 'text-emerald-300' : 'text-rose-300'
              )}
            >
              <span>{trend >= 0 ? '▲' : '▼'}</span>
              <span>{Math.abs(trend).toFixed(1)}% vs last period</span>
            </p>
          )}
        </div>
        <div className={clsx('flex h-12 w-12 items-center justify-center rounded-xl', colors.iconBg)}>
          <Icon className={clsx('h-6 w-6', colors.icon)} />
        </div>
      </div>

      {/* Decorative circle */}
      <div className="absolute -right-8 -top-8 h-32 w-32 rounded-full bg-white/5" />
      <div className="absolute -bottom-6 -right-4 h-20 w-20 rounded-full bg-white/5" />
    </div>
  )
}

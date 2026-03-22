'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Brain, LayoutDashboard, TrendingUp, Target, BarChart3, BarChart2, FlaskConical } from 'lucide-react'
import clsx from 'clsx'

const navItems = [
  { label: 'Dashboard', href: '/', icon: LayoutDashboard },
  { label: 'Markets', href: '/markets', icon: TrendingUp },
  { label: 'Decisions', href: '/decisions', icon: Target },
  { label: 'Outcomes', href: '/outcomes', icon: BarChart3 },
  { label: 'Backtest', href: '/backtest', icon: BarChart2 },
  { label: 'Paper Trading', href: '/paper-trading', icon: FlaskConical },
]

export default function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-16 flex-col bg-gray-950 md:w-60">
      {/* Logo */}
      <div className="flex h-16 items-center gap-3 border-b border-gray-800 px-4">
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-sky-600">
          <Brain className="h-5 w-5 text-white" />
        </div>
        <span className="hidden text-lg font-bold text-white md:block">PredictAI</span>
      </div>

      {/* Navigation */}
      <nav className="flex flex-1 flex-col gap-1 p-2 pt-4">
        {navItems.map(({ label, href, icon: Icon }) => {
          const isActive =
            href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(href + '/')
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-sky-600 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-white'
              )}
            >
              <Icon className="h-5 w-5 flex-shrink-0" />
              <span className="hidden md:block">{label}</span>
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-gray-800 p-4">
        <p className="hidden text-xs text-gray-600 md:block">Prediction Market AI v0.1</p>
      </div>
    </aside>
  )
}

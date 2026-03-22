'use client'

import { useEffect, useState } from 'react'
import { TrendingUp, Trophy, DollarSign, Brain, RefreshCw, Scan } from 'lucide-react'
import StatsCard from '@/components/StatsCard'
import LoadingSpinner from '@/components/LoadingSpinner'
import Badge from '@/components/Badge'
import { fetchStats, triggerScan, type Stats } from '@/lib/api'

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [scanLoading, setScanLoading] = useState(false)
  const [scanMessage, setScanMessage] = useState<string | null>(null)

  const loadStats = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await fetchStats()
      setStats(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot connect to backend')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStats()
  }, [])

  const handleScan = async () => {
    try {
      setScanLoading(true)
      setScanMessage(null)
      const result = await triggerScan()
      setScanMessage(`Scan complete: found ${result.markets_found} markets`)
      await loadStats()
    } catch (err) {
      setScanMessage(
        `Scan failed: ${err instanceof Error ? err.message : 'Unknown error'}`
      )
    } finally {
      setScanLoading(false)
      setTimeout(() => setScanMessage(null), 5000)
    }
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="mt-1 text-sm text-gray-400">
            Overview of your prediction market performance
          </p>
        </div>
        <button
          onClick={loadStats}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg bg-gray-700 px-4 py-2 text-sm font-medium text-gray-300 transition-colors hover:bg-gray-600 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Error State */}
      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4">
          <p className="text-sm text-rose-400">
            <span className="font-semibold">Connection Error:</span> {error}
          </p>
          <p className="mt-1 text-xs text-rose-500">
            Make sure the backend is running at http://localhost:8000
          </p>
        </div>
      )}

      {/* Loading State */}
      {loading && !error && <LoadingSpinner size="lg" />}

      {/* Stats Grid */}
      {stats && !loading && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatsCard
              title="Total Markets"
              value={stats.total_markets.toLocaleString()}
              subtitle={`${stats.active_markets} active`}
              icon={TrendingUp}
              color="blue"
            />
            <StatsCard
              title="Win Rate"
              value={`${(stats.win_rate * 100).toFixed(1)}%`}
              subtitle={`${stats.total_predictions} predictions`}
              icon={Trophy}
              color={stats.win_rate >= 0.5 ? 'green' : 'red'}
            />
            <StatsCard
              title="Total PnL"
              value={`$${stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(2)}`}
              subtitle="Realized profit/loss"
              icon={DollarSign}
              color={stats.total_pnl >= 0 ? 'green' : 'red'}
            />
            <StatsCard
              title="Avg Confidence"
              value={`${(stats.avg_confidence * 100).toFixed(1)}%`}
              subtitle="Model confidence"
              icon={Brain}
              color="purple"
            />
          </div>

          {/* Quick Actions & Decision Breakdown */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Quick Actions */}
            <div className="rounded-xl border border-gray-700 bg-gray-800 p-6">
              <h2 className="mb-4 text-base font-semibold text-white">Quick Actions</h2>
              <div className="flex flex-col gap-3">
                <button
                  onClick={handleScan}
                  disabled={scanLoading}
                  className="flex items-center justify-center gap-2 rounded-lg bg-sky-600 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {scanLoading ? (
                    <>
                      <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                      Scanning markets...
                    </>
                  ) : (
                    <>
                      <Scan className="h-4 w-4" />
                      Scan Markets
                    </>
                  )}
                </button>

                {scanMessage && (
                  <div
                    className={`rounded-lg p-3 text-sm ${
                      scanMessage.startsWith('Scan failed')
                        ? 'bg-rose-500/10 text-rose-400'
                        : 'bg-emerald-500/10 text-emerald-400'
                    }`}
                  >
                    {scanMessage}
                  </div>
                )}
              </div>
            </div>

            {/* Decision Breakdown */}
            <div className="rounded-xl border border-gray-700 bg-gray-800 p-6">
              <h2 className="mb-4 text-base font-semibold text-white">Decision Breakdown</h2>
              {!stats.decisions_by_action || Object.keys(stats.decisions_by_action).length === 0 ? (
                <p className="text-sm text-gray-500">No decisions recorded yet.</p>
              ) : (
                <div className="space-y-3">
                  {Object.entries(stats.decisions_by_action).map(([action, count]) => {
                    const variant = action as 'buy' | 'skip' | 'observe'
                    const total = Object.values(stats.decisions_by_action).reduce(
                      (a, b) => a + b,
                      0
                    )
                    const pct = total > 0 ? (count / total) * 100 : 0
                    return (
                      <div key={action} className="flex items-center gap-3">
                        <Badge variant={variant} label={action} />
                        <div className="flex-1">
                          <div className="h-2 overflow-hidden rounded-full bg-gray-700">
                            <div
                              className={`h-full rounded-full transition-all ${
                                action === 'buy'
                                  ? 'bg-emerald-500'
                                  : action === 'skip'
                                  ? 'bg-rose-500'
                                  : 'bg-amber-500'
                              }`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                        <span className="w-16 text-right text-sm text-gray-400">
                          {count} ({pct.toFixed(0)}%)
                        </span>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

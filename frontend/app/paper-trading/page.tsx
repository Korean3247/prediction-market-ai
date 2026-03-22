'use client'

import { useEffect, useState, useCallback } from 'react'
import { AlertCircle, FlaskConical } from 'lucide-react'
import LoadingSpinner from '@/components/LoadingSpinner'
import EmptyState from '@/components/EmptyState'
import { fetchPerformanceStats, fetchPaperTrades, type PaperTrade, type PerformanceStats } from '@/lib/api'

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function StatCard({
  label,
  value,
  sub,
  color,
}: {
  label: string
  value: string
  sub?: string
  color?: string
}) {
  return (
    <div className="rounded-xl border border-gray-700 bg-gray-800 p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-400">{label}</p>
      <p className={`mt-2 text-2xl font-bold ${color ?? 'text-white'}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-gray-500">{sub}</p>}
    </div>
  )
}

function SegmentSection({
  title,
  stats,
}: {
  title: string
  stats: PerformanceStats['short_term'] | PerformanceStats['long_term']
}) {
  return (
    <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-5">
      <h3 className="mb-4 text-base font-semibold text-white">{title}</h3>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div>
          <p className="text-xs text-gray-400">Trades</p>
          <p className="text-lg font-bold text-white">{stats.total}</p>
        </div>
        <div>
          <p className="text-xs text-gray-400">Win Rate</p>
          <p className="text-lg font-bold text-emerald-400">
            {(stats.win_rate * 100).toFixed(1)}%
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-400">Total P&L</p>
          <p
            className={`text-lg font-bold ${
              stats.total_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
            }`}
          >
            {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl.toFixed(2)}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-400">Avg Edge</p>
          <p className="text-lg font-bold text-sky-400">
            {(stats.avg_edge * 100).toFixed(1)}%
          </p>
        </div>
      </div>
      <div className="mt-3 flex gap-4 text-xs text-gray-500">
        <span>Won: <span className="text-emerald-400">{stats.won}</span></span>
        <span>Lost: <span className="text-rose-400">{stats.lost}</span></span>
        <span>Open: <span className="text-amber-400">{stats.open}</span></span>
      </div>
    </div>
  )
}

function statusBadge(status: string) {
  const classes: Record<string, string> = {
    open: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    won: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    lost: 'bg-rose-500/20 text-rose-400 border-rose-500/30',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${
        classes[status] ?? 'bg-gray-500/20 text-gray-400 border-gray-500/30'
      }`}
    >
      {status.toUpperCase()}
    </span>
  )
}

export default function PaperTradingPage() {
  const [stats, setStats] = useState<PerformanceStats | null>(null)
  const [trades, setTrades] = useState<PaperTrade[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const [statsData, tradesData] = await Promise.all([
        fetchPerformanceStats(),
        fetchPaperTrades(100),
      ])
      setStats(statsData)
      setTrades(tradesData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot connect to backend')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Paper Trading</h1>
        <p className="mt-1 text-sm text-gray-400">
          Virtual signal performance tracking — no real money at risk
        </p>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4">
          <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-rose-400" />
          <div>
            <p className="text-sm font-medium text-rose-400">Cannot connect to backend</p>
            <p className="mt-0.5 text-xs text-rose-500">{error}</p>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && !error && <LoadingSpinner />}

      {!loading && !error && stats && (
        <>
          {/* Summary Stats Cards */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard
              label="Paper Win Rate"
              value={`${(stats.paper_trading.win_rate * 100).toFixed(1)}%`}
              sub={`${stats.paper_trading.won}W / ${stats.paper_trading.lost}L`}
              color="text-emerald-400"
            />
            <StatCard
              label="Paper P&L"
              value={`${stats.paper_trading.total_pnl >= 0 ? '+' : ''}$${stats.paper_trading.total_pnl.toFixed(2)}`}
              sub={`${stats.paper_trading.total_trades} total trades`}
              color={stats.paper_trading.total_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}
            />
            <StatCard
              label="Avg Edge"
              value={`${(stats.paper_trading.avg_edge * 100).toFixed(1)}%`}
              sub="across all paper trades"
              color="text-sky-400"
            />
            <StatCard
              label="Signal Rate"
              value={`${(stats.signal_stats.paper_signal_rate * 100).toFixed(1)}%`}
              sub={`Buy: ${(stats.signal_stats.buy_signal_rate * 100).toFixed(1)}%`}
              color="text-violet-400"
            />
          </div>

          {/* Short-term vs Long-term Sections */}
          <div className="grid gap-4 sm:grid-cols-2">
            <SegmentSection title="Short-term (within 72h)" stats={stats.short_term} />
            <SegmentSection title="Long-term (7 days+)" stats={stats.long_term} />
          </div>

          {/* Signal Stats */}
          <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-5">
            <h3 className="mb-3 text-base font-semibold text-white">Signal Analytics</h3>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 text-sm">
              <div>
                <p className="text-xs text-gray-400">Analyzed Today</p>
                <p className="mt-1 font-semibold text-white">{stats.signal_stats.markets_analyzed_today}</p>
              </div>
              <div>
                <p className="text-xs text-gray-400">Analyzed This Week</p>
                <p className="mt-1 font-semibold text-white">{stats.signal_stats.markets_analyzed_week}</p>
              </div>
              <div>
                <p className="text-xs text-gray-400">Trades / Day</p>
                <p className="mt-1 font-semibold text-white">
                  {stats.paper_trading.action_frequency_per_day.toFixed(2)}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-400">Open Trades</p>
                <p className="mt-1 font-semibold text-amber-400">{stats.paper_trading.open_trades}</p>
              </div>
            </div>
          </div>

          {/* Paper Trades Table */}
          <div className="overflow-hidden rounded-xl border border-gray-700 bg-gray-800">
            <div className="border-b border-gray-700 px-4 py-3">
              <h3 className="text-sm font-semibold text-white">Paper Trades</h3>
            </div>
            {trades.length === 0 ? (
              <EmptyState message="No paper trades yet." icon={FlaskConical} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700 text-left">
                      <th className="px-4 py-3 font-medium text-gray-400">Market</th>
                      <th className="px-4 py-3 font-medium text-gray-400">Entry</th>
                      <th className="px-4 py-3 font-medium text-gray-400">Predicted</th>
                      <th className="px-4 py-3 font-medium text-gray-400">Edge</th>
                      <th className="px-4 py-3 font-medium text-gray-400">Size</th>
                      <th className="px-4 py-3 font-medium text-gray-400">Status</th>
                      <th className="px-4 py-3 font-medium text-gray-400">P&L</th>
                      <th className="px-4 py-3 font-medium text-gray-400">Date</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-700/50">
                    {trades.map((trade) => (
                      <tr key={trade.id} className="transition-colors hover:bg-gray-700/30">
                        <td className="max-w-xs px-4 py-3">
                          <p className="line-clamp-1 text-gray-200">
                            {trade.market_title ?? `Market #${trade.market_id}`}
                          </p>
                          {trade.is_short_term && (
                            <span className="mt-0.5 text-xs text-amber-500">short-term</span>
                          )}
                        </td>
                        <td className="px-4 py-3 font-mono text-gray-300">
                          {(trade.entry_price * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-3 font-mono text-gray-300">
                          {(trade.predicted_prob * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-3 font-mono">
                          <span className="text-sky-400">
                            +{(trade.edge * 100).toFixed(1)}%
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-gray-300">
                          ${trade.size_usd.toFixed(2)}
                        </td>
                        <td className="px-4 py-3">{statusBadge(trade.status)}</td>
                        <td className="px-4 py-3 font-mono">
                          {trade.pnl !== null ? (
                            <span
                              className={trade.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}
                            >
                              {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}
                            </span>
                          ) : (
                            <span className="text-gray-600">—</span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-gray-500">
                          {formatDate(trade.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

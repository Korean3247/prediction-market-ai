'use client'

import { useEffect, useState } from 'react'
import { BarChart2, RefreshCw, TrendingUp, Target, DollarSign } from 'lucide-react'
import LoadingSpinner from '@/components/LoadingSpinner'
import { fetchBacktest, type BacktestData } from '@/lib/api'

function formatPct(val: number) {
  return `${(val * 100).toFixed(1)}%`
}

function formatPnl(val: number) {
  const sign = val >= 0 ? '+' : ''
  return `${sign}$${val.toFixed(2)}`
}

/** Simple ASCII-style bar using filled blocks */
function AsciiBar({ value, max, width = 20 }: { value: number; max: number; width?: number }) {
  const filled = max > 0 ? Math.round((value / max) * width) : 0
  const bar = '█'.repeat(Math.max(0, filled)) + '░'.repeat(Math.max(0, width - filled))
  return <span className="font-mono text-sky-400">{bar}</span>
}

export default function BacktestPage() {
  const [data, setData] = useState<BacktestData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    try {
      setLoading(true)
      setError(null)
      const result = await fetchBacktest()
      setData(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load backtest data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Backtesting</h1>
          <p className="mt-1 text-sm text-gray-400">
            Historical prediction accuracy, calibration, and PnL performance
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg bg-gray-700 px-4 py-2 text-sm font-medium text-gray-300 transition-colors hover:bg-gray-600 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4">
          <p className="text-sm text-rose-400">
            <span className="font-semibold">Error:</span> {error}
          </p>
          <p className="mt-1 text-xs text-rose-500">
            Make sure the backend is running at http://localhost:8000
          </p>
        </div>
      )}

      {loading && !error && <LoadingSpinner size="lg" />}

      {data && !loading && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl border border-gray-700 bg-gray-800 p-5">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-sky-500/10">
                  <BarChart2 className="h-5 w-5 text-sky-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-400">Total Outcomes</p>
                  <p className="text-xl font-bold text-white">{data.total_outcomes}</p>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-gray-700 bg-gray-800 p-5">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10">
                  <Target className="h-5 w-5 text-purple-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-400">Brier Score</p>
                  <p className="text-xl font-bold text-white">
                    {data.brier_score !== null ? data.brier_score.toFixed(4) : 'N/A'}
                  </p>
                  <p className="text-xs text-gray-500">Lower is better (0 = perfect)</p>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-gray-700 bg-gray-800 p-5">
              <div className="flex items-center gap-3">
                <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${data.total_pnl >= 0 ? 'bg-emerald-500/10' : 'bg-rose-500/10'}`}>
                  <DollarSign className={`h-5 w-5 ${data.total_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`} />
                </div>
                <div>
                  <p className="text-xs text-gray-400">Total PnL</p>
                  <p className={`text-xl font-bold ${data.total_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {formatPnl(data.total_pnl)}
                  </p>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-gray-700 bg-gray-800 p-5">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-500/10">
                  <TrendingUp className="h-5 w-5 text-amber-400" />
                </div>
                <div>
                  <p className="text-xs text-gray-400">Win Rate</p>
                  <p className="text-xl font-bold text-white">
                    {data.records.length > 0
                      ? formatPct(data.records.filter((r) => r.pnl > 0).length / data.records.length)
                      : 'N/A'}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Cumulative PnL Table */}
          <div className="rounded-xl border border-gray-700 bg-gray-800 p-6">
            <h2 className="mb-4 text-base font-semibold text-white">Cumulative PnL Over Time</h2>
            {data.records.length === 0 ? (
              <p className="text-sm text-gray-500">No resolved outcomes yet. Cumulative PnL will appear here once markets resolve.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700 text-left text-xs text-gray-400">
                      <th className="pb-2 pr-4">Date</th>
                      <th className="pb-2 pr-4">Market</th>
                      <th className="pb-2 pr-4">Predicted</th>
                      <th className="pb-2 pr-4">Actual</th>
                      <th className="pb-2 pr-4">PnL</th>
                      <th className="pb-2">Cumulative PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.records.map((record, idx) => (
                      <tr key={idx} className="border-b border-gray-700/50">
                        <td className="py-2 pr-4 text-gray-400 text-xs">
                          {record.date ? new Date(record.date).toLocaleDateString() : '—'}
                        </td>
                        <td className="py-2 pr-4 max-w-xs truncate text-gray-300">
                          {record.market_title}
                        </td>
                        <td className="py-2 pr-4 text-gray-300">
                          {formatPct(record.predicted_prob)}
                        </td>
                        <td className="py-2 pr-4">
                          <span
                            className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                              record.actual_result
                                ? 'bg-emerald-500/20 text-emerald-400'
                                : 'bg-rose-500/20 text-rose-400'
                            }`}
                          >
                            {record.actual_result ? 'YES' : 'NO'}
                          </span>
                        </td>
                        <td className={`py-2 pr-4 font-medium ${record.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {formatPnl(record.pnl)}
                        </td>
                        <td className={`py-2 font-medium ${record.cumulative_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {formatPnl(record.cumulative_pnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Calibration Table */}
          <div className="rounded-xl border border-gray-700 bg-gray-800 p-6">
            <h2 className="mb-1 text-base font-semibold text-white">Prediction Calibration</h2>
            <p className="mb-4 text-xs text-gray-500">
              A well-calibrated model shows ~50% actual YES rate when predicting 50%, etc.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-700 text-left text-xs text-gray-400">
                    <th className="pb-2 pr-4">Predicted Range</th>
                    <th className="pb-2 pr-4">Count</th>
                    <th className="pb-2 pr-4">Actual YES Rate</th>
                    <th className="pb-2">Bar</th>
                  </tr>
                </thead>
                <tbody>
                  {data.calibration_table.map((bucket) => (
                    <tr key={bucket.predicted_range} className="border-b border-gray-700/50">
                      <td className="py-2 pr-4 font-mono text-gray-300">{bucket.predicted_range}</td>
                      <td className="py-2 pr-4 text-gray-400">{bucket.count}</td>
                      <td className="py-2 pr-4 text-gray-300">
                        {bucket.actual_yes_rate !== null
                          ? formatPct(bucket.actual_yes_rate)
                          : <span className="text-gray-600">—</span>}
                      </td>
                      <td className="py-2">
                        {bucket.actual_yes_rate !== null ? (
                          <AsciiBar value={bucket.actual_yes_rate} max={1} width={20} />
                        ) : (
                          <span className="font-mono text-gray-700">{'░'.repeat(20)}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

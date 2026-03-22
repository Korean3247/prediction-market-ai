'use client'

import { useEffect, useState } from 'react'
import { AlertCircle, BarChart3, Plus, X } from 'lucide-react'
import LoadingSpinner from '@/components/LoadingSpinner'
import EmptyState from '@/components/EmptyState'
import { fetchOutcomes, recordOutcome, type Outcome } from '@/lib/api'

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  })
}

interface RecordModalProps {
  onClose: () => void
  onSave: (marketId: string, actualResult: boolean, pnl: number) => Promise<void>
}

function RecordModal({ onClose, onSave }: RecordModalProps) {
  const [marketId, setMarketId] = useState('')
  const [actualResult, setActualResult] = useState<boolean>(true)
  const [pnl, setPnl] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!marketId.trim()) {
      setErr('Market ID is required')
      return
    }
    const pnlValue = parseFloat(pnl)
    if (isNaN(pnlValue)) {
      setErr('PnL must be a valid number')
      return
    }
    try {
      setSaving(true)
      setErr(null)
      await onSave(marketId.trim(), actualResult, pnlValue)
      onClose()
    } catch (error) {
      setErr(error instanceof Error ? error.message : 'Failed to record outcome')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-gray-700 bg-gray-800 p-6 shadow-2xl">
        <div className="mb-6 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Record Outcome</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-gray-500 hover:bg-gray-700 hover:text-white transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-300">
              Market ID
            </label>
            <input
              type="text"
              value={marketId}
              onChange={(e) => setMarketId(e.target.value)}
              placeholder="e.g. market-abc-123"
              className="w-full rounded-lg border border-gray-600 bg-gray-700 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-sky-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-300">
              Actual Result
            </label>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setActualResult(true)}
                className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                  actualResult
                    ? 'bg-emerald-600 text-white'
                    : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                }`}
              >
                Win (Yes)
              </button>
              <button
                type="button"
                onClick={() => setActualResult(false)}
                className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                  !actualResult
                    ? 'bg-rose-600 text-white'
                    : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                }`}
              >
                Loss (No)
              </button>
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-300">
              PnL ($)
            </label>
            <input
              type="number"
              step="0.01"
              value={pnl}
              onChange={(e) => setPnl(e.target.value)}
              placeholder="e.g. 12.50 or -5.00"
              className="w-full rounded-lg border border-gray-600 bg-gray-700 px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-sky-500 focus:outline-none"
            />
          </div>

          {err && (
            <p className="text-sm text-rose-400">{err}</p>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 rounded-lg bg-gray-700 px-4 py-2.5 text-sm font-medium text-gray-300 hover:bg-gray-600 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 rounded-lg bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-sky-500 disabled:opacity-60 transition-colors"
            >
              {saving ? 'Saving...' : 'Record'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function OutcomesPage() {
  const [outcomes, setOutcomes] = useState<Outcome[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)

  const loadOutcomes = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await fetchOutcomes(50)
      setOutcomes(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot connect to backend')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadOutcomes()
  }, [])

  const handleSaveOutcome = async (
    marketId: string,
    actualResult: boolean,
    pnl: number
  ) => {
    await recordOutcome(marketId, { actual_result: actualResult, pnl })
    await loadOutcomes()
  }

  // Summary stats
  const totalPnl = outcomes.reduce((sum, o) => sum + o.pnl, 0)
  const wins = outcomes.filter((o) => o.actual_result).length
  const losses = outcomes.filter((o) => !o.actual_result).length

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Outcomes</h1>
          <p className="mt-1 text-sm text-gray-400">
            Track your prediction results and PnL
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-sky-500"
        >
          <Plus className="h-4 w-4" />
          Record Outcome
        </button>
      </div>

      {/* Summary Bar */}
      {!loading && !error && outcomes.length > 0 && (
        <div className="grid grid-cols-3 gap-4">
          <div className="rounded-xl border border-gray-700 bg-gray-800 p-4 text-center">
            <p className="text-xs text-gray-400">Total PnL</p>
            <p
              className={`mt-1 text-2xl font-bold ${
                totalPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
            </p>
          </div>
          <div className="rounded-xl border border-emerald-700/30 bg-emerald-900/20 p-4 text-center">
            <p className="text-xs text-gray-400">Wins</p>
            <p className="mt-1 text-2xl font-bold text-emerald-400">{wins}</p>
          </div>
          <div className="rounded-xl border border-rose-700/30 bg-rose-900/20 p-4 text-center">
            <p className="text-xs text-gray-400">Losses</p>
            <p className="mt-1 text-2xl font-bold text-rose-400">{losses}</p>
          </div>
        </div>
      )}

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

      {/* Table */}
      {!loading && !error && (
        <div className="overflow-hidden rounded-xl border border-gray-700 bg-gray-800">
          {outcomes.length === 0 ? (
            <EmptyState
              message="No outcomes recorded yet. Record your first result above."
              icon={BarChart3}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-700 text-left">
                    <th className="px-4 py-3 font-medium text-gray-400">Market ID</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Result</th>
                    <th className="px-4 py-3 font-medium text-gray-400">PnL</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Notes</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Tags</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {outcomes.map((outcome) => (
                    <tr
                      key={outcome.id}
                      className="transition-colors hover:bg-gray-700/30"
                    >
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs text-gray-400">
                          #{outcome.market_id}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                            outcome.actual_result
                              ? 'bg-emerald-500/20 text-emerald-400'
                              : 'bg-rose-500/20 text-rose-400'
                          }`}
                        >
                          {outcome.actual_result ? 'Win' : 'Loss'}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono">
                        <span
                          className={
                            outcome.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'
                          }
                        >
                          {outcome.pnl >= 0 ? '+' : ''}${outcome.pnl.toFixed(2)}
                        </span>
                      </td>
                      <td className="max-w-xs px-4 py-3">
                        <p className="line-clamp-2 text-gray-400">
                          {outcome.review_notes || '—'}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        {outcome.failure_tags && outcome.failure_tags.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {outcome.failure_tags.map((tag) => (
                              <span
                                key={tag}
                                className="rounded bg-gray-700 px-1.5 py-0.5 text-xs text-gray-400"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-gray-600">—</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-gray-500">
                        {formatDate(outcome.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Record Outcome Modal */}
      {showModal && (
        <RecordModal
          onClose={() => setShowModal(false)}
          onSave={handleSaveOutcome}
        />
      )}
    </div>
  )
}

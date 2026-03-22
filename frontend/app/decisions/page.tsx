'use client'

import { useEffect, useState, useCallback } from 'react'
import { AlertCircle, Target } from 'lucide-react'
import Badge from '@/components/Badge'
import LoadingSpinner from '@/components/LoadingSpinner'
import EmptyState from '@/components/EmptyState'
import { fetchDecisions, type RiskDecision } from '@/lib/api'

type ActionFilter = 'all' | 'buy' | 'skip' | 'observe'

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const tabs: { label: string; value: ActionFilter }[] = [
  { label: 'All', value: 'all' },
  { label: 'Buy', value: 'buy' },
  { label: 'Skip', value: 'skip' },
  { label: 'Observe', value: 'observe' }
]

const tabActiveClass: Record<ActionFilter, string> = {
  all: 'bg-gray-600 text-white',
  buy: 'bg-emerald-600 text-white',
  skip: 'bg-rose-600 text-white',
  observe: 'bg-amber-600 text-white'
}

export default function DecisionsPage() {
  const [decisions, setDecisions] = useState<RiskDecision[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<ActionFilter>('all')

  const loadDecisions = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await fetchDecisions({
        action: filter === 'all' ? undefined : filter,
        limit: 50
      })
      // Sort by date desc
      const sorted = [...data].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      )
      setDecisions(sorted)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot connect to backend')
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    loadDecisions()
  }, [loadDecisions])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Decisions</h1>
        <p className="mt-1 text-sm text-gray-400">
          Risk decisions made by the AI for each market
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
        {tabs.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setFilter(tab.value)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              filter === tab.value
                ? tabActiveClass[tab.value]
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white'
            }`}
          >
            {tab.label}
          </button>
        ))}
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

      {/* Table */}
      {!loading && !error && (
        <div className="overflow-hidden rounded-xl border border-gray-700 bg-gray-800">
          {decisions.length === 0 ? (
            <EmptyState
              message={`No ${filter === 'all' ? '' : filter + ' '}decisions found.`}
              icon={Target}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-700 text-left">
                    <th className="px-4 py-3 font-medium text-gray-400">Market ID</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Action</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Rec. Size</th>
                    <th className="px-4 py-3 font-medium text-gray-400">EV</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Risk Score</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Reason</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {decisions.map((decision) => (
                    <tr
                      key={decision.id}
                      className="transition-colors hover:bg-gray-700/30"
                    >
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs text-gray-400">
                          #{decision.market_id}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={decision.action} label={decision.action.toUpperCase()} />
                      </td>
                      <td className="px-4 py-3 font-mono text-gray-200">
                        ${decision.recommended_size.toFixed(2)}
                      </td>
                      <td className="px-4 py-3 font-mono">
                        <span
                          className={
                            decision.ev >= 0 ? 'text-emerald-400' : 'text-rose-400'
                          }
                        >
                          {decision.ev >= 0 ? '+' : ''}{(decision.ev * 100).toFixed(2)}%
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-gray-700">
                            <div
                              className={`h-full rounded-full ${
                                decision.risk_score > 0.7
                                  ? 'bg-rose-500'
                                  : decision.risk_score > 0.4
                                  ? 'bg-amber-500'
                                  : 'bg-emerald-500'
                              }`}
                              style={{ width: `${decision.risk_score * 100}%` }}
                            />
                          </div>
                          <span className="text-xs text-gray-400">
                            {(decision.risk_score * 100).toFixed(0)}%
                          </span>
                        </div>
                      </td>
                      <td className="max-w-xs px-4 py-3">
                        <p className="line-clamp-2 text-gray-300">{decision.reason}</p>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-gray-500">
                        {formatDate(decision.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import {
  Scan,
  ExternalLink,
  Eye,
  ChevronDown,
  TrendingUp,
  AlertCircle
} from 'lucide-react'
import Badge from '@/components/Badge'
import LoadingSpinner from '@/components/LoadingSpinner'
import EmptyState from '@/components/EmptyState'
import { fetchMarkets, triggerScan, type Market } from '@/lib/api'

function formatCurrency(value: number): string {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`
  return `$${value.toFixed(0)}`
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function PriorityBar({ score }: { score: number }) {
  const pct = Math.min(Math.max(score, 0), 100)
  const color =
    pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-gray-600'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-gray-700">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400">{score.toFixed(0)}</span>
    </div>
  )
}

export default function MarketsPage() {
  const router = useRouter()
  const [markets, setMarkets] = useState<Market[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [platform, setPlatform] = useState('')
  const [status, setStatus] = useState('')
  const [scanLoading, setScanLoading] = useState(false)
  const [scanMessage, setScanMessage] = useState<string | null>(null)

  const loadMarkets = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await fetchMarkets({
        platform: platform || undefined,
        status: status || undefined,
        limit: 50
      })
      setMarkets(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot connect to backend')
    } finally {
      setLoading(false)
    }
  }, [platform, status])

  useEffect(() => {
    loadMarkets()
  }, [loadMarkets])

  const handleScan = async () => {
    try {
      setScanLoading(true)
      setScanMessage(null)
      const result = await triggerScan()
      setScanMessage(`Scan complete: ${result.markets_found} markets found`)
      await loadMarkets()
    } catch (err) {
      setScanMessage(`Scan failed: ${err instanceof Error ? err.message : 'Error'}`)
    } finally {
      setScanLoading(false)
      setTimeout(() => setScanMessage(null), 4000)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Markets</h1>
          <p className="mt-1 text-sm text-gray-400">
            {markets.length} market{markets.length !== 1 ? 's' : ''} found
          </p>
        </div>

        <button
          onClick={handleScan}
          disabled={scanLoading}
          className="flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-sky-500 disabled:opacity-60"
        >
          {scanLoading ? (
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
          ) : (
            <Scan className="h-4 w-4" />
          )}
          Scan Now
        </button>
      </div>

      {/* Scan message toast */}
      {scanMessage && (
        <div
          className={`rounded-lg p-3 text-sm ${
            scanMessage.startsWith('Scan failed')
              ? 'border border-rose-500/30 bg-rose-500/10 text-rose-400'
              : 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
          }`}
        >
          {scanMessage}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="relative">
          <select
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
            className="appearance-none rounded-lg border border-gray-700 bg-gray-800 py-2 pl-3 pr-8 text-sm text-gray-300 focus:border-sky-500 focus:outline-none"
          >
            <option value="">All Platforms</option>
            <option value="polymarket">Polymarket</option>
            <option value="manifold">Manifold</option>
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-2.5 h-4 w-4 text-gray-500" />
        </div>

        <div className="relative">
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="appearance-none rounded-lg border border-gray-700 bg-gray-800 py-2 pl-3 pr-8 text-sm text-gray-300 focus:border-sky-500 focus:outline-none"
          >
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="resolved">Resolved</option>
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-2.5 h-4 w-4 text-gray-500" />
        </div>
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
          {markets.length === 0 ? (
            <EmptyState
              message="No markets found. Try scanning for new markets."
              icon={TrendingUp}
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-700 text-left">
                    <th className="px-4 py-3 font-medium text-gray-400">Title</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Platform</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Price</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Liquidity</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Vol 24h</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Priority</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Resolve</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Status</th>
                    <th className="px-4 py-3 font-medium text-gray-400">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {markets.map((market) => (
                    <tr
                      key={market.id}
                      className="transition-colors hover:bg-gray-700/30"
                    >
                      <td className="max-w-xs px-4 py-3">
                        <div className="flex items-start gap-2">
                          <p className="line-clamp-2 font-medium text-white">
                            {market.title}
                          </p>
                          {market.url && (
                            <a
                              href={market.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="mt-0.5 flex-shrink-0 text-gray-500 hover:text-sky-400"
                            >
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          )}
                        </div>
                        {market.category && (
                          <p className="mt-0.5 text-xs text-gray-500">{market.category}</p>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-300 capitalize">
                        {market.platform}
                      </td>
                      <td className="px-4 py-3 font-mono text-gray-200">
                        {(market.current_price * 100).toFixed(1)}%
                      </td>
                      <td className="px-4 py-3 text-gray-300">
                        {formatCurrency(market.liquidity)}
                      </td>
                      <td className="px-4 py-3 text-gray-300">
                        {formatCurrency(market.volume_24h)}
                      </td>
                      <td className="px-4 py-3">
                        <PriorityBar score={market.priority_score} />
                      </td>
                      <td className="px-4 py-3 text-gray-400">
                        {formatDate(market.resolve_time)}
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant={market.status === 'active' ? 'active' : 'resolved'}
                          label={market.status}
                        />
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => router.push(`/markets/${market.market_id}`)}
                          className="flex items-center gap-1 rounded-lg bg-gray-700 px-3 py-1.5 text-xs font-medium text-gray-300 transition-colors hover:bg-gray-600"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          View
                        </button>
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

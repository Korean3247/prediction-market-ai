'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import {
  ArrowLeft,
  ExternalLink,
  FlaskConical,
  Cpu,
  RefreshCw,
  AlertCircle,
  Calendar,
  DollarSign,
  Activity,
  Layers
} from 'lucide-react'
import Badge from '@/components/Badge'
import LoadingSpinner from '@/components/LoadingSpinner'
import {
  fetchMarketDetail,
  triggerResearch,
  triggerPredict,
  type MarketDetail,
  type ResearchReport,
  type Prediction,
  type RiskDecision
} from '@/lib/api'

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function ScoreBar({
  label,
  value,
  max = 1,
  color = 'sky'
}: {
  label: string
  value: number
  max?: number
  color?: string
}) {
  const pct = Math.min(Math.max((value / max) * 100, 0), 100)
  const colorMap: Record<string, string> = {
    sky: 'bg-sky-500',
    emerald: 'bg-emerald-500',
    amber: 'bg-amber-500',
    rose: 'bg-rose-500',
    violet: 'bg-violet-500'
  }
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-gray-400">
        <span>{label}</span>
        <span className="font-mono text-gray-300">{(pct).toFixed(1)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-gray-700">
        <div
          className={`h-full rounded-full transition-all ${colorMap[color] || 'bg-sky-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-gray-700/50 last:border-0">
      <span className="text-sm text-gray-400 flex-shrink-0">{label}</span>
      <span className="text-sm text-gray-200 text-right">{value}</span>
    </div>
  )
}

function ResearchCard({ research }: { research: ResearchReport }) {
  return (
    <div className="rounded-xl border border-gray-700 bg-gray-800 p-5 space-y-4">
      <h3 className="text-base font-semibold text-white flex items-center gap-2">
        <FlaskConical className="h-4 w-4 text-sky-400" />
        Research Report
      </h3>
      <div className="space-y-3">
        <ScoreBar label="Sentiment Score" value={(research.sentiment_score + 1) / 2} color="emerald" />
        <ScoreBar label="Credibility Score" value={research.credibility_score} color="sky" />
      </div>
      <InfoRow label="Sources" value={research.source_count} />
      {research.summary && (
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-500">Summary</p>
          <p className="text-sm text-gray-300 leading-relaxed">{research.summary}</p>
        </div>
      )}
      {research.keywords.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-500">Keywords</p>
          <div className="flex flex-wrap gap-1.5">
            {research.keywords.map((kw) => (
              <span
                key={kw}
                className="rounded-md bg-gray-700 px-2 py-0.5 text-xs text-gray-300"
              >
                {kw}
              </span>
            ))}
          </div>
        </div>
      )}
      <p className="text-xs text-gray-600">Generated {formatDate(research.created_at)}</p>
    </div>
  )
}

function PredictionCard({ prediction }: { prediction: Prediction }) {
  const edge = prediction.edge
  return (
    <div className="rounded-xl border border-gray-700 bg-gray-800 p-5 space-y-4">
      <h3 className="text-base font-semibold text-white flex items-center gap-2">
        <Cpu className="h-4 w-4 text-violet-400" />
        AI Prediction
      </h3>
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg bg-gray-700/50 p-3 text-center">
          <p className="text-xs text-gray-400">Predicted Prob</p>
          <p className="mt-1 text-2xl font-bold text-sky-400">
            {(prediction.predicted_probability * 100).toFixed(1)}%
          </p>
        </div>
        <div className="rounded-lg bg-gray-700/50 p-3 text-center">
          <p className="text-xs text-gray-400">Implied Prob</p>
          <p className="mt-1 text-2xl font-bold text-gray-300">
            {(prediction.implied_probability * 100).toFixed(1)}%
          </p>
        </div>
      </div>
      <div className="flex items-center justify-between rounded-lg bg-gray-700/30 px-4 py-3">
        <span className="text-sm text-gray-400">Edge</span>
        <span
          className={`text-lg font-bold ${
            edge >= 0 ? 'text-emerald-400' : 'text-rose-400'
          }`}
        >
          {edge >= 0 ? '+' : ''}{(edge * 100).toFixed(1)}%
        </span>
      </div>
      <ScoreBar label="Confidence" value={prediction.confidence_score} color="violet" />
      <InfoRow label="Model" value={<span className="font-mono text-xs">{prediction.model_version}</span>} />
      {prediction.reasoning && (
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-500">Reasoning</p>
          <p className="text-sm text-gray-300 leading-relaxed">{prediction.reasoning}</p>
        </div>
      )}
      <p className="text-xs text-gray-600">Generated {formatDate(prediction.created_at)}</p>
    </div>
  )
}

function DecisionCard({ decision }: { decision: RiskDecision }) {
  return (
    <div className="rounded-xl border border-gray-700 bg-gray-800 p-5 space-y-4">
      <h3 className="text-base font-semibold text-white flex items-center gap-2">
        <Activity className="h-4 w-4 text-amber-400" />
        Risk Decision
      </h3>
      <div className="flex items-center justify-center py-2">
        <Badge
          variant={decision.action}
          label={decision.action.toUpperCase()}
        />
      </div>
      <div className="space-y-0">
        <InfoRow
          label="Recommended Size"
          value={`$${decision.recommended_size.toFixed(2)}`}
        />
        <InfoRow
          label="Expected Value"
          value={
            <span className={decision.ev >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
              {decision.ev >= 0 ? '+' : ''}{(decision.ev * 100).toFixed(2)}%
            </span>
          }
        />
        <InfoRow
          label="Risk Score"
          value={
            <span
              className={
                decision.risk_score > 0.7
                  ? 'text-rose-400'
                  : decision.risk_score > 0.4
                  ? 'text-amber-400'
                  : 'text-emerald-400'
              }
            >
              {(decision.risk_score * 100).toFixed(0)}%
            </span>
          }
        />
      </div>
      {decision.reason && (
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-gray-500">Reason</p>
          <p className="text-sm text-gray-300 leading-relaxed">{decision.reason}</p>
        </div>
      )}
      <p className="text-xs text-gray-600">Decided {formatDate(decision.created_at)}</p>
    </div>
  )
}

export default function MarketDetailPage() {
  const params = useParams()
  const router = useRouter()
  const id = params.id as string

  const [detail, setDetail] = useState<MarketDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [researchLoading, setResearchLoading] = useState(false)
  const [predictLoading, setPredictLoading] = useState(false)
  const [actionMsg, setActionMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(
    null
  )

  const loadDetail = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await fetchMarketDetail(id)
      setDetail(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot connect to backend')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDetail()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const showMsg = (type: 'success' | 'error', text: string) => {
    setActionMsg({ type, text })
    setTimeout(() => setActionMsg(null), 4000)
  }

  const handleResearch = async () => {
    try {
      setResearchLoading(true)
      await triggerResearch(id)
      showMsg('success', 'Research completed successfully')
      await loadDetail()
    } catch (err) {
      showMsg('error', `Research failed: ${err instanceof Error ? err.message : 'Error'}`)
    } finally {
      setResearchLoading(false)
    }
  }

  const handlePredict = async () => {
    try {
      setPredictLoading(true)
      await triggerPredict(id)
      showMsg('success', 'Prediction generated successfully')
      await loadDetail()
    } catch (err) {
      showMsg('error', `Prediction failed: ${err instanceof Error ? err.message : 'Error'}`)
    } finally {
      setPredictLoading(false)
    }
  }

  if (loading) return <LoadingSpinner size="lg" />

  if (error) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => router.push('/markets')}
          className="flex items-center gap-2 text-sm text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="h-4 w-4" /> Markets
        </button>
        <div className="flex items-start gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4">
          <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-rose-400" />
          <div>
            <p className="text-sm font-medium text-rose-400">Failed to load market</p>
            <p className="mt-0.5 text-xs text-rose-500">{error}</p>
          </div>
        </div>
      </div>
    )
  }

  if (!detail) return null
  const { market, research, prediction, decision } = detail

  return (
    <div className="space-y-6">
      {/* Back button */}
      <button
        onClick={() => router.push('/markets')}
        className="flex items-center gap-2 text-sm text-gray-400 hover:text-white transition-colors"
      >
        <ArrowLeft className="h-4 w-4" /> Markets
      </button>

      {/* Title row */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Badge
            variant={market.status === 'active' ? 'active' : 'resolved'}
            label={market.status}
          />
          <span className="rounded-md bg-gray-700 px-2 py-0.5 text-xs text-gray-300 capitalize">
            {market.platform}
          </span>
          {market.category && (
            <span className="text-xs text-gray-500">{market.category}</span>
          )}
        </div>
        <h1 className="text-xl font-bold text-white leading-snug">{market.title}</h1>
        {market.url && (
          <a
            href={market.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-sky-400 hover:text-sky-300"
          >
            <ExternalLink className="h-3.5 w-3.5" /> View on {market.platform}
          </a>
        )}
      </div>

      {/* Action message */}
      {actionMsg && (
        <div
          className={`rounded-lg p-3 text-sm ${
            actionMsg.type === 'error'
              ? 'border border-rose-500/30 bg-rose-500/10 text-rose-400'
              : 'border border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
          }`}
        >
          {actionMsg.text}
        </div>
      )}

      {/* Two-column layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* LEFT: Market Info + Actions */}
        <div className="space-y-6">
          {/* Market Info Card */}
          <div className="rounded-xl border border-gray-700 bg-gray-800 p-5">
            <h3 className="mb-4 text-base font-semibold text-white flex items-center gap-2">
              <Layers className="h-4 w-4 text-gray-400" />
              Market Info
            </h3>
            <div>
              <InfoRow
                label="Current Price"
                value={
                  <span className="font-mono text-sky-400">
                    {(market.current_price * 100).toFixed(2)}%
                  </span>
                }
              />
              <InfoRow
                label="Liquidity"
                value={
                  <span className="font-mono">
                    ${market.liquidity.toLocaleString()}
                  </span>
                }
              />
              <InfoRow
                label="Volume 24h"
                value={
                  <span className="font-mono">
                    ${market.volume_24h.toLocaleString()}
                  </span>
                }
              />
              <InfoRow
                label="Spread"
                value={<span className="font-mono">{(market.spread * 100).toFixed(2)}%</span>}
              />
              <InfoRow
                label="Priority Score"
                value={
                  <span className="font-mono">
                    {market.priority_score.toFixed(1)}
                  </span>
                }
              />
              {market.resolve_time && (
                <InfoRow
                  label="Resolve Time"
                  value={
                    <span className="flex items-center gap-1.5">
                      <Calendar className="h-3.5 w-3.5 text-gray-500" />
                      {formatDate(market.resolve_time)}
                    </span>
                  }
                />
              )}
              <InfoRow label="Last Updated" value={formatDate(market.updated_at)} />
            </div>
          </div>

          {/* Action Buttons */}
          <div className="rounded-xl border border-gray-700 bg-gray-800 p-5 space-y-3">
            <h3 className="text-base font-semibold text-white">Actions</h3>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={handleResearch}
                disabled={researchLoading}
                className="flex items-center justify-center gap-2 rounded-lg bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-sky-500 disabled:opacity-60"
              >
                {researchLoading ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                ) : (
                  <FlaskConical className="h-4 w-4" />
                )}
                Research
              </button>
              <button
                onClick={handlePredict}
                disabled={predictLoading || !research}
                title={!research ? 'Run research first' : undefined}
                className="flex items-center justify-center gap-2 rounded-lg bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {predictLoading ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                ) : (
                  <Cpu className="h-4 w-4" />
                )}
                Predict
              </button>
            </div>
            <button
              onClick={loadDetail}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-gray-700 px-4 py-2 text-sm font-medium text-gray-300 transition-colors hover:bg-gray-600"
            >
              <RefreshCw className="h-4 w-4" />
              Refresh Data
            </button>
          </div>
        </div>

        {/* RIGHT: Research, Prediction, Decision */}
        <div className="space-y-6">
          {!research && !prediction && !decision && (
            <div className="rounded-xl border border-dashed border-gray-700 bg-gray-800/50 p-8 text-center">
              <DollarSign className="mx-auto mb-3 h-10 w-10 text-gray-600" />
              <p className="text-sm text-gray-400">
                No analysis yet. Click Research to start.
              </p>
            </div>
          )}

          {research && <ResearchCard research={research} />}
          {prediction && <PredictionCard prediction={prediction} />}
          {decision && <DecisionCard decision={decision} />}
        </div>
      </div>
    </div>
  )
}

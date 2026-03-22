const API_BASE = '/api/v1'

export interface Market {
  id: number
  market_id: string
  title: string
  category: string
  platform: string
  current_price: number
  liquidity: number
  volume_24h: number
  spread: number
  resolve_time: string | null
  priority_score: number
  status: string
  url: string | null
  created_at: string
  updated_at: string
}

export interface ResearchReport {
  id: number
  market_id: number
  summary: string
  sentiment_score: number
  source_count: number
  credibility_score: number
  keywords: string[]
  created_at: string
}

export interface Prediction {
  id: number
  market_id: number
  predicted_probability: number
  implied_probability: number
  edge: number
  confidence_score: number
  model_version: string
  reasoning: string | null
  created_at: string
}

export interface RiskDecision {
  id: number
  market_id: number
  action: 'buy' | 'skip' | 'observe'
  recommended_size: number
  ev: number
  risk_score: number
  reason: string
  created_at: string
}

export interface Outcome {
  id: number
  market_id: number
  actual_result: boolean
  pnl: number
  review_notes: string | null
  failure_tags: string[]
  created_at: string
}

export interface Stats {
  total_markets: number
  active_markets: number
  total_predictions: number
  win_rate: number
  total_pnl: number
  avg_confidence: number
  decisions_by_action: Record<string, number>
}

export interface MarketDetail {
  market: Market
  research: ResearchReport | null
  prediction: Prediction | null
  decision: RiskDecision | null
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers
    }
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API error ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export async function fetchStats(): Promise<Stats> {
  return apiFetch<Stats>('/stats')
}

export async function fetchMarkets(params?: {
  platform?: string
  status?: string
  limit?: number
}): Promise<Market[]> {
  const query = new URLSearchParams()
  if (params?.platform) query.set('platform', params.platform)
  if (params?.status) query.set('status', params.status)
  if (params?.limit !== undefined) query.set('limit', String(params.limit))
  const qs = query.toString()
  return apiFetch<Market[]>(`/markets${qs ? `?${qs}` : ''}`)
}

export async function fetchMarketDetail(id: string): Promise<MarketDetail> {
  const raw = await apiFetch<any>(`/markets/${id}`)
  // Backend returns a flat object; normalize into nested MarketDetail shape
  return {
    market: {
      id: raw.id,
      market_id: raw.market_id,
      title: raw.title,
      category: raw.category,
      platform: raw.platform,
      current_price: raw.current_price,
      liquidity: raw.liquidity,
      volume_24h: raw.volume_24h,
      spread: raw.spread,
      resolve_time: raw.resolve_time,
      priority_score: raw.priority_score,
      status: raw.status,
      url: raw.url,
      created_at: raw.created_at,
      updated_at: raw.updated_at,
    },
    research: raw.latest_research ?? null,
    prediction: raw.latest_prediction ?? null,
    decision: raw.latest_decision ?? null,
  }
}

export async function triggerScan(): Promise<{ status: string; markets_found: number }> {
  return apiFetch<{ status: string; markets_found: number }>('/markets/scan', {
    method: 'POST'
  })
}

export async function triggerResearch(id: string): Promise<ResearchReport> {
  return apiFetch<ResearchReport>(`/markets/${id}/research`, { method: 'POST' })
}

export async function triggerPredict(id: string): Promise<Prediction> {
  return apiFetch<Prediction>(`/markets/${id}/predict`, { method: 'POST' })
}

export async function fetchDecisions(params?: {
  action?: string
  limit?: number
}): Promise<RiskDecision[]> {
  const query = new URLSearchParams()
  if (params?.action) query.set('action', params.action)
  if (params?.limit !== undefined) query.set('limit', String(params.limit))
  const qs = query.toString()
  return apiFetch<RiskDecision[]>(`/decisions${qs ? `?${qs}` : ''}`)
}

export async function fetchOutcomes(limit?: number): Promise<Outcome[]> {
  const qs = limit !== undefined ? `?limit=${limit}` : ''
  return apiFetch<Outcome[]>(`/outcomes${qs}`)
}

export async function recordOutcome(
  marketId: string,
  data: { actual_result: boolean; pnl: number }
): Promise<Outcome> {
  return apiFetch<Outcome>(`/outcomes/${marketId}`, {
    method: 'POST',
    body: JSON.stringify(data)
  })
}

export interface BacktestRecord {
  date: string | null
  market_title: string
  market_id: string
  predicted_prob: number
  actual_result: boolean
  pnl: number
  cumulative_pnl: number
}

export interface CalibrationBucket {
  predicted_range: string
  count: number
  actual_yes_rate: number | null
}

export interface BacktestData {
  records: BacktestRecord[]
  total_outcomes: number
  brier_score: number | null
  total_pnl: number
  calibration_table: CalibrationBucket[]
}

export async function fetchBacktest(): Promise<BacktestData> {
  return apiFetch<BacktestData>('/backtest')
}

export interface PaperTrade {
  id: number
  market_id: number
  market_title?: string
  direction: string
  entry_price: number
  predicted_prob: number
  edge: number
  confidence: number
  size_usd: number
  is_short_term: boolean
  status: string
  actual_result: boolean | null
  pnl: number | null
  created_at: string
  resolved_at: string | null
}

interface SegmentStats {
  total: number
  won: number
  lost: number
  open: number
  win_rate: number
  total_pnl: number
  avg_edge: number
}

interface PaperTradingStats {
  total_trades: number
  open_trades: number
  won: number
  lost: number
  win_rate: number
  total_pnl: number
  avg_edge: number
  action_frequency_per_day: number
}

interface SignalStats {
  avg_edge: number
  buy_signal_rate: number
  paper_signal_rate: number
  markets_analyzed_today: number
  markets_analyzed_week: number
}

export interface PerformanceStats {
  short_term: SegmentStats
  long_term: SegmentStats
  paper_trading: PaperTradingStats
  signal_stats: SignalStats
}

export async function fetchPerformanceStats(): Promise<PerformanceStats> {
  return apiFetch<PerformanceStats>('/stats/performance')
}

export async function fetchPaperTrades(limit?: number): Promise<PaperTrade[]> {
  const qs = limit !== undefined ? `?limit=${limit}` : ''
  return apiFetch<PaperTrade[]>(`/paper-trades${qs}`)
}

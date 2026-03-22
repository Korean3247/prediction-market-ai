# Prediction Market AI

An end-to-end AI system that monitors 500+ prediction markets across **Polymarket, Kalshi, Metaculus, and Manifold** — autonomously identifying mispricing opportunities based on probability vs. market price discrepancies.

## Architecture

```
[Platforms] Polymarket / Kalshi / Metaculus / Manifold
      ↓  (up to 500+ markets per scan)
[ScanAgent]       Priority scoring → top markets selected
      ↓
[ResearchAgent]   News + Reddit → sentiment analysis → GPT-4o-mini summary
      ↓
[PredictionAgent] Rule-based + GPT-4o-mini + XGBoost → calibrated probability
      |             Fast path (< 6h to resolve): rule-based + XGBoost only
      ↓
[RiskAgent]       3-gate filter → dynamic Kelly sizing → BUY / OBSERVE / SKIP
      ↓
[ReviewAgent]     Outcome fetch → PnL calc → LLM failure analysis → ML retrain
      ↑
[RealtimeMonitor] Polymarket WebSocket → mispricing scanner → spread alert → fast re-analysis
[MispricingScanner] Live price vs. ML prediction + cross-platform reference → instant alert
```

## Agents

| Agent | Role |
|---|---|
| **ScanAgent** | Fetches markets from all platforms, scores by liquidity/volume/time-to-resolve, returns top candidates |
| **ResearchAgent** | Extracts keywords, pulls news & Reddit posts, blends keyword + LLM sentiment (40/60), generates GPT-4o-mini research summary |
| **PredictionAgent** | 3-layer prediction stack: rule-based adjustment → GPT-4o-mini superforecasting → XGBoost calibration (auto-retrained on 20+ resolved outcomes). Fast path for intraday markets (< 6h): skips LLM, uses rule-based + XGBoost only |
| **RiskAgent** | 3-gate filter (confidence ≥ 0.6, edge ≥ 2%, EV ≥ 1%), dynamic Kelly fraction (0.15x–0.50x by confidence tier), max position capped at 15% bankroll or 2% market liquidity |
| **ReviewAgent** | Detects expired markets, fetches actual outcomes (Gamma API for Polymarket), computes PnL, runs LLM failure analysis (7 error tags), retrains ML model |

## Tech Stack

**Backend**: Python, FastAPI, SQLAlchemy, SQLite, APScheduler, asyncio
**ML**: XGBoost, scikit-learn (9-feature calibrator, auto-retrained)
**LLM**: GPT-4o-mini (research summaries, probability forecasting, failure analysis)
**Real-time**: WebSocket (Polymarket), Telegram Bot alerts
**Frontend**: Next.js, TypeScript, Tailwind CSS (see `frontend/`)

## Features

- **Real-time mispricing scanner**: on every WebSocket tick, checks live price against two independent signals — (1) ML-predicted probability and (2) cross-platform price from Kalshi/Metaculus. Fires instant Telegram alert when gap ≥ 8%. No LLM calls — runs in milliseconds
- **Bid-ask spread detection**: flags temporarily illiquid markets (spread ≥ 10%) as potential mispricing opportunities, independent of any stored prediction
- **Cross-platform arbitrage**: Jaccard title-similarity matching (≥ 55%) flags price discrepancies across platforms; cross-platform prices also serve as independent reference signals for the mispricing scanner
- **Intraday fast path**: markets resolving within 6h skip the LLM entirely — rule-based + XGBoost only — for near-instant re-evaluation. Markets with predictions < 30 min old reuse them directly
- **Scheduled pipelines**: 6 background jobs — ultra-fast (5 min) for intraday markets down to full pipeline (2 hr) for long-horizon markets
- **Backtesting engine**: Brier score, 10-bucket calibration table, cumulative PnL curves
- **Paper trading**: Every BUY decision auto-generates a $10 virtual trade tracked through resolution
- **Telegram alerts**: mispricing signals, spread alerts, BUY signals, arbitrage opportunities, paper trade results, pipeline summaries

## Key Settings (`.env`)

| Variable | Default | Description |
|---|---|---|
| `MISPRICING_MIN_EDGE` | `0.08` | Min gap (8%) to trigger mispricing alert |
| `SPREAD_ALERT_THRESHOLD` | `0.10` | Bid-ask spread width (10%) for illiquidity alert |
| `INTRADAY_HOURS` | `24` | Hours-to-resolve threshold for intraday classification |
| `MISPRICING_ALERT_COOLDOWN_SECONDS` | `300` | Min seconds between alerts per market |

## Project Structure

```
prediction-market-ai/
├── agents/          # 5 autonomous agents (Scan, Research, Prediction, Risk, Review)
├── api/             # FastAPI REST endpoints
├── services/        # Market fetchers, LLM, alerts, sentiment analysis
├── database/        # SQLAlchemy models & migrations
├── frontend/        # Next.js dashboard (TypeScript, Tailwind CSS)
├── main.py          # Server entrypoint (API + scheduler + WebSocket)
├── cli.py           # CLI commands
├── config.py        # Pydantic settings (loaded from .env)
└── scheduler.py     # APScheduler background jobs
```

## Setup

```bash
git clone https://github.com/Korean3247/prediction-market-ai.git
cd prediction-market-ai

# Backend
pip install -r requirements.txt
cp .env.example .env
# Fill in your API keys in .env

# Frontend
cd frontend
npm install
```

**Required**: `OPENAI_API_KEY`
**Optional**: `NEWS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `KALSHI_API_KEY`, `METACULUS_API_TOKEN`

## Usage

```bash
# Start the backend (API + scheduler + WebSocket monitor)
python main.py

# Start the frontend (in a separate terminal)
cd frontend && npm run dev

# CLI commands
python cli.py scan                        # Scan all platforms
python cli.py pipeline --top-n 10        # Run full pipeline on top 10 markets
python cli.py predict <market_id>        # Predict a specific market
python cli.py decide <market_id>         # Risk decision for a market
python cli.py stats                       # System statistics
python cli.py outcomes                    # Recent resolved outcomes
```

The REST API runs at `http://localhost:8000` (`/docs` for OpenAPI spec). The frontend runs at `http://localhost:3000`.

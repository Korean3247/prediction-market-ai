# Prediction Market AI

An end-to-end AI system for analyzing prediction markets across **Polymarket, Kalshi, Metaculus, and Manifold**. A 5-agent pipeline handles everything from market scanning to probabilistic forecasting, risk management, and automated outcome review.

## Architecture

```
[Platforms] Polymarket / Kalshi / Metaculus / Manifold
      ↓  (up to 500+ markets per scan)
[ScanAgent]      Priority scoring → top markets selected
      ↓
[ResearchAgent]  News + Reddit → sentiment analysis → GPT-4o-mini summary
      ↓
[PredictionAgent] Rule-based + GPT-4o-mini + XGBoost → calibrated probability
      ↓
[RiskAgent]      3-gate filter → dynamic Kelly sizing → BUY / OBSERVE / SKIP
      ↓
[ReviewAgent]    Outcome fetch → PnL calc → LLM failure analysis → ML retrain
      ↑
[RealtimeMonitor] Polymarket WebSocket → price jump detection → fast re-analysis
```

## Agents

| Agent | Role |
|---|---|
| **ScanAgent** | Fetches markets from all platforms, scores by liquidity/volume/time-to-resolve, returns top candidates |
| **ResearchAgent** | Extracts keywords, pulls news & Reddit posts, blends keyword + LLM sentiment (40/60), generates GPT-4o-mini research summary |
| **PredictionAgent** | 3-layer prediction stack: rule-based adjustment → GPT-4o-mini superforecasting → XGBoost calibration (auto-retrained on 20+ resolved outcomes) |
| **RiskAgent** | 3-gate filter (confidence ≥ 0.6, edge ≥ 2%, EV ≥ 1%), dynamic Kelly fraction (0.15x–0.50x by confidence tier), max position capped at 15% bankroll or 2% market liquidity |
| **ReviewAgent** | Detects expired markets, fetches actual outcomes (Gamma API for Polymarket), computes PnL, runs LLM failure analysis (7 error tags), retrains ML model |

## Tech Stack

**Backend**: Python, FastAPI, SQLAlchemy, SQLite, APScheduler, asyncio
**ML**: XGBoost, scikit-learn (9-feature calibrator, auto-retrained)
**LLM**: GPT-4o-mini (research summaries, probability forecasting, failure analysis)
**Real-time**: WebSocket (Polymarket), Telegram Bot alerts
**Frontend**: Next.js, TypeScript, Tailwind CSS → [`prediction-market-frontend`](https://github.com/Korean3247/prediction-market-frontend)

## Features

- **Real-time monitoring**: Polymarket WebSocket subscribes to 50-market batches; 3% price jump triggers immediate re-analysis
- **Cross-platform arbitrage**: Jaccard title-similarity matching (≥55%) flags price discrepancies across platforms, with instant Telegram alerts
- **Scheduled pipelines**: 6 background jobs — ultra-fast (5 min) for same-day markets down to full pipeline (2 hr) for long-horizon markets
- **Backtesting engine**: Brier score, 10-bucket calibration table, cumulative PnL curves
- **Paper trading**: Every BUY decision auto-generates a $10 virtual trade tracked through resolution
- **Telegram alerts**: BUY signals, arbitrage opportunities, paper trade results, pipeline summaries

## Setup

```bash
git clone https://github.com/Korean3247/prediction-market-ai.git
cd prediction-market-ai
pip install -r requirements.txt

cp .env.example .env
# Fill in your API keys in .env
```

**Required**: `OPENAI_API_KEY`
**Optional**: `NEWS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `KALSHI_API_KEY`, `METACULUS_API_TOKEN`

## Usage

```bash
# Start the full server (API + scheduler + WebSocket monitor)
python main.py

# CLI commands
python cli.py scan                        # Scan all platforms
python cli.py pipeline --top-n 10        # Run full pipeline on top 10 markets
python cli.py predict <market_id>        # Predict a specific market
python cli.py decide <market_id>         # Risk decision for a market
python cli.py stats                       # System statistics
python cli.py outcomes                    # Recent resolved outcomes
```

The REST API runs at `http://localhost:8000`. See `/docs` for the full OpenAPI spec.

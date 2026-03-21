"""
FastAPI route definitions for the prediction market AI system.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    ActionEnum,
    Market,
    MarketStatus,
    Outcome,
    PaperTrade,
    Prediction,
    ResearchReport,
    RiskDecision,
)
from database.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic response/request schemas
# ---------------------------------------------------------------------------


class MarketResponse(BaseModel):
    id: int
    market_id: str
    title: str
    description: Optional[str]
    category: Optional[str]
    platform: str
    current_price: float
    liquidity: float
    volume_24h: float
    spread: float
    resolve_time: Optional[datetime]
    priority_score: float
    flags: Optional[Dict[str, Any]]
    status: str
    url: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MarketDetailResponse(MarketResponse):
    latest_research: Optional[Dict[str, Any]] = None
    latest_prediction: Optional[Dict[str, Any]] = None
    latest_decision: Optional[Dict[str, Any]] = None


class DecisionResponse(BaseModel):
    id: int
    market_id: int
    action: str
    recommended_size: float
    ev: float
    risk_score: float
    reason: Optional[str]
    created_at: datetime
    market_title: Optional[str] = None

    model_config = {"from_attributes": True}


class OutcomeResponse(BaseModel):
    id: int
    market_id: int
    actual_result: bool
    pnl: float
    review_notes: Optional[str]
    failure_tags: Optional[List[str]]
    created_at: datetime
    market_title: Optional[str] = None

    model_config = {"from_attributes": True}


class RecordOutcomeRequest(BaseModel):
    actual_result: bool
    pnl: float


class StatsResponse(BaseModel):
    total_markets: int
    active_markets: int
    resolved_markets: int
    total_predictions: int
    total_decisions: int
    buy_decisions: int
    total_outcomes: int
    win_count: int
    loss_count: int
    win_rate: float
    total_pnl: float
    avg_confidence: float
    decisions_by_action: Dict[str, int] = {}


# ---------------------------------------------------------------------------
# Market endpoints
# ---------------------------------------------------------------------------


@router.get("/markets", response_model=List[MarketResponse], tags=["Markets"])
def list_markets(
    platform: Optional[str] = Query(None, description="Filter by platform"),
    status: Optional[str] = Query(None, description="Filter by status (active/resolved/cancelled)"),
    min_priority: Optional[float] = Query(None, description="Minimum priority score"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> List[MarketResponse]:
    """List all markets with optional filters."""
    q = db.query(Market)

    if platform:
        q = q.filter(Market.platform == platform.lower())
    if status:
        try:
            q = q.filter(Market.status == MarketStatus(status.lower()))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    if min_priority is not None:
        q = q.filter(Market.priority_score >= min_priority)

    markets = (
        q.order_by(Market.priority_score.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return markets


@router.get("/markets/{market_id}", response_model=MarketDetailResponse, tags=["Markets"])
def get_market_detail(market_id: str, db: Session = Depends(get_db)) -> MarketDetailResponse:
    """
    Get detailed information for a single market including its latest
    research report, prediction, and risk decision.
    """
    market = db.query(Market).filter(Market.market_id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail=f"Market '{market_id}' not found.")

    # Latest research
    latest_research = (
        db.query(ResearchReport)
        .filter(ResearchReport.market_id == market.id)
        .order_by(ResearchReport.created_at.desc())
        .first()
    )

    # Latest prediction
    latest_prediction = (
        db.query(Prediction)
        .filter(Prediction.market_id == market.id)
        .order_by(Prediction.created_at.desc())
        .first()
    )

    # Latest decision
    latest_decision = (
        db.query(RiskDecision)
        .filter(RiskDecision.market_id == market.id)
        .order_by(RiskDecision.created_at.desc())
        .first()
    )

    def _research_dict(r: ResearchReport) -> Dict[str, Any]:
        return {
            "id": r.id,
            "keywords": r.keywords,
            "summary": r.summary,
            "sentiment_score": r.sentiment_score,
            "source_count": r.source_count,
            "credibility_score": r.credibility_score,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }

    def _prediction_dict(p: Prediction) -> Dict[str, Any]:
        return {
            "id": p.id,
            "predicted_probability": p.predicted_probability,
            "implied_probability": p.implied_probability,
            "edge": p.edge,
            "confidence_score": p.confidence_score,
            "reasoning": p.reasoning,
            "model_version": p.model_version,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }

    def _decision_dict(d: RiskDecision) -> Dict[str, Any]:
        return {
            "id": d.id,
            "action": d.action,
            "recommended_size": d.recommended_size,
            "ev": d.ev,
            "risk_score": d.risk_score,
            "reason": d.reason,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }

    response = MarketDetailResponse(
        **{c.name: getattr(market, c.name) for c in Market.__table__.columns},
        latest_research=_research_dict(latest_research) if latest_research else None,
        latest_prediction=_prediction_dict(latest_prediction) if latest_prediction else None,
        latest_decision=_decision_dict(latest_decision) if latest_decision else None,
    )
    return response


@router.post("/markets/scan", tags=["Markets"])
def trigger_scan(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Trigger a market scan and return summary."""
    from agents.scan_agent import ScanAgent

    try:
        agent = ScanAgent(db=db)
        markets = agent.scan_markets()
        return {
            "status": "success",
            "markets_found": len(markets),
            "top_markets": [
                {"market_id": m.market_id, "title": m.title[:80], "priority": m.priority_score}
                for m in markets[:5]
            ],
        }
    except Exception as e:
        logger.error(f"Scan trigger failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/markets/{market_id}/research", tags=["Markets"])
async def trigger_research(market_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Trigger research generation for a specific market."""
    from agents.research_agent import ResearchAgent

    market = db.query(Market).filter(Market.market_id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail=f"Market '{market_id}' not found.")

    try:
        agent = ResearchAgent(db=db)
        report = await agent.research_market_async(market)
        if not report:
            raise HTTPException(status_code=500, detail="Research generation failed.")
        return {
            "status": "success",
            "report_id": report.id,
            "sentiment_score": report.sentiment_score,
            "source_count": report.source_count,
            "credibility_score": report.credibility_score,
            "summary": report.summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Research trigger failed for {market_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/markets/{market_id}/predict", tags=["Markets"])
async def trigger_prediction(market_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Trigger probability prediction for a specific market."""
    from agents.prediction_agent import PredictionAgent

    market = db.query(Market).filter(Market.market_id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail=f"Market '{market_id}' not found.")

    # Get latest research report if available
    research = (
        db.query(ResearchReport)
        .filter(ResearchReport.market_id == market.id)
        .order_by(ResearchReport.created_at.desc())
        .first()
    )

    try:
        agent = PredictionAgent(db=db)
        prediction = await agent.predict_async(market, research)
        if not prediction:
            raise HTTPException(status_code=500, detail="Prediction generation failed.")
        return {
            "status": "success",
            "prediction_id": prediction.id,
            "predicted_probability": prediction.predicted_probability,
            "implied_probability": prediction.implied_probability,
            "edge": prediction.edge,
            "confidence_score": prediction.confidence_score,
            "reasoning": prediction.reasoning,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Prediction trigger failed for {market_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Decision endpoints
# ---------------------------------------------------------------------------


@router.get("/decisions", response_model=List[DecisionResponse], tags=["Decisions"])
def list_decisions(
    action: Optional[str] = Query(None, description="Filter by action (buy/skip/observe)"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> List[DecisionResponse]:
    """List risk decisions with optional action and date filters."""
    q = db.query(RiskDecision)

    if action:
        try:
            q = q.filter(RiskDecision.action == ActionEnum(action.lower()))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid action: {action}")
    if date_from:
        q = q.filter(RiskDecision.created_at >= date_from)
    if date_to:
        q = q.filter(RiskDecision.created_at <= date_to)

    decisions = (
        q.order_by(RiskDecision.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = []
    for d in decisions:
        market = db.query(Market).filter(Market.id == d.market_id).first()
        results.append(
            DecisionResponse(
                id=d.id,
                market_id=d.market_id,
                action=d.action,
                recommended_size=d.recommended_size,
                ev=d.ev,
                risk_score=d.risk_score,
                reason=d.reason,
                created_at=d.created_at,
                market_title=market.title[:80] if market else None,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Outcome endpoints
# ---------------------------------------------------------------------------


@router.get("/outcomes", response_model=List[OutcomeResponse], tags=["Outcomes"])
def list_outcomes(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """List outcomes with a PnL summary."""
    outcomes = (
        db.query(Outcome)
        .order_by(Outcome.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = []
    for o in outcomes:
        market = db.query(Market).filter(Market.id == o.market_id).first()
        results.append(
            OutcomeResponse(
                id=o.id,
                market_id=o.market_id,
                actual_result=o.actual_result,
                pnl=o.pnl,
                review_notes=o.review_notes,
                failure_tags=o.failure_tags,
                created_at=o.created_at,
                market_title=market.title[:80] if market else None,
            )
        )
    return results


@router.post("/outcomes/{market_id}", tags=["Outcomes"])
def record_outcome(
    market_id: str,
    body: RecordOutcomeRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Manually record an outcome for a market."""
    market = db.query(Market).filter(Market.market_id == market_id).first()
    if not market:
        raise HTTPException(status_code=404, detail=f"Market '{market_id}' not found.")

    existing = db.query(Outcome).filter(Outcome.market_id == market.id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Outcome already recorded for this market.")

    try:
        outcome = Outcome(
            market_id=market.id,
            actual_result=body.actual_result,
            pnl=body.pnl,
            review_notes="Manually recorded.",
            failure_tags=[],
        )
        market.status = MarketStatus.RESOLVED
        market.updated_at = datetime.utcnow()
        db.add(outcome)
        db.commit()
        db.refresh(outcome)
        return {
            "status": "success",
            "outcome_id": outcome.id,
            "actual_result": outcome.actual_result,
            "pnl": outcome.pnl,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to record outcome for {market_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------


@router.get("/backtest", tags=["Backtest"])
def get_backtest(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Return historical backtesting performance data.

    Computes:
      - Per-outcome records: date, predicted_prob, actual_result, pnl, market_title
      - Brier score (lower is better)
      - Calibration table: predictions bucketed into 10% bands vs actual rate
      - Cumulative PnL over time
    """
    # Fetch all outcomes joined with their latest prediction
    outcomes = db.query(Outcome).order_by(Outcome.created_at.asc()).all()

    records = []
    cumulative_pnl = 0.0
    brier_sum = 0.0
    brier_count = 0

    # Calibration buckets: 0-10%, 10-20%, ..., 90-100%
    calibration_buckets: Dict[str, Dict[str, Any]] = {}
    for i in range(10):
        bucket_key = f"{i*10}-{(i+1)*10}%"
        calibration_buckets[bucket_key] = {"predicted_count": 0, "actual_yes_count": 0}

    for outcome in outcomes:
        market = db.query(Market).filter(Market.id == outcome.market_id).first()
        prediction = (
            db.query(Prediction)
            .filter(Prediction.market_id == outcome.market_id)
            .order_by(Prediction.created_at.desc())
            .first()
        )

        predicted_prob = float(prediction.predicted_probability) if prediction else 0.5
        actual_result = bool(outcome.actual_result)
        pnl = float(outcome.pnl or 0.0)
        cumulative_pnl += pnl

        # Brier score contribution: (predicted - actual)^2
        actual_val = 1.0 if actual_result else 0.0
        brier_sum += (predicted_prob - actual_val) ** 2
        brier_count += 1

        # Calibration: bucket by predicted probability
        bucket_idx = min(9, int(predicted_prob * 10))
        bucket_key = f"{bucket_idx*10}-{(bucket_idx+1)*10}%"
        calibration_buckets[bucket_key]["predicted_count"] += 1
        if actual_result:
            calibration_buckets[bucket_key]["actual_yes_count"] += 1

        records.append({
            "date": outcome.created_at.isoformat() if outcome.created_at else None,
            "market_title": (market.title[:80] if market else "Unknown"),
            "market_id": (market.market_id if market else ""),
            "predicted_prob": round(predicted_prob, 4),
            "actual_result": actual_result,
            "pnl": round(pnl, 4),
            "cumulative_pnl": round(cumulative_pnl, 4),
        })

    brier_score = round(brier_sum / brier_count, 6) if brier_count > 0 else None

    # Build calibration table
    calibration_table = []
    for bucket_key, bucket in calibration_buckets.items():
        count = bucket["predicted_count"]
        yes_count = bucket["actual_yes_count"]
        actual_rate = round(yes_count / count, 4) if count > 0 else None
        calibration_table.append({
            "predicted_range": bucket_key,
            "count": count,
            "actual_yes_rate": actual_rate,
        })

    return {
        "records": records,
        "total_outcomes": len(records),
        "brier_score": brier_score,
        "total_pnl": round(cumulative_pnl, 4),
        "calibration_table": calibration_table,
    }


@router.get("/stats", response_model=StatsResponse, tags=["Stats"])
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    """Return aggregate system statistics."""
    total_markets = db.query(func.count(Market.id)).scalar() or 0
    active_markets = (
        db.query(func.count(Market.id))
        .filter(Market.status == MarketStatus.ACTIVE)
        .scalar()
        or 0
    )
    resolved_markets = (
        db.query(func.count(Market.id))
        .filter(Market.status == MarketStatus.RESOLVED)
        .scalar()
        or 0
    )
    total_predictions = db.query(func.count(Prediction.id)).scalar() or 0
    total_decisions = db.query(func.count(RiskDecision.id)).scalar() or 0
    buy_decisions = (
        db.query(func.count(RiskDecision.id))
        .filter(RiskDecision.action == ActionEnum.BUY)
        .scalar()
        or 0
    )
    total_outcomes = db.query(func.count(Outcome.id)).scalar() or 0

    wins = (
        db.query(func.count(Outcome.id)).filter(Outcome.pnl > 0).scalar() or 0
    )
    losses = (
        db.query(func.count(Outcome.id)).filter(Outcome.pnl < 0).scalar() or 0
    )
    total_pnl = float(db.query(func.sum(Outcome.pnl)).scalar() or 0.0)
    avg_confidence = float(
        db.query(func.avg(Prediction.confidence_score)).scalar() or 0.0
    )

    win_rate = (wins / total_outcomes) if total_outcomes > 0 else 0.0

    decisions_by_action: Dict[str, int] = {}
    for action_val in ["buy", "skip", "observe"]:
        try:
            count = db.query(func.count(RiskDecision.id)).filter(
                RiskDecision.action == ActionEnum(action_val)
            ).scalar() or 0
            decisions_by_action[action_val] = count
        except Exception:
            decisions_by_action[action_val] = 0

    return StatsResponse(
        total_markets=total_markets,
        active_markets=active_markets,
        resolved_markets=resolved_markets,
        total_predictions=total_predictions,
        total_decisions=total_decisions,
        buy_decisions=buy_decisions,
        total_outcomes=total_outcomes,
        win_count=wins,
        loss_count=losses,
        win_rate=round(win_rate, 4),
        total_pnl=round(total_pnl, 2),
        avg_confidence=round(avg_confidence, 4),
        decisions_by_action=decisions_by_action,
    )


# ---------------------------------------------------------------------------
# Paper Trading endpoints
# ---------------------------------------------------------------------------


class PaperTradeResponse(BaseModel):
    id: int
    market_id: int
    market_title: Optional[str] = None
    direction: str
    entry_price: float
    predicted_prob: float
    edge: float
    confidence: float
    size_usd: float
    is_short_term: bool
    status: str
    actual_result: Optional[bool]
    pnl: Optional[float]
    created_at: datetime
    resolved_at: Optional[datetime]

    model_config = {"from_attributes": True}


def _paper_segment_stats(trades: List[PaperTrade]) -> Dict[str, Any]:
    """Compute win/loss/open/pnl/edge stats for a list of PaperTrade records."""
    total = len(trades)
    won = sum(1 for t in trades if t.status == "won")
    lost = sum(1 for t in trades if t.status == "lost")
    open_count = sum(1 for t in trades if t.status == "open")
    resolved = won + lost
    win_rate = round(won / resolved, 4) if resolved > 0 else 0.0
    total_pnl = round(sum(float(t.pnl or 0) for t in trades), 4)
    avg_edge = round(
        sum(float(t.edge or 0) for t in trades) / total, 4
    ) if total > 0 else 0.0
    return {
        "total": total,
        "won": won,
        "lost": lost,
        "open": open_count,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_edge": avg_edge,
    }


@router.get("/paper-trades", response_model=List[PaperTradeResponse], tags=["Paper Trading"])
def list_paper_trades(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> List[PaperTradeResponse]:
    """List paper trades joined with market title."""
    trades = (
        db.query(PaperTrade)
        .order_by(PaperTrade.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    results = []
    for t in trades:
        market = db.query(Market).filter(Market.id == t.market_id).first()
        results.append(
            PaperTradeResponse(
                id=t.id,
                market_id=t.market_id,
                market_title=market.title[:80] if market else None,
                direction=t.direction,
                entry_price=t.entry_price,
                predicted_prob=t.predicted_prob,
                edge=t.edge,
                confidence=t.confidence,
                size_usd=t.size_usd,
                is_short_term=t.is_short_term,
                status=t.status,
                actual_result=t.actual_result,
                pnl=t.pnl,
                created_at=t.created_at,
                resolved_at=t.resolved_at,
            )
        )
    return results


@router.get("/stats/performance", tags=["Stats"])
def get_performance_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Return detailed performance statistics split by short-term vs long-term markets,
    paper trading summary, and signal stats.
    """
    from datetime import timedelta

    all_paper = db.query(PaperTrade).all()

    # Short-term: paper trades on markets resolving within 7 days of trade creation
    short_term_trades = [t for t in all_paper if t.is_short_term]
    long_term_trades = [t for t in all_paper if not t.is_short_term]

    short_stats = _paper_segment_stats(short_term_trades)
    long_stats = _paper_segment_stats(long_term_trades)

    # Paper trading overall
    total_trades = len(all_paper)
    open_trades = sum(1 for t in all_paper if t.status == "open")
    won = sum(1 for t in all_paper if t.status == "won")
    lost = sum(1 for t in all_paper if t.status == "lost")
    resolved = won + lost
    win_rate = round(won / resolved, 4) if resolved > 0 else 0.0
    total_pnl = round(sum(float(t.pnl or 0) for t in all_paper), 4)
    avg_edge = round(
        sum(float(t.edge or 0) for t in all_paper) / total_trades, 4
    ) if total_trades > 0 else 0.0

    # Trades per day
    action_frequency = 0.0
    if all_paper:
        oldest = min(t.created_at for t in all_paper)
        days_span = max(
            1.0,
            (datetime.utcnow() - oldest).total_seconds() / 86400,
        )
        action_frequency = round(total_trades / days_span, 4)

    paper_trading_stats = {
        "total_trades": total_trades,
        "open_trades": open_trades,
        "won": won,
        "lost": lost,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_edge": avg_edge,
        "action_frequency_per_day": action_frequency,
    }

    # Signal stats
    total_decisions = db.query(func.count(RiskDecision.id)).scalar() or 0
    buy_count = (
        db.query(func.count(RiskDecision.id))
        .filter(RiskDecision.action == ActionEnum.BUY)
        .scalar()
        or 0
    )
    avg_edge_all = float(db.query(func.avg(Prediction.edge)).scalar() or 0.0)

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - __import__('datetime').timedelta(days=7)
    markets_today = (
        db.query(func.count(RiskDecision.id))
        .filter(RiskDecision.created_at >= today_start)
        .scalar()
        or 0
    )
    markets_week = (
        db.query(func.count(RiskDecision.id))
        .filter(RiskDecision.created_at >= week_start)
        .scalar()
        or 0
    )

    buy_signal_rate = round(buy_count / total_decisions, 4) if total_decisions > 0 else 0.0
    paper_signal_rate = round(total_trades / total_decisions, 4) if total_decisions > 0 else 0.0

    signal_stats = {
        "avg_edge": round(avg_edge_all, 4),
        "buy_signal_rate": buy_signal_rate,
        "paper_signal_rate": paper_signal_rate,
        "markets_analyzed_today": markets_today,
        "markets_analyzed_week": markets_week,
    }

    return {
        "short_term": short_stats,
        "long_term": long_stats,
        "paper_trading": paper_trading_stats,
        "signal_stats": signal_stats,
    }

"""
ReviewAgent: Reviews resolved markets, records outcomes, calculates PnL,
and performs failure analysis using the LLM.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy.orm import Session

from config import settings
from database.models import ActionEnum, Market, MarketStatus, Outcome, PaperTrade, Prediction, RiskDecision, ResearchReport
from database.session import get_db_context
from services.alert_service import alert_service
from services.llm_service import LLMService
from services.ml_model import calibrator

logger = logging.getLogger(__name__)


def _calculate_pnl(
    action: str,
    actual_result: bool,
    recommended_size: float,
    implied_prob: float,
) -> float:
    """
    Calculate profit/loss for a completed position.

    For a BUY position on YES:
        - Win (actual_result=True):  pnl = size * (1/implied_prob - 1)
        - Lose (actual_result=False): pnl = -size

    For SKIP/OBSERVE decisions: pnl = 0
    """
    if action != ActionEnum.BUY.value and action != ActionEnum.BUY:
        return 0.0

    if recommended_size <= 0:
        return 0.0

    if actual_result:
        # Payout = cost + profit; net profit = size * (net_odds)
        net_odds = (1.0 / max(implied_prob, 0.01)) - 1.0
        return round(recommended_size * net_odds, 4)
    else:
        return round(-recommended_size, 4)


class ReviewAgent:
    """
    Identifies markets that have passed their resolve_time, records outcomes,
    and uses the LLM to conduct failure analysis.
    """

    def __init__(self, db: Optional[Session] = None):
        self.llm = LLMService()
        self._db = db

    def review_completed_markets(self) -> List[Outcome]:
        """
        Synchronous entry point.
        Returns list of newly created Outcome records.
        """
        try:
            return asyncio.run(self._review_async())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._review_async())

    async def review_completed_markets_async(self) -> List[Outcome]:
        """Async entry point."""
        return await self._review_async()

    async def _review_async(self) -> List[Outcome]:
        """Core async review pipeline."""
        logger.info("ReviewAgent: scanning for resolved markets.")
        outcomes: List[Outcome] = []

        def _fetch_markets(db: Session) -> List[Market]:
            now = datetime.utcnow()
            return (
                db.query(Market)
                .filter(
                    Market.status == MarketStatus.ACTIVE,
                    Market.resolve_time <= now,
                    Market.resolve_time.isnot(None),
                )
                .all()
            )

        if self._db:
            markets_to_review = _fetch_markets(self._db)
        else:
            with get_db_context() as db:
                markets_to_review = _fetch_markets(db)
                db.expunge_all()  # detach so we can use outside context

        logger.info(f"ReviewAgent: found {len(markets_to_review)} markets to review.")

        for market in markets_to_review:
            outcome = await self._review_single_market(market)
            if outcome:
                outcomes.append(outcome)

        # After recording outcomes, attempt ML retraining with all available data
        await self._retrain_ml_model()

        return outcomes

    async def _retrain_ml_model(self) -> None:
        """
        Gather all resolved outcomes with associated predictions and research data,
        build a training dataset, and retrain the ML calibration model.
        """
        try:
            def _collect_training_data(db: Session) -> List[Dict[str, Any]]:
                training_data: List[Dict[str, Any]] = []
                outcomes = db.query(Outcome).all()
                for outcome in outcomes:
                    pred = (
                        db.query(Prediction)
                        .filter(Prediction.market_id == outcome.market_id)
                        .order_by(Prediction.created_at.desc())
                        .first()
                    )
                    if not pred:
                        continue
                    market = db.query(Market).filter(Market.id == outcome.market_id).first()
                    if not market:
                        continue
                    research = (
                        db.query(ResearchReport)
                        .filter(ResearchReport.market_id == outcome.market_id)
                        .order_by(ResearchReport.created_at.desc())
                        .first()
                    )
                    sentiment = float(research.sentiment_score or 0.0) if research else 0.0
                    credibility = float(research.credibility_score or 0.5) if research else 0.5

                    training_data.append({
                        "market_price": float(pred.implied_probability or 0.5),
                        "llm_prob": float(pred.predicted_probability or 0.5),
                        "sentiment": sentiment,
                        "credibility": credibility,
                        "liquidity": float(market.liquidity or 0),
                        "volume": float(market.volume_24h or 0),
                        "spread": float(market.spread or 0.05),
                        "actual_result": bool(outcome.actual_result),
                    })
                return training_data

            if self._db:
                training_data = _collect_training_data(self._db)
            else:
                with get_db_context() as db:
                    training_data = _collect_training_data(db)

            if training_data:
                logger.info(f"ReviewAgent: attempting ML retrain with {len(training_data)} samples")
                calibrator.train(training_data)
            else:
                logger.debug("ReviewAgent: no training data available for ML retrain")
        except Exception as e:
            logger.error(f"ReviewAgent: ML retraining failed: {e}")

    def _fetch_polymarket_result(self, market_id: str) -> Optional[bool]:
        """
        Attempt to auto-fetch the resolution result for a Polymarket market.
        Extracts the numeric ID from 'polymarket_XXXXX' and calls the Gamma API.
        Returns True if YES resolved, False if NO resolved, None if unknown/error.
        """
        try:
            # Extract numeric/slug ID from 'polymarket_<id>'
            if market_id.startswith("polymarket_"):
                numeric_id = market_id[len("polymarket_"):]
            else:
                return None

            url = f"https://gamma-api.polymarket.com/markets/{numeric_id}"
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                logger.debug(f"Gamma API returned {resp.status_code} for market {market_id}")
                return None

            data = resp.json()
            # Check if the market is closed/resolved
            closed = data.get("closed", False)
            resolved = data.get("resolved", False)
            if not (closed or resolved):
                logger.debug(f"Market {market_id} is not yet resolved on Polymarket")
                return None

            # outcomePrices is a JSON string like '["0.99", "0.01"]'
            outcome_prices = data.get("outcomePrices")
            if isinstance(outcome_prices, str):
                import json as _json
                try:
                    prices = _json.loads(outcome_prices)
                    if prices:
                        first_price = float(prices[0])
                        # If first outcome (YES) price is ~1.0, result is True
                        return first_price >= 0.9
                except Exception:
                    pass
            elif isinstance(outcome_prices, list) and outcome_prices:
                first_price = float(outcome_prices[0])
                return first_price >= 0.9

            logger.debug(f"Could not determine result from outcomePrices for {market_id}")
            return None
        except Exception as e:
            logger.debug(f"Failed to fetch Polymarket result for {market_id}: {e}")
            return None

    async def _review_single_market(self, market: Market) -> Optional[Outcome]:
        """
        Review a single market.
        For Polymarket markets, attempts to fetch the actual resolution via the Gamma API.
        Falls back to inferring from the last known market price (price > 0.5 → YES).
        """
        logger.info(f"ReviewAgent: reviewing market '{market.title[:60]}'")

        def _check_existing(db: Session) -> bool:
            return (
                db.query(Outcome)
                .filter(Outcome.market_id == market.id)
                .first()
            ) is not None

        if self._db:
            has_outcome = _check_existing(self._db)
        else:
            with get_db_context() as db:
                has_outcome = _check_existing(db)

        if has_outcome:
            logger.debug(f"Market {market.market_id} already has an outcome; skipping.")
            return None

        # Attempt to fetch actual resolution from Polymarket API
        actual_result: Optional[bool] = None
        if market.platform == "polymarket":
            actual_result = self._fetch_polymarket_result(market.market_id)
            if actual_result is not None:
                logger.info(f"ReviewAgent: fetched Polymarket resolution for {market.market_id}: {'YES' if actual_result else 'NO'}")

        # Fall back to inferring from the last known market price
        if actual_result is None:
            actual_result = (market.current_price or 0.5) > 0.5
            logger.debug(f"ReviewAgent: using price-based inference for {market.market_id}: {'YES' if actual_result else 'NO'}")

        # Get the latest prediction and risk decision
        def _fetch_prediction_and_decision(db: Session):
            pred = (
                db.query(Prediction)
                .filter(Prediction.market_id == market.id)
                .order_by(Prediction.created_at.desc())
                .first()
            )
            dec = (
                db.query(RiskDecision)
                .filter(RiskDecision.market_id == market.id)
                .order_by(RiskDecision.created_at.desc())
                .first()
            )
            return pred, dec

        if self._db:
            prediction, decision = _fetch_prediction_and_decision(self._db)
        else:
            with get_db_context() as db:
                prediction, decision = _fetch_prediction_and_decision(db)
                if prediction:
                    db.expunge(prediction)
                if decision:
                    db.expunge(decision)

        # Calculate PnL
        pnl = 0.0
        if prediction and decision:
            pnl = _calculate_pnl(
                action=decision.action,
                actual_result=actual_result,
                recommended_size=float(decision.recommended_size or 0),
                implied_prob=float(prediction.implied_probability or 0.5),
            )

        # Determine if prediction was wrong
        prediction_correct = True
        if prediction:
            predicted_yes = prediction.predicted_probability > 0.5
            prediction_correct = predicted_yes == actual_result

        # LLM failure analysis (only for incorrect predictions with a BUY decision)
        review_notes = "Market resolved. No position was taken."
        failure_tags: List[str] = []

        if (
            prediction
            and decision
            and decision.action == ActionEnum.BUY
            and not prediction_correct
        ):
            try:
                pred_dict = {
                    "predicted_probability": prediction.predicted_probability,
                    "implied_probability": prediction.implied_probability,
                    "confidence_score": prediction.confidence_score,
                    "reasoning": prediction.reasoning,
                }
                outcome_dict = {"actual_result": actual_result, "pnl": pnl}
                analysis = await self.llm.analyze_failure(
                    market.title, pred_dict, outcome_dict
                )
                failure_tags = analysis.get("failure_tags", ["prediction_error"])
                root_cause = analysis.get("root_cause", "")
                suggestions = analysis.get("improvement_suggestions", [])
                review_notes = (
                    f"Prediction incorrect. Root cause: {root_cause}. "
                    f"Suggestions: {'; '.join(suggestions)}"
                )
            except Exception as e:
                logger.error(f"LLM failure analysis failed for {market.market_id}: {e}")
                failure_tags = ["prediction_error"]
                review_notes = "Prediction incorrect. LLM failure analysis unavailable."
        elif prediction and prediction_correct:
            review_notes = (
                f"Prediction correct. "
                f"Predicted: {'YES' if prediction.predicted_probability > 0.5 else 'NO'}, "
                f"Actual: {'YES' if actual_result else 'NO'}. "
                f"PnL: ${pnl:.2f}"
            )

        outcome = Outcome(
            market_id=market.id,
            actual_result=actual_result,
            pnl=pnl,
            review_notes=review_notes,
            failure_tags=failure_tags,
        )

        def _save(db: Session) -> Outcome:
            # Update market status
            m = db.query(Market).filter(Market.id == market.id).first()
            if m:
                m.status = MarketStatus.RESOLVED
                m.updated_at = datetime.utcnow()
            db.add(outcome)
            db.flush()
            db.refresh(outcome)

            # Resolve any open PaperTrades for this market
            open_paper_trades = (
                db.query(PaperTrade)
                .filter(
                    PaperTrade.market_id == market.id,
                    PaperTrade.status == "open",
                )
                .all()
            )
            now = datetime.utcnow()
            for pt in open_paper_trades:
                pt.actual_result = actual_result
                pt.resolved_at = now
                if actual_result:
                    pt.status = "won"
                    entry = max(float(pt.entry_price or 0.01), 0.01)
                    pt.pnl = round(float(pt.size_usd) * (1.0 / entry - 1.0), 4)
                else:
                    pt.status = "lost"
                    pt.pnl = round(-float(pt.size_usd), 4)
                try:
                    alert_service.send_paper_trade_result(
                        market_title=market.title,
                        status=pt.status,
                        predicted_prob=float(pt.predicted_prob),
                        actual_result=actual_result,
                        entry_price=float(pt.entry_price or 0),
                        pnl=float(pt.pnl),
                        size_usd=float(pt.size_usd),
                    )
                except Exception as _ae:
                    logger.warning(f"Failed to send Telegram paper trade result alert: {_ae}")

            return outcome

        try:
            if self._db:
                saved = _save(self._db)
                self._db.commit()
            else:
                with get_db_context() as db:
                    saved = _save(db)

            logger.info(
                f"ReviewAgent: recorded outcome {saved.id} for market {market.market_id} "
                f"— result={'YES' if actual_result else 'NO'}, pnl=${pnl:.2f}"
            )
            return saved
        except Exception as e:
            logger.error(f"Failed to save outcome for market {market.market_id}: {e}")
            return None

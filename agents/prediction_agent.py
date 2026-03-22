"""
PredictionAgent: Generates calibrated probability predictions for markets
by combining rule-based adjustments with LLM reasoning.
"""

import asyncio
import logging
from typing import Optional

from sqlalchemy.orm import Session

from config import settings
from database.models import Market, Prediction, ResearchReport
from database.session import get_db_context
from services.llm_service import LLMService
from services.ml_model import calibrator

logger = logging.getLogger(__name__)

MODEL_VERSION = "v1.0"


def _calculate_confidence(
    liquidity: float,
    volume_24h: float,
    source_count: int,
    credibility_score: float,
    sentiment_confidence: float,
) -> float:
    """
    Compute a confidence score [0, 1] based on data quality signals.

    Components:
        - Liquidity quality (log-scaled, up to $50K reference)
        - Volume quality (log-scaled, up to $10K reference)
        - Research depth (source_count up to 20)
        - Credibility score
        - Sentiment signal strength
    """
    liq_conf = min(1.0, (liquidity / 50_000) ** 0.5) if liquidity > 0 else 0.0
    vol_conf = min(1.0, (volume_24h / 10_000) ** 0.5) if volume_24h > 0 else 0.0
    src_conf = min(1.0, source_count / 20)

    confidence = (
        0.25 * liq_conf
        + 0.20 * vol_conf
        + 0.20 * src_conf
        + 0.20 * credibility_score
        + 0.15 * sentiment_confidence
    )
    return round(min(1.0, max(0.0, confidence)), 4)


def _rule_based_adjustment(
    implied_prob: float,
    sentiment_score: float,
    credibility_score: float,
) -> float:
    """
    Apply simple rule-based adjustments to the implied probability.

    Sentiment pushes the probability toward extremes when credibility is high.
    Max adjustment is capped at ±10 percentage points.
    """
    max_adjustment = 0.10
    sentiment_weight = credibility_score * 0.5  # max influence is 0.5 * 0.1 = 0.05

    adjustment = sentiment_score * sentiment_weight * max_adjustment
    adjusted = implied_prob + adjustment

    return max(0.01, min(0.99, adjusted))


class PredictionAgent:
    """
    Combines market data, research reports, and LLM reasoning to generate
    calibrated probability predictions.
    """

    def __init__(self, db: Optional[Session] = None):
        self.llm = LLMService()
        self._db = db

    def predict(
        self, market: Market, research_report: Optional[ResearchReport] = None
    ) -> Optional[Prediction]:
        """
        Synchronous entry point.
        Returns a persisted Prediction or None on failure.
        """
        try:
            return asyncio.run(self._predict_async(market, research_report))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._predict_async(market, research_report))

    async def predict_async(
        self, market: Market, research_report: Optional[ResearchReport] = None
    ) -> Optional[Prediction]:
        """Async entry point."""
        return await self._predict_async(market, research_report)

    async def quick_predict_async(self, market: Market) -> Optional[Prediction]:
        """
        Fast path prediction — skips LLM and ResearchAgent entirely.
        Uses rule-based adjustment + XGBoost calibration only.

        When to use:
          - Markets resolving within 6 h (every second counts)
          - As a fallback when LLM is unavailable

        Trade-off: lower confidence score, but runs in milliseconds with zero API cost.
        """
        logger.info(
            f"PredictionAgent (quick): predicting for '{market.title[:60]}'"
        )

        implied_prob = max(0.01, min(0.99, float(market.current_price or 0.5)))
        rule_adjusted = _rule_based_adjustment(implied_prob, 0.0, 0.5)

        calibrated_prob, confidence_boost = calibrator.predict(
            market_price=implied_prob,
            llm_prob=rule_adjusted,
            sentiment=0.0,
            credibility=0.5,
            liquidity=float(market.liquidity or 0),
            volume=float(market.volume_24h or 0),
            spread=float(market.spread or 0.05),
        )

        predicted_prob = (
            round(0.7 * calibrated_prob + 0.3 * rule_adjusted, 6)
            if calibrator.is_trained
            else rule_adjusted
        )
        predicted_prob = max(0.01, min(0.99, predicted_prob))

        # Quick predictions carry lower confidence (no research, no LLM)
        base_confidence = _calculate_confidence(
            liquidity=float(market.liquidity or 0),
            volume_24h=float(market.volume_24h or 0),
            source_count=0,
            credibility_score=0.5,
            sentiment_confidence=0.0,
        )
        confidence = round(min(1.0, base_confidence * 0.80 + confidence_boost), 4)

        edge = round(predicted_prob - implied_prob, 6)
        reasoning = "Quick prediction: rule-based + XGBoost only (no LLM, no research)."

        prediction = Prediction(
            market_id=market.id,
            predicted_probability=predicted_prob,
            implied_probability=round(implied_prob, 6),
            edge=edge,
            confidence_score=confidence,
            model_version=f"{MODEL_VERSION}-quick",
            reasoning=reasoning,
        )

        def _save(db: Session) -> Prediction:
            db.add(prediction)
            db.flush()
            db.refresh(prediction)
            return prediction

        try:
            if self._db:
                saved = _save(self._db)
                self._db.commit()
            else:
                with get_db_context() as db:
                    saved = _save(db)

            logger.info(
                f"PredictionAgent (quick): saved | "
                f"predicted={saved.predicted_probability:.3f}, "
                f"edge={saved.edge:.3f}, confidence={saved.confidence_score:.3f}"
            )
            return saved
        except Exception as e:
            logger.error(f"Quick prediction save failed for {market.market_id}: {e}")
            return None

    async def _predict_async(
        self, market: Market, research_report: Optional[ResearchReport] = None
    ) -> Optional[Prediction]:
        """Core async prediction pipeline."""
        logger.info(f"PredictionAgent: predicting for market '{market.title[:60]}'")

        # Implied probability from current market price
        implied_prob = max(0.01, min(0.99, float(market.current_price or 0.5)))

        # Research data
        sentiment_score = 0.0
        credibility_score = 0.5
        source_count = 0
        sentiment_confidence = 0.0
        research_summary = "No research available."

        if research_report:
            sentiment_score = float(research_report.sentiment_score or 0.0)
            credibility_score = float(research_report.credibility_score or 0.5)
            source_count = int(research_report.source_count or 0)
            research_summary = research_report.summary or research_summary

            raw_data = research_report.raw_data or {}
            kw_sentiment = raw_data.get("keyword_sentiment", {})
            sentiment_confidence = float(kw_sentiment.get("confidence", 0.3))

        # Rule-based starting estimate
        rule_adjusted = _rule_based_adjustment(
            implied_prob, sentiment_score, credibility_score
        )

        # LLM refinement
        market_data = {
            "current_price": market.current_price,
            "liquidity": market.liquidity,
            "volume_24h": market.volume_24h,
            "spread": market.spread,
            "platform": market.platform,
        }

        try:
            llm_result = await self.llm.predict_probability(
                market.title, market_data, research_summary
            )
            llm_prob = float(llm_result.get("predicted_probability", rule_adjusted))
            llm_conf = float(llm_result.get("confidence", 0.5))
            reasoning = llm_result.get("reasoning", "")
        except Exception as e:
            logger.error(f"LLM prediction failed for {market.market_id}: {e}")
            llm_prob = rule_adjusted
            llm_conf = 0.3
            reasoning = f"LLM unavailable; rule-based estimate used. Error: {e}"

        # Blend rule-based and LLM estimates
        # Weight LLM more heavily when it reports higher confidence
        llm_weight = min(0.8, llm_conf)
        rule_weight = 1.0 - llm_weight
        blended_llm_prob = (llm_weight * llm_prob) + (rule_weight * rule_adjusted)
        blended_llm_prob = max(0.01, min(0.99, blended_llm_prob))

        # Apply ML calibration if the model is trained
        calibrated_prob, confidence_boost = calibrator.predict(
            market_price=implied_prob,
            llm_prob=blended_llm_prob,
            sentiment=sentiment_score,
            credibility=credibility_score,
            liquidity=float(market.liquidity or 0),
            volume=float(market.volume_24h or 0),
            spread=float(market.spread or 0.05),
        )
        if calibrator.is_trained:
            predicted_prob = round(0.7 * calibrated_prob + 0.3 * blended_llm_prob, 6)
            logger.info(
                f"PredictionAgent: ML calibration applied — "
                f"blended_llm={blended_llm_prob:.3f}, calibrated={calibrated_prob:.3f}, "
                f"final={predicted_prob:.3f}"
            )
        else:
            predicted_prob = blended_llm_prob
            confidence_boost = 0.0
        predicted_prob = max(0.01, min(0.99, predicted_prob))

        # Overall confidence
        confidence = _calculate_confidence(
            liquidity=float(market.liquidity or 0),
            volume_24h=float(market.volume_24h or 0),
            source_count=source_count,
            credibility_score=credibility_score,
            sentiment_confidence=sentiment_confidence,
        )
        # Blend with LLM confidence, add ML confidence boost if applicable
        confidence = round((0.5 * confidence + 0.5 * llm_conf) + confidence_boost, 4)
        confidence = min(1.0, confidence)

        edge = round(predicted_prob - implied_prob, 6)

        prediction = Prediction(
            market_id=market.id,
            predicted_probability=round(predicted_prob, 6),
            implied_probability=round(implied_prob, 6),
            edge=edge,
            confidence_score=confidence,
            model_version=MODEL_VERSION,
            reasoning=reasoning,
        )

        def _save(db: Session) -> Prediction:
            db.add(prediction)
            db.flush()
            db.refresh(prediction)
            return prediction

        try:
            if self._db:
                saved = _save(self._db)
                self._db.commit()
            else:
                with get_db_context() as db:
                    saved = _save(db)

            logger.info(
                f"PredictionAgent: saved prediction {saved.id} | "
                f"predicted={saved.predicted_probability:.3f}, "
                f"implied={saved.implied_probability:.3f}, "
                f"edge={saved.edge:.3f}, confidence={saved.confidence_score:.3f}"
            )
            return saved
        except Exception as e:
            logger.error(f"Failed to save prediction for {market.market_id}: {e}")
            return None

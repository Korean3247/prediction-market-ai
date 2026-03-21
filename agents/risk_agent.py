"""
RiskAgent: Applies Kelly criterion and risk thresholds to make bet/skip decisions.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from config import settings
from database.models import ActionEnum, Market, Prediction, RiskDecision, PaperTrade
from database.session import get_db_context
from services.alert_service import alert_service

logger = logging.getLogger(__name__)


def _dynamic_kelly_fraction(confidence: float) -> float:
    """
    Map confidence score to a Kelly fraction multiplier.

    Confidence → Kelly fraction
      < 0.65   →  KELLY_MIN_FRACTION  (e.g. 0.15x — very cautious)
      0.65-0.75 → 0.25x               (quarter Kelly, baseline)
      0.75-0.85 → 0.35x               (moderate aggression)
      > 0.85   →  KELLY_MAX_FRACTION  (e.g. 0.50x — high conviction)
    """
    kmin = settings.KELLY_MIN_FRACTION
    kmax = settings.KELLY_MAX_FRACTION

    if confidence < 0.65:
        return kmin
    elif confidence < 0.75:
        return 0.25
    elif confidence < 0.85:
        return 0.35
    else:
        return kmax


def _kelly_fraction(
    predicted_prob: float,
    implied_prob: float,
    kelly_fraction: float = 0.25,
) -> float:
    """
    Compute fractional Kelly criterion position size as a fraction of bankroll.

    Kelly formula: f = (b*p - q) / b
    where:
        b = net odds received = (1 / implied_prob) - 1
        p = predicted probability of winning
        q = 1 - p (probability of losing)

    Returns fractional Kelly (f * kelly_fraction), floored at 0.
    """
    if implied_prob <= 0 or implied_prob >= 1:
        return 0.0

    b = (1.0 / implied_prob) - 1.0  # net odds
    p = predicted_prob
    q = 1.0 - p

    if b <= 0:
        return 0.0

    full_kelly = (b * p - q) / b
    fractional = full_kelly * kelly_fraction

    return max(0.0, fractional)


def _dynamic_max_position(edge: float, liquidity: float) -> float:
    """
    Determine maximum position size (as fraction of bankroll) based on edge
    and market liquidity.

    Edge tiers:
      < 0.08  → 5%  of bankroll  (baseline)
      0.08-0.15 → 10% of bankroll
      > 0.15  → MAX_POSITION_SIZE (up to 15%)

    Liquidity cap: never exceed MAX_POSITION_PCT_LIQUIDITY * liquidity in USD.
    """
    abs_edge = abs(edge)
    if abs_edge < 0.08:
        pct = 0.05
    elif abs_edge < 0.15:
        pct = 0.10
    else:
        pct = settings.MAX_POSITION_SIZE  # e.g. 0.15 or whatever is set

    bankroll_cap = pct * settings.BANKROLL
    liquidity_cap = settings.MAX_POSITION_PCT_LIQUIDITY * max(liquidity, 1.0)
    return min(bankroll_cap, liquidity_cap)


def _calculate_ev(
    predicted_prob: float,
    implied_prob: float,
) -> float:
    """
    Calculate expected value of a YES position.

    EV = (predicted_prob * payout) - cost
    where payout = 1/implied_prob per $1 staked, cost = 1.

    Simplified: EV = predicted_prob * (1/implied_prob) - 1
    """
    if implied_prob <= 0 or implied_prob >= 1:
        return 0.0
    payout = 1.0 / implied_prob
    ev = predicted_prob * payout - 1.0
    return round(ev, 6)


def _calculate_risk_score(
    edge: float,
    confidence: float,
    spread: float,
    liquidity: float,
) -> float:
    """
    Compute a risk score [0, 1] where higher means riskier.

    Components:
        - Low confidence → high risk
        - High spread → high risk
        - Low liquidity → high risk
        - Small edge → higher risk
    """
    conf_risk = 1.0 - confidence
    spread_risk = min(1.0, spread / settings.MAX_SPREAD)
    liq_risk = 1.0 - min(1.0, (liquidity / 100_000) ** 0.5)
    edge_risk = max(0.0, 1.0 - abs(edge) / 0.2)  # edges > 20% considered safe

    risk_score = (
        0.35 * conf_risk
        + 0.25 * spread_risk
        + 0.25 * liq_risk
        + 0.15 * edge_risk
    )
    return round(min(1.0, max(0.0, risk_score)), 4)


class RiskAgent:
    """
    Makes position-sizing decisions using Kelly criterion and configurable thresholds.
    """

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    def decide(self, market: Market, prediction: Prediction) -> Optional[RiskDecision]:
        """
        Apply risk management rules and return a RiskDecision.

        Decision logic:
            - If confidence < MIN_CONFIDENCE_SCORE → skip
            - If edge < MIN_EDGE (absolute) → observe
            - If EV < MIN_EV → observe
            - Otherwise → buy, sized by fractional Kelly (capped at MAX_POSITION_SIZE)
        """
        logger.info(
            f"RiskAgent: deciding for market '{market.title[:60]}' "
            f"(prediction_id={prediction.id})"
        )

        predicted_prob = float(prediction.predicted_probability)
        implied_prob = float(prediction.implied_probability)
        edge = float(prediction.edge)
        confidence = float(prediction.confidence_score)
        spread = float(market.spread or 0.05)
        liquidity = float(market.liquidity or 0)

        # --- Gate 1: Confidence check ---
        if confidence < settings.MIN_CONFIDENCE_SCORE:
            reason = (
                f"Confidence {confidence:.2f} below threshold {settings.MIN_CONFIDENCE_SCORE:.2f}. "
                "Skipping due to insufficient data quality."
            )
            logger.info(f"RiskAgent: SKIP (low confidence) — {reason}")
            decision = self._save_decision(
                market=market,
                action=ActionEnum.SKIP,
                size=0.0,
                ev=0.0,
                risk_score=_calculate_risk_score(edge, confidence, spread, liquidity),
                reason=reason,
            )
            self._maybe_create_paper_trade(market, prediction, ActionEnum.SKIP)
            return decision

        # --- Gate 2: Edge check ---
        if abs(edge) < settings.MIN_EDGE:
            reason = (
                f"Edge {edge:.3f} below minimum {settings.MIN_EDGE:.3f}. "
                "Market appears fairly priced; observing for changes."
            )
            logger.info(f"RiskAgent: OBSERVE (insufficient edge) — {reason}")
            decision = self._save_decision(
                market=market,
                action=ActionEnum.OBSERVE,
                size=0.0,
                ev=0.0,
                risk_score=_calculate_risk_score(edge, confidence, spread, liquidity),
                reason=reason,
            )
            self._maybe_create_paper_trade(market, prediction, ActionEnum.OBSERVE)
            return decision

        # --- Gate 3: EV check ---
        ev = _calculate_ev(predicted_prob, implied_prob)
        if ev < settings.MIN_EV:
            reason = (
                f"Expected value {ev:.4f} below minimum {settings.MIN_EV:.4f}. "
                "Risk-adjusted return is insufficient."
            )
            logger.info(f"RiskAgent: OBSERVE (negative/low EV) — {reason}")
            decision = self._save_decision(
                market=market,
                action=ActionEnum.OBSERVE,
                size=0.0,
                ev=ev,
                risk_score=_calculate_risk_score(edge, confidence, spread, liquidity),
                reason=reason,
            )
            self._maybe_create_paper_trade(market, prediction, ActionEnum.OBSERVE)
            return decision

        # --- Buy decision: Dynamic Kelly sizing ---
        dyn_kelly_frac = _dynamic_kelly_fraction(confidence)
        kelly_f = _kelly_fraction(predicted_prob, implied_prob, dyn_kelly_frac)
        max_size = _dynamic_max_position(edge, liquidity)
        recommended_size = min(kelly_f * settings.BANKROLL, max_size)
        recommended_size = round(recommended_size, 2)

        risk_score = _calculate_risk_score(edge, confidence, spread, liquidity)

        reason = (
            f"BUY signal: edge={edge:.3f}, EV={ev:.4f}, "
            f"confidence={confidence:.2f}, Kelly={kelly_f:.4f} "
            f"(dyn_fraction={dyn_kelly_frac:.2f}x). "
            f"Recommended size: ${recommended_size:.2f} "
            f"(max=${max_size:.2f}, bankroll=${settings.BANKROLL:.0f})."
        )

        logger.info(
            f"RiskAgent: BUY — edge={edge:.3f}, EV={ev:.4f}, "
            f"size=${recommended_size:.2f}, risk={risk_score:.3f}"
        )

        # Send Telegram alert for BUY signal
        try:
            alert_service.send_buy_signal(
                market_title=market.title,
                market_id=market.market_id,
                predicted_prob=predicted_prob,
                implied_prob=implied_prob,
                edge=edge,
                ev=ev,
                recommended_size=recommended_size,
            )
        except Exception as e:
            logger.warning(f"Failed to send Telegram BUY alert for {market.market_id}: {e}")

        decision = self._save_decision(
            market=market,
            action=ActionEnum.BUY,
            size=recommended_size,
            ev=ev,
            risk_score=risk_score,
            reason=reason,
        )
        self._maybe_create_paper_trade(market, prediction, ActionEnum.BUY)
        return decision

    def _maybe_create_paper_trade(
        self,
        market: Market,
        prediction: Prediction,
        real_action: ActionEnum,
    ) -> None:
        """
        Create a PaperTrade for every prediction to maximize data collection.
        Records all signals regardless of edge direction — the model learns from
        both good and bad calls. BUY decisions are also recorded as paper trades.
        """
        edge = float(prediction.edge)
        confidence = float(prediction.confidence_score)

        if confidence >= settings.PAPER_MIN_CONFIDENCE:
            from datetime import datetime as _dt
            now = _dt.utcnow()
            is_short_term = False
            if market.resolve_time:
                hours_left = (market.resolve_time - now).total_seconds() / 3600
                is_short_term = hours_left <= settings.FAST_PIPELINE_HOURS

            def _save_paper(db: Session) -> None:
                # Avoid duplicate open paper trades for the same market
                existing_open = db.query(PaperTrade).filter(
                    PaperTrade.market_id == market.id,
                    PaperTrade.status == "open",
                ).first()
                if existing_open:
                    # Update if edge improved significantly (>= 1% better)
                    if edge - existing_open.edge >= 0.01:
                        existing_open.entry_price = float(market.current_price)
                        existing_open.predicted_prob = float(prediction.predicted_probability)
                        existing_open.edge = edge
                        existing_open.confidence = confidence
                        logger.info(
                            f"RiskAgent: updated PaperTrade for market {market.market_id} "
                            f"(edge {existing_open.edge:.3f} → {edge:.3f})"
                        )
                    return

                paper_trade = PaperTrade(
                    market_id=market.id,
                    direction="YES",
                    entry_price=float(market.current_price),
                    predicted_prob=float(prediction.predicted_probability),
                    edge=edge,
                    confidence=confidence,
                    size_usd=10.0,
                    is_short_term=is_short_term,
                    status="open",
                )
                db.add(paper_trade)
                logger.info(
                    f"RiskAgent: created PaperTrade for market {market.market_id} "
                    f"(edge={edge:.3f}, confidence={confidence:.2f})"
                )
                try:
                    alert_service.send_paper_trade_signal(
                        market_title=market.title,
                        market_id=market.market_id,
                        predicted_prob=float(prediction.predicted_probability),
                        implied_prob=float(prediction.implied_probability),
                        edge=edge,
                        confidence=confidence,
                        size_usd=10.0,
                    )
                except Exception as _ae:
                    logger.warning(f"Failed to send Telegram paper trade alert for {market.market_id}: {_ae}")

            try:
                if self._db:
                    _save_paper(self._db)
                    self._db.commit()
                else:
                    with get_db_context() as db:
                        _save_paper(db)
            except Exception as e:
                logger.error(
                    f"Failed to save paper trade for market {market.market_id}: {e}"
                )

    def _save_decision(
        self,
        market: Market,
        action: ActionEnum,
        size: float,
        ev: float,
        risk_score: float,
        reason: str,
    ) -> Optional[RiskDecision]:
        """Persist a RiskDecision to the database."""
        decision = RiskDecision(
            market_id=market.id,
            action=action,
            recommended_size=size,
            ev=ev,
            risk_score=risk_score,
            reason=reason,
            price_at_decision=float(market.current_price),
        )

        def _save(db: Session) -> RiskDecision:
            db.add(decision)
            db.flush()
            db.refresh(decision)
            return decision

        try:
            if self._db:
                saved = _save(self._db)
                self._db.commit()
            else:
                with get_db_context() as db:
                    saved = _save(db)

            logger.info(
                f"RiskAgent: saved decision {saved.id} — "
                f"action={saved.action}, size=${saved.recommended_size:.2f}"
            )
            return saved
        except Exception as e:
            logger.error(
                f"Failed to save risk decision for market {market.market_id}: {e}"
            )
            return None

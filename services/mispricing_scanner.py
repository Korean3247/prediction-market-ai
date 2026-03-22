"""
Real-time mispricing scanner.

Two independent reference signals are checked on every WebSocket tick:

  1. LLM/ML predicted probability (from DB) vs live price
  2. Cross-platform price (Kalshi / Metaculus) vs live Polymarket price
     — uses the most recent ArbOpportunity records, so no extra API calls.

Fires instant Telegram alerts when either gap exceeds MISPRICING_MIN_EDGE.
No LLM calls — pure math, runs in milliseconds per event.

Usage:
    from services.mispricing_scanner import check_mispricing, get_market_title
    edge = check_mispricing(asset_id, live_price)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from config import settings
from database.session import get_db_context
from database.models import ArbOpportunity, Market, Prediction
from services.alert_service import alert_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache 1: LLM/ML predictions
# {condition_id: (predicted_prob, market_title, url, cached_at)}
# ---------------------------------------------------------------------------
_pred_cache: Dict[str, Tuple[float, str, str, datetime]] = {}

# ---------------------------------------------------------------------------
# Cache 2: Cross-platform reference prices from ArbOpportunity table
# {condition_id: (cross_price, cross_platform, cached_at)}
# ---------------------------------------------------------------------------
_cross_cache: Dict[str, Tuple[float, str, datetime]] = {}

_CACHE_TTL_SECONDS = 600       # refresh both caches every 10 min
_last_cache_refresh = datetime.min

# Cooldown: {condition_id: last_alert_time} — one dict covers both signals
_alert_cooldown: Dict[str, datetime] = {}


# ---------------------------------------------------------------------------
# Cache refresh
# ---------------------------------------------------------------------------

def _refresh_cache() -> None:
    """Reload prediction cache and cross-platform cache from DB."""
    global _last_cache_refresh
    now = datetime.utcnow()
    if (now - _last_cache_refresh).total_seconds() < _CACHE_TTL_SECONDS:
        return

    _refresh_pred_cache(now)
    _refresh_cross_cache(now)
    _last_cache_refresh = now


def _refresh_pred_cache(now: datetime) -> None:
    """Load most recent LLM/ML prediction per active Polymarket market."""
    try:
        with get_db_context() as db:
            from sqlalchemy import func

            subq = (
                db.query(
                    Prediction.market_id,
                    func.max(Prediction.created_at).label("max_ts"),
                )
                .group_by(Prediction.market_id)
                .subquery()
            )

            rows = (
                db.query(Prediction, Market)
                .join(
                    subq,
                    (Prediction.market_id == subq.c.market_id)
                    & (Prediction.created_at == subq.c.max_ts),
                )
                .join(Market, Market.id == Prediction.market_id)
                .filter(Market.platform == "polymarket")
                .filter(Market.status == "active")
                .all()
            )

            new_cache: Dict[str, Tuple[float, str, str, datetime]] = {}
            for pred, market in rows:
                if market.market_id.startswith("polymarket_"):
                    cid = market.market_id[len("polymarket_"):]
                    new_cache[cid] = (
                        float(pred.predicted_probability),
                        market.title,
                        market.url or "",
                        now,
                    )

            _pred_cache.clear()
            _pred_cache.update(new_cache)
            logger.debug(
                f"[MispricingScanner] Pred cache refreshed: {len(_pred_cache)} markets."
            )

    except Exception as e:
        logger.error(f"[MispricingScanner] Pred cache refresh failed: {e}")


def _refresh_cross_cache(now: datetime) -> None:
    """
    Load recent ArbOpportunity records to extract cross-platform reference prices.

    For each arb pair involving Polymarket, the other platform's price becomes
    an independent "fair value" reference — no extra API calls needed.
    """
    try:
        one_hour_ago = now - timedelta(hours=1)
        with get_db_context() as db:
            arbs = (
                db.query(ArbOpportunity)
                .filter(ArbOpportunity.created_at >= one_hour_ago)
                .all()
            )

            new_cross: Dict[str, Tuple[float, str, datetime]] = {}
            for arb in arbs:
                # Resolve which side is Polymarket
                ma_platform = arb.platform_a
                mb_platform = arb.platform_b

                if ma_platform == "polymarket" and mb_platform != "polymarket":
                    # market_a is Polymarket; reference = market_b's price
                    poly_market_id = arb.market_id_a
                    cross_price = float(arb.price_b)
                    cross_platform = mb_platform
                elif mb_platform == "polymarket" and ma_platform != "polymarket":
                    poly_market_id = arb.market_id_b
                    cross_price = float(arb.price_a)
                    cross_platform = ma_platform
                else:
                    continue  # no Polymarket side

                # Resolve condition_id from DB id via pred_cache keys (cheap lookup)
                # We need the condition_id string; get it via the Market table
                market = db.query(Market).filter(Market.id == poly_market_id).first()
                if market and market.market_id.startswith("polymarket_"):
                    cid = market.market_id[len("polymarket_"):]
                    # Keep the most recent entry per market
                    existing = new_cross.get(cid)
                    if existing is None or arb.created_at > existing[2]:
                        new_cross[cid] = (cross_price, cross_platform, now)

            _cross_cache.clear()
            _cross_cache.update(new_cross)
            logger.debug(
                f"[MispricingScanner] Cross cache refreshed: {len(_cross_cache)} markets."
            )

    except Exception as e:
        logger.error(f"[MispricingScanner] Cross cache refresh failed: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_on_cooldown(asset_id: str) -> bool:
    last = _alert_cooldown.get(asset_id)
    if last is None:
        return False
    return (datetime.utcnow() - last).total_seconds() < settings.MISPRICING_ALERT_COOLDOWN_SECONDS


def get_market_title(asset_id: str) -> Optional[str]:
    """Return cached market title for a given Polymarket condition_id, or None."""
    _refresh_cache()
    entry = _pred_cache.get(asset_id)
    return entry[1] if entry else None


def get_market_url(asset_id: str) -> str:
    _refresh_cache()
    entry = _pred_cache.get(asset_id)
    return entry[2] if entry else ""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def check_mispricing(asset_id: str, live_price: float) -> Optional[float]:
    """
    Check live WebSocket price against two independent reference signals:
      1. LLM/ML prediction stored in DB
      2. Cross-platform price (Kalshi / Metaculus) from recent ArbOpportunity records

    Returns the largest edge found (or None).
    Fires Telegram alert on the first significant signal per cooldown window.

    Called on every WebSocket tick — must be fast (no I/O unless cache is stale).
    """
    _refresh_cache()

    best_edge: Optional[float] = None
    alerted = False

    # --- Signal 1: LLM/ML prediction vs live price ---
    pred_entry = _pred_cache.get(asset_id)
    if pred_entry:
        predicted_prob, title, url, cached_at = pred_entry
        age = (datetime.utcnow() - cached_at).total_seconds()
        if age <= 7200:  # ignore predictions older than 2 h
            edge = predicted_prob - live_price
            if abs(edge) >= settings.MISPRICING_MIN_EDGE and not _is_on_cooldown(asset_id):
                direction = "YES underpriced" if edge > 0 else "YES overpriced"
                logger.info(
                    f"[MispricingScanner] LLM edge on {asset_id[:16]}: "
                    f"pred={predicted_prob:.3f} live={live_price:.3f} edge={edge:+.3f}"
                )
                _alert_cooldown[asset_id] = datetime.utcnow()
                try:
                    alert_service.send_mispricing_alert(
                        market_title=title,
                        asset_id=asset_id,
                        predicted_prob=predicted_prob,
                        live_price=live_price,
                        edge=edge,
                        direction=f"[ML] {direction}",
                        url=url,
                    )
                except Exception as e:
                    logger.warning(f"[MispricingScanner] Alert failed: {e}")
                best_edge = edge
                alerted = True

    # --- Signal 2: Cross-platform price vs live price ---
    cross_entry = _cross_cache.get(asset_id)
    if cross_entry and not alerted:
        cross_price, cross_platform, _ = cross_entry
        edge = cross_price - live_price
        if abs(edge) >= settings.MISPRICING_MIN_EDGE and not _is_on_cooldown(asset_id):
            title = (pred_entry[1] if pred_entry else asset_id[:40])
            url = (pred_entry[2] if pred_entry else "")
            direction = "YES underpriced vs " + cross_platform if edge > 0 else "YES overpriced vs " + cross_platform
            logger.info(
                f"[MispricingScanner] CROSS-PLATFORM edge on {asset_id[:16]}: "
                f"{cross_platform}={cross_price:.3f} poly={live_price:.3f} edge={edge:+.3f}"
            )
            _alert_cooldown[asset_id] = datetime.utcnow()
            try:
                alert_service.send_mispricing_alert(
                    market_title=title,
                    asset_id=asset_id,
                    predicted_prob=cross_price,
                    live_price=live_price,
                    edge=edge,
                    direction=f"[{cross_platform.upper()}] {direction}",
                    url=url,
                )
            except Exception as e:
                logger.warning(f"[MispricingScanner] Cross alert failed: {e}")
            if best_edge is None or abs(edge) > abs(best_edge):
                best_edge = edge

    return best_edge


def invalidate_cache_for(asset_id: str) -> None:
    """Remove a single entry from caches (call after storing a new prediction)."""
    _pred_cache.pop(asset_id, None)
    _cross_cache.pop(asset_id, None)

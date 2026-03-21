"""
Cross-platform arbitrage detector.

Logic:
  For each pair of platforms, fuzzy-match market titles using Jaccard word
  overlap.  When the same market is priced differently on two platforms:

    Buy YES on the cheaper platform + Buy NO on the other
    = guaranteed payout regardless of outcome

  Profit % = price_high - price_low
  (e.g. Kalshi 45% vs Polymarket 65%  →  20% guaranteed return per dollar)

  We don't execute real trades, but we:
    1. Flag the opportunity in the DB (ArbOpportunity table)
    2. Send a Telegram alert
    3. Log for paper-trade analysis
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from database.models import ArbOpportunity, Market
from database.session import get_db_context
from config import settings

logger = logging.getLogger(__name__)

# Common words to exclude from title comparison
_STOP_WORDS: Set[str] = {
    "will", "the", "a", "an", "in", "on", "at", "to", "of", "and", "or",
    "be", "is", "are", "was", "were", "by", "for", "with", "this", "that",
    "it", "its", "he", "she", "they", "we", "you", "i", "do", "does",
    "did", "has", "have", "had", "can", "could", "would", "should", "may",
    "might", "shall", "yes", "no", "not", "market", "resolve", "before",
    "after", "than", "more", "least", "most", "end", "by", "reach",
}


@dataclass
class ArbSignal:
    market_a: Market
    market_b: Market
    platform_a: str
    platform_b: str
    price_a: float           # YES price on platform A
    price_b: float           # YES price on platform B
    delta: float             # price_high - price_low
    profit_pct: float        # guaranteed profit fraction
    title_similarity: float
    buy_yes_on: str          # which platform to buy YES
    buy_no_on: str           # which platform to buy NO


def _normalize_title(title: str) -> Set[str]:
    """Lowercase, strip punctuation, remove stop words → word set."""
    words = re.sub(r"[^\w\s]", " ", title.lower()).split()
    return {w for w in words if w not in _STOP_WORDS and len(w) > 2}


def _jaccard(set_a: Set[str], set_b: Set[str]) -> float:
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def detect_arb_opportunities(markets: List[Market]) -> List[ArbSignal]:
    """
    Given a list of active Market ORM objects, find cross-platform arb pairs.

    Returns a list of ArbSignal (highest delta first).
    Only markets that resolve within the next 30 days are considered.
    """
    min_delta = settings.ARB_MIN_DELTA
    min_sim = settings.ARB_MIN_TITLE_SIMILARITY
    now = datetime.utcnow()
    cutoff = now + timedelta(days=30)

    # Pre-filter: active markets resolving within 30 days
    eligible = [
        m for m in markets
        if m.status.value == "active"
        and m.current_price is not None
        and (m.resolve_time is None or m.resolve_time <= cutoff)
    ]

    # Group by platform
    by_platform: Dict[str, List[Market]] = {}
    for m in eligible:
        by_platform.setdefault(m.platform, []).append(m)

    platforms = list(by_platform.keys())
    signals: List[ArbSignal] = []
    seen_pairs: Set[Tuple[int, int]] = set()

    # Word sets cache
    word_sets: Dict[int, Set[str]] = {
        m.id: _normalize_title(m.title) for m in eligible
    }

    for i, platform_a in enumerate(platforms):
        for platform_b in platforms[i + 1:]:
            markets_a = by_platform[platform_a]
            markets_b = by_platform[platform_b]

            for ma in markets_a:
                for mb in markets_b:
                    pair = (min(ma.id, mb.id), max(ma.id, mb.id))
                    if pair in seen_pairs:
                        continue

                    sim = _jaccard(word_sets[ma.id], word_sets[mb.id])
                    if sim < min_sim:
                        continue

                    price_a = float(ma.current_price)
                    price_b = float(mb.current_price)
                    delta = abs(price_a - price_b)

                    if delta < min_delta:
                        continue

                    # Arbitrage math:
                    # Buy YES on cheaper + Buy NO on other
                    # Total cost = price_low + (1 - price_high)
                    # Payout = $1 regardless
                    price_low = min(price_a, price_b)
                    price_high = max(price_a, price_b)
                    total_cost = price_low + (1.0 - price_high)
                    if total_cost <= 0:
                        continue
                    profit_pct = (1.0 - total_cost) / total_cost  # ROI

                    if price_a < price_b:
                        buy_yes_on, buy_no_on = platform_a, platform_b
                    else:
                        buy_yes_on, buy_no_on = platform_b, platform_a

                    signals.append(ArbSignal(
                        market_a=ma,
                        market_b=mb,
                        platform_a=platform_a,
                        platform_b=platform_b,
                        price_a=price_a,
                        price_b=price_b,
                        delta=delta,
                        profit_pct=profit_pct,
                        title_similarity=sim,
                        buy_yes_on=buy_yes_on,
                        buy_no_on=buy_no_on,
                    ))
                    seen_pairs.add(pair)

    signals.sort(key=lambda s: s.delta, reverse=True)
    logger.info(
        f"[ArbDetector] Scanned {len(eligible)} markets across "
        f"{len(platforms)} platforms → {len(signals)} arb opportunities found."
    )
    return signals


def save_arb_opportunities(signals: List[ArbSignal]) -> int:
    """
    Persist new ArbOpportunity records.  Skips pairs already recorded
    in the last hour to avoid flooding the DB.
    Returns count of newly saved records.
    """
    if not signals:
        return 0

    saved = 0
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)

    try:
        with get_db_context() as db:
            for sig in signals:
                # Dedup: same market pair within the last hour
                existing = (
                    db.query(ArbOpportunity)
                    .filter(
                        ArbOpportunity.market_id_a == sig.market_a.id,
                        ArbOpportunity.market_id_b == sig.market_b.id,
                        ArbOpportunity.created_at >= one_hour_ago,
                    )
                    .first()
                )
                if existing:
                    # Update delta if improved
                    if sig.delta > existing.delta:
                        existing.delta = sig.delta
                        existing.price_a = sig.price_a
                        existing.price_b = sig.price_b
                        existing.guaranteed_profit_pct = sig.profit_pct
                    continue

                arb = ArbOpportunity(
                    market_id_a=sig.market_a.id,
                    market_id_b=sig.market_b.id,
                    platform_a=sig.platform_a,
                    platform_b=sig.platform_b,
                    price_a=sig.price_a,
                    price_b=sig.price_b,
                    delta=sig.delta,
                    guaranteed_profit_pct=sig.profit_pct,
                    title_similarity=sig.title_similarity,
                    status="open",
                )
                db.add(arb)
                saved += 1

    except Exception as e:
        logger.error(f"[ArbDetector] Failed to save arb opportunities: {e}", exc_info=True)

    logger.info(f"[ArbDetector] Saved {saved} new arb opportunities to DB.")
    return saved

"""
ScanAgent: Discovers, filters, scores, and persists prediction markets.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from config import settings
from database.models import Market, MarketStatus
from database.session import get_db_context
from services.market_fetcher import MarketFetcher

logger = logging.getLogger(__name__)

TOP_N_MARKETS = 20


def _calculate_priority_score(market: Dict[str, Any]) -> float:
    """
    Compute a composite priority score for a market.

    Weights:
        - time_factor:   0.45  (short-term markets prioritized for faster data)
        - liquidity:     0.25
        - volume_24h:    0.20
        - 1/spread:      0.10

    Time scoring: peak at 3-14 days, usable up to 90 days, decay beyond that.
    Markets resolving in 24h-14d score highest for rapid feedback cycles.
    """
    liquidity = market.get("liquidity", 0.0)
    volume = market.get("volume_24h", 0.0)
    spread = max(market.get("spread", 0.05), 0.001)
    resolve_time = market.get("resolve_time")

    # Normalize liquidity (log scale, capped at 1M)
    liq_score = min(1.0, (liquidity / 1_000_000) ** 0.5) if liquidity > 0 else 0.0

    # Normalize volume (log scale, capped at 100K)
    vol_score = min(1.0, (volume / 100_000) ** 0.5) if volume > 0 else 0.0

    # Tighter spread → higher score
    spread_score = min(1.0, 0.05 / spread)

    # Time factor (tiered):
    #   < 6h   → 1.0  (intraday — highest priority for rapid feedback)
    #   6-24h  → 0.85-1.0
    #   1-14d  → 0.4-0.85
    #   14-90d → 0.0-0.4 (decaying)
    time_score = 0.0
    if resolve_time:
        now = datetime.utcnow()
        hours_left = (resolve_time - now).total_seconds() / 3600
        if 0 < hours_left <= 6:
            time_score = 1.0                                           # intraday
        elif hours_left <= 24:
            time_score = 0.85 + 0.15 * (1.0 - (hours_left - 6) / 18) # same-day
        elif hours_left <= 336:
            time_score = 0.40 + 0.45 * (1.0 - (hours_left - 24) / 312)  # 1-14 days
        elif hours_left <= 2160:
            time_score = max(0.0, 0.40 * (1.0 - (hours_left - 336) / (2160 - 336)))

    score = (
        0.45 * time_score
        + 0.25 * liq_score
        + 0.20 * vol_score
        + 0.10 * spread_score
    )
    return round(score, 6)


def _detect_anomalies(new_price: float, existing_market: Optional[Market]) -> Dict[str, Any]:
    """
    Detect price anomalies (jumps > 10%) when comparing to stored price.
    Returns a flags dict to be merged into Market.flags.
    """
    flags: Dict[str, Any] = {}
    if existing_market is None:
        return flags

    old_price = existing_market.current_price or 0.5
    if old_price > 0:
        change = abs(new_price - old_price) / old_price
        if change > 0.10:
            flags["price_jump"] = {
                "old_price": round(old_price, 4),
                "new_price": round(new_price, 4),
                "change_pct": round(change * 100, 2),
                "detected_at": datetime.utcnow().isoformat(),
            }
            logger.info(
                f"Price anomaly detected: {change:.1%} jump "
                f"({old_price:.3f} → {new_price:.3f})"
            )
    return flags


class ScanAgent:
    """
    Discovers markets from all platforms, applies quality filters,
    scores by priority, and persists to the database.
    """

    def __init__(self, db: Optional[Session] = None):
        self.fetcher = MarketFetcher()
        self._db = db

    def _apply_filters(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply configured quality filters to raw market dicts.
        Returns only markets that pass all criteria.
        """
        passed = []
        now = datetime.utcnow()
        min_resolve = now + timedelta(hours=settings.MIN_HOURS_TO_RESOLVE)

        for m in markets:
            platform = m.get("platform", "")
            # Metaculus/Kalshi use proxy liquidity values — apply relaxed thresholds
            if platform in ("metaculus", "kalshi"):
                min_liq = settings.MIN_LIQUIDITY * 0.1
                min_vol = settings.MIN_VOLUME_24H * 0.1
            else:
                min_liq = settings.MIN_LIQUIDITY
                min_vol = settings.MIN_VOLUME_24H

            # Liquidity filter
            if m.get("liquidity", 0) < min_liq:
                logger.debug(
                    f"Filtered (liquidity) {m.get('market_id')}: "
                    f"{m.get('liquidity', 0):.0f} < {min_liq}"
                )
                continue

            # Volume filter
            if m.get("volume_24h", 0) < min_vol:
                logger.debug(
                    f"Filtered (volume) {m.get('market_id')}: "
                    f"{m.get('volume_24h', 0):.0f} < {min_vol}"
                )
                continue

            # Spread filter
            if m.get("spread", 1.0) > settings.MAX_SPREAD:
                logger.debug(
                    f"Filtered (spread) {m.get('market_id')}: "
                    f"{m.get('spread', 0):.3f} > {settings.MAX_SPREAD}"
                )
                continue

            # Resolve time filter
            resolve_time = m.get("resolve_time")
            if resolve_time and resolve_time < min_resolve:
                logger.debug(
                    f"Filtered (resolve_time) {m.get('market_id')}: "
                    f"resolves too soon at {resolve_time}"
                )
                continue

            passed.append(m)

        logger.info(f"Filters: {len(markets)} raw → {len(passed)} passed.")
        return passed

    def _upsert_market(
        self, db: Session, market_data: Dict[str, Any]
    ) -> Market:
        """
        Insert or update a Market record in the database.
        Returns the persisted Market ORM object.
        """
        existing = (
            db.query(Market)
            .filter(Market.market_id == market_data["market_id"])
            .first()
        )

        new_price = float(market_data.get("current_price", 0.5))
        priority = _calculate_priority_score(market_data)
        flags = _detect_anomalies(new_price, existing)

        if existing:
            existing.title = market_data.get("title", existing.title)
            existing.description = market_data.get("description", existing.description)
            existing.category = market_data.get("category", existing.category)
            existing.current_price = new_price
            existing.liquidity = float(market_data.get("liquidity", 0))
            existing.volume_24h = float(market_data.get("volume_24h", 0))
            existing.spread = float(market_data.get("spread", 0))
            existing.resolve_time = market_data.get("resolve_time")
            existing.priority_score = priority
            existing.url = market_data.get("url", existing.url)
            existing.updated_at = datetime.utcnow()
            if flags:
                existing_flags = existing.flags or {}
                existing_flags.update(flags)
                existing.flags = existing_flags
            return existing
        else:
            market = Market(
                market_id=market_data["market_id"],
                title=market_data.get("title", ""),
                description=market_data.get("description", ""),
                category=market_data.get("category", ""),
                platform=market_data.get("platform", "unknown"),
                current_price=new_price,
                liquidity=float(market_data.get("liquidity", 0)),
                volume_24h=float(market_data.get("volume_24h", 0)),
                spread=float(market_data.get("spread", 0)),
                resolve_time=market_data.get("resolve_time"),
                priority_score=priority,
                flags=flags,
                status=MarketStatus.ACTIVE,
                url=market_data.get("url"),
            )
            db.add(market)
            return market

    def scan_markets(self, short_term_only: bool = False) -> List[Market]:
        """
        Main entry point: fetch → filter → score → persist → return top N.

        If short_term_only=True, further filters to markets resolving within
        settings.FAST_PIPELINE_HOURS hours and returns only the top 10 of those.

        Returns the top TOP_N_MARKETS Market objects by priority_score
        (or top 10 when short_term_only=True).
        """
        logger.info(
            f"ScanAgent: starting market scan"
            f"{' (short-term only)' if short_term_only else ''}."
        )

        raw_markets = self.fetcher.fetch_all_markets()
        if not raw_markets:
            logger.warning("No markets fetched from any platform.")
            return []

        filtered = self._apply_filters(raw_markets)
        if not filtered:
            logger.warning("No markets passed filters.")
            return []

        # Apply short-term filter: only markets resolving within FAST_PIPELINE_HOURS
        if short_term_only:
            now = datetime.utcnow()
            cutoff = now + timedelta(hours=settings.FAST_PIPELINE_HOURS)
            filtered = [
                m for m in filtered
                if m.get("resolve_time") and m["resolve_time"] <= cutoff
            ]
            logger.info(
                f"ScanAgent: short-term filter applied — {len(filtered)} markets within "
                f"{settings.FAST_PIPELINE_HOURS}h."
            )

        if not filtered:
            logger.warning("No markets remained after short-term filter.")
            return []

        # Sort by priority score before DB write for efficiency
        filtered.sort(key=_calculate_priority_score, reverse=True)

        db_markets: List[Market] = []

        def _run(db: Session) -> None:
            for market_data in filtered:
                try:
                    with db.begin_nested():  # savepoint per market — rollback only this one on error
                        m = self._upsert_market(db, market_data)
                    db_markets.append(m)
                except Exception as e:
                    logger.error(
                        f"Error upserting market {market_data.get('market_id')}: {e}"
                    )
                    continue

        if self._db:
            _run(self._db)
            self._db.flush()
            for m in db_markets:
                self._db.expunge(m)
        else:
            with get_db_context() as db:
                _run(db)
                db.flush()
                for m in db_markets:
                    db.expunge(m)

        # Sort in-memory and return top N (session already closed — use cached priority_score)
        db_markets.sort(key=lambda m: m.__dict__.get('priority_score') or 0, reverse=True)
        limit = 10 if short_term_only else TOP_N_MARKETS
        top = db_markets[:limit]

        logger.info(
            f"ScanAgent: scan complete. "
            f"{len(filtered)} markets processed, returning top {len(top)}."
        )
        return top

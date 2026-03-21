"""
Market data fetcher for Manifold Markets, Polymarket, and Kalshi APIs.
Returns normalized market dicts suitable for DB ingestion.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from services.kalshi_fetcher import KalshiFetcher
from services.metaculus_fetcher import MetaculusFetcher

logger = logging.getLogger(__name__)

MANIFOLD_API_URL = "https://api.manifold.markets/v0/markets"
POLYMARKET_API_URL = "https://gamma-api.polymarket.com/markets"

REQUEST_TIMEOUT = 15  # seconds


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float safely."""
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Parse various datetime formats to UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Unix timestamp in milliseconds or seconds
        ts = value / 1000 if value > 1e10 else value
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    if isinstance(value, str):
        for fmt in (
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


class MarketFetcher:
    """
    Fetches and normalizes prediction market data from multiple platforms.
    All methods return empty lists on error rather than raising exceptions.
    """

    def fetch_manifold_markets(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch markets from Manifold Markets API.
        Endpoint: GET https://api.manifold.markets/v0/markets
        No authentication required.
        """
        try:
            params = {"limit": limit, "sort": "liquidity", "order": "desc"}
            resp = requests.get(
                MANIFOLD_API_URL, params=params, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            raw_markets = resp.json()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch Manifold markets: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching Manifold markets: {e}")
            return []

        normalized = []
        for m in raw_markets:
            try:
                # Skip non-binary markets that don't have a simple 0-1 price
                if m.get("outcomeType") not in ("BINARY", "PSEUDO_NUMERIC"):
                    continue

                # current probability 0-1
                prob = _safe_float(m.get("probability", m.get("p", 0.5)))
                prob = max(0.01, min(0.99, prob))

                # Manifold uses 'totalLiquidity' and 'volume24Hours'
                liquidity = _safe_float(m.get("totalLiquidity", 0))
                volume_24h = _safe_float(m.get("volume24Hours", 0))

                # Spread not directly provided – estimate from liquidity
                spread = 0.02 if liquidity > 5000 else 0.05

                resolve_time = _parse_datetime(m.get("closeTime"))

                normalized.append(
                    {
                        "market_id": f"manifold_{m['id']}",
                        "title": m.get("question", ""),
                        "description": m.get("description", ""),
                        "category": m.get("category", ""),
                        "platform": "manifold",
                        "current_price": prob,
                        "liquidity": liquidity,
                        "volume_24h": volume_24h,
                        "spread": spread,
                        "resolve_time": resolve_time,
                        "url": m.get("url", f"https://manifold.markets/{m.get('slug', m['id'])}"),
                    }
                )
            except Exception as e:
                logger.debug(f"Skipping malformed Manifold market {m.get('id')}: {e}")
                continue

        logger.info(f"Fetched {len(normalized)} markets from Manifold Markets.")
        return normalized

    def fetch_polymarket_markets(self, max_markets: int = 500) -> List[Dict[str, Any]]:
        """
        Fetch markets from Polymarket Gamma API with pagination.
        Endpoint: GET https://gamma-api.polymarket.com/markets
        Supports limit/offset pagination. Fetches up to max_markets total.
        No authentication required.
        """
        import time as _time
        page_limit = 100
        all_raw: List[Dict[str, Any]] = []

        for page in range(max_markets // page_limit):
            offset = page * page_limit
            try:
                params = {
                    "active": "true",
                    "closed": "false",
                    "limit": page_limit,
                    "offset": offset,
                }
                resp = requests.get(
                    POLYMARKET_API_URL, params=params, timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                data = resp.json()
                # API may return {"data": [...]} or a plain list
                page_markets = data.get("data", data) if isinstance(data, dict) else data
                if not page_markets:
                    logger.debug(f"Polymarket pagination: no more markets at offset {offset}")
                    break
                all_raw.extend(page_markets)
                logger.debug(f"Polymarket page {page + 1}: fetched {len(page_markets)} markets (total so far: {len(all_raw)})")
                if len(page_markets) < page_limit:
                    # Last page
                    break
                _time.sleep(0.3)  # be polite to the API
            except requests.RequestException as e:
                logger.warning(f"Failed to fetch Polymarket markets at offset {offset}: {e}")
                break
            except Exception as e:
                logger.error(f"Unexpected error fetching Polymarket markets at offset {offset}: {e}")
                break

        raw_markets = all_raw

        normalized = []
        for m in raw_markets:
            try:
                market_id = str(m.get("id", m.get("condition_id", "")))
                if not market_id:
                    continue

                # Gamma API: outcomePrices is a JSON string like '["0.95", "0.05"]'
                outcome_prices = m.get("outcomePrices")
                if isinstance(outcome_prices, str):
                    import json as _json
                    try:
                        prices = _json.loads(outcome_prices)
                        price = _safe_float(prices[0]) if prices else 0.5
                    except Exception:
                        price = 0.5
                else:
                    price = _safe_float(m.get("bestBid", m.get("lastTradePrice", 0.5)))

                price = max(0.01, min(0.99, price))

                # Spread from bestBid/bestAsk or default
                best_bid = _safe_float(m.get("bestBid", price - 0.02))
                best_ask = _safe_float(m.get("bestAsk", price + 0.02))
                spread = max(0.0, best_ask - best_bid)
                if spread == 0.0:
                    spread = 0.04

                liquidity = _safe_float(m.get("liquidity", 0))
                volume_24h = _safe_float(m.get("volume24hr", m.get("volume24h", 0)))
                resolve_time = _parse_datetime(
                    m.get("endDate", m.get("end_date_iso", m.get("end_date")))
                )
                slug = m.get("slug", market_id)

                normalized.append(
                    {
                        "market_id": f"polymarket_{market_id}",
                        "title": m.get("question", m.get("title", "")),
                        "description": m.get("description", ""),
                        "category": m.get("category", ""),
                        "platform": "polymarket",
                        "current_price": price,
                        "liquidity": liquidity,
                        "volume_24h": volume_24h,
                        "spread": spread,
                        "resolve_time": resolve_time,
                        "url": f"https://polymarket.com/event/{slug}",
                    }
                )
            except Exception as e:
                logger.debug(f"Skipping malformed Polymarket market {m.get('id')}: {e}")
                continue

        logger.info(f"Fetched {len(normalized)} markets from Polymarket.")
        return normalized

    def fetch_all_markets(self) -> List[Dict[str, Any]]:
        """
        Fetch markets from all configured platforms and return combined list.
        Individual platform failures do not prevent other platforms from being fetched.
        """
        from config import settings

        all_markets: List[Dict[str, Any]] = []

        manifold = self.fetch_manifold_markets()
        all_markets.extend(manifold)

        polymarket = self.fetch_polymarket_markets()
        all_markets.extend(polymarket)

        kalshi_fetcher = KalshiFetcher(
            api_key_id=settings.KALSHI_API_KEY or "",
            private_key_path=settings.KALSHI_PRIVATE_KEY_PATH,
        )
        kalshi = kalshi_fetcher.fetch_markets()
        all_markets.extend(kalshi)

        metaculus_fetcher = MetaculusFetcher(api_token=settings.METACULUS_API_TOKEN or "")
        metaculus = metaculus_fetcher.fetch_markets()
        all_markets.extend(metaculus)

        logger.info(
            f"Total markets fetched: {len(all_markets)} "
            f"(manifold={len(manifold)}, polymarket={len(polymarket)}, "
            f"kalshi={len(kalshi)}, metaculus={len(metaculus)})"
        )
        return all_markets

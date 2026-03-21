"""
Kalshi market fetcher using RSA key authentication.
Kalshi is a US-regulated prediction market exchange.
"""

import base64
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"
REQUEST_TIMEOUT = 15


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


class KalshiFetcher:
    """
    Fetches markets from Kalshi using RSA key-based authentication.
    """

    def __init__(self, api_key_id: str, private_key_path: str):
        self.api_key_id = api_key_id
        self.private_key = None
        self.enabled = False

        if not api_key_id or not private_key_path:
            logger.info("Kalshi API key or private key path not configured.")
            return

        if not os.path.exists(private_key_path):
            logger.warning(f"Kalshi private key file not found: {private_key_path}")
            return

        try:
            with open(private_key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(f.read(), password=None)
            self.enabled = True
            logger.info("Kalshi fetcher initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to load Kalshi private key: {e}")

    def _sign_request(self, method: str, full_path: str) -> Dict[str, str]:
        """Generate RSA-signed authentication headers for Kalshi API.
        full_path should be the complete URL path e.g. /trade-api/v2/markets
        """
        timestamp_ms = str(int(time.time() * 1000))
        message = timestamp_ms + method.upper() + full_path
        signature = self.private_key.sign(
            message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: Dict = None) -> Optional[Dict]:
        """Make authenticated GET request to Kalshi API."""
        full_path = f"/trade-api/v2{path}"
        headers = self._sign_request("GET", full_path)
        url = f"{KALSHI_API_BASE}{path}"
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning(f"Kalshi API request failed: {e}")
            return None

    def fetch_markets(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Fetch active binary markets from Kalshi."""
        if not self.enabled:
            return []

        all_markets = []
        cursor = None
        page_size = 100

        for _ in range(limit // page_size + 1):
            params = {"limit": page_size, "status": "open"}
            if cursor:
                params["cursor"] = cursor

            data = self._get("/markets", params=params)
            if not data:
                break

            markets = data.get("markets", [])
            if not markets:
                break

            all_markets.extend(markets)
            cursor = data.get("cursor")
            if not cursor or len(all_markets) >= limit:
                break
            time.sleep(0.2)

        normalized = []
        for m in all_markets:
            try:
                # Only binary (yes/no) markets
                if m.get("market_type") not in ("binary", "yes_no"):
                    ticker = m.get("ticker", "")
                    # Kalshi tickers for binary markets often end in -YES
                    if not ticker.endswith("-YES") and m.get("market_type") not in (None, "binary"):
                        continue

                # Price: yes_bid or last_price, 0-1 scale (Kalshi uses cents 0-100)
                yes_bid = _safe_float(m.get("yes_bid", 0)) / 100
                yes_ask = _safe_float(m.get("yes_ask", 0)) / 100
                last_price = _safe_float(m.get("last_price", 0)) / 100

                price = yes_bid if yes_bid > 0 else last_price
                price = max(0.01, min(0.99, price)) if price > 0 else 0.5

                spread = max(0.0, yes_ask - yes_bid) if yes_ask > 0 and yes_bid > 0 else 0.04

                liquidity = _safe_float(m.get("open_interest", 0))
                volume_24h = _safe_float(m.get("volume_24h", m.get("volume", 0)))
                resolve_time = _parse_datetime(m.get("close_time", m.get("expected_expiration_time")))

                ticker = m.get("ticker", "")
                title = m.get("title", m.get("subtitle", ticker))

                normalized.append({
                    "market_id": f"kalshi_{ticker}",
                    "title": title,
                    "description": m.get("rules_primary", ""),
                    "category": m.get("category", ""),
                    "platform": "kalshi",
                    "current_price": price,
                    "liquidity": liquidity,
                    "volume_24h": volume_24h,
                    "spread": spread,
                    "resolve_time": resolve_time,
                    "url": f"https://kalshi.com/markets/{ticker}",
                })
            except Exception as e:
                logger.debug(f"Skipping malformed Kalshi market {m.get('ticker')}: {e}")
                continue

        logger.info(f"Fetched {len(normalized)} markets from Kalshi.")
        return normalized

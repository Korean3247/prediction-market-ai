"""
Metaculus market fetcher.
Metaculus is a forecasting platform with high-quality binary questions.
Community predictions are often hidden; LLM will provide independent analysis.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

METACULUS_API_BASE = "https://www.metaculus.com/api2"
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


class MetaculusFetcher:
    """
    Fetches binary questions from Metaculus API.
    """

    def __init__(self, api_token: str):
        self.api_token = api_token
        self.enabled = bool(api_token)
        self.headers = {
            "Authorization": f"Token {api_token}",
            "Content-Type": "application/json",
        }
        if self.enabled:
            logger.info("Metaculus fetcher initialized.")

    def fetch_markets(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Fetch active binary questions from Metaculus."""
        if not self.enabled:
            return []

        all_questions = []
        page_size = 100
        offset = 0

        while len(all_questions) < limit:
            params = {
                "limit": min(page_size, limit - len(all_questions)),
                "offset": offset,
                "format": "json",
                "type": "binary",
                "status": "open",
                "order_by": "-nr_forecasters",
            }
            try:
                resp = requests.get(
                    f"{METACULUS_API_BASE}/questions/",
                    headers=self.headers,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                logger.warning(f"Metaculus API request failed: {e}")
                break

            results = data.get("results", [])
            if not results:
                break

            all_questions.extend(results)
            if not data.get("next"):
                break

            offset += page_size
            time.sleep(0.2)

        normalized = []
        for q in all_questions:
            try:
                qs = q.get("question", {}) or {}

                # 커뮤니티 예측 추출 (공개된 경우)
                price = 0.5  # 기본값
                agg = qs.get("aggregations", {}) or {}
                for agg_type in ("recency_weighted", "unweighted"):
                    latest = (agg.get(agg_type) or {}).get("latest")
                    if latest:
                        mean = latest.get("means") or latest.get("forecast_values")
                        if mean and isinstance(mean, list) and len(mean) > 0:
                            price = _safe_float(mean[0])
                            break
                        elif isinstance(mean, (int, float)):
                            price = _safe_float(mean)
                            break

                # community_weighted_mean 직접 필드
                cwm = qs.get("community_weighted_mean")
                if cwm is not None:
                    price = _safe_float(cwm)

                price = max(0.01, min(0.99, price))

                title = q.get("title", q.get("short_title", ""))
                slug = q.get("slug", str(q.get("id", "")))
                resolve_time = _parse_datetime(
                    qs.get("scheduled_resolve_time", q.get("scheduled_resolve_time"))
                )
                nr_forecasters = q.get("nr_forecasters", 0) or 0

                # 예측자 수를 유동성 프록시로 사용
                liquidity = float(nr_forecasters) * 10
                volume_24h = liquidity * 0.1

                # 카테고리
                category = ""
                projects = q.get("projects", {}) or {}
                cats = projects.get("category", []) or []
                if cats:
                    category = cats[0].get("name", "") if isinstance(cats[0], dict) else str(cats[0])

                normalized.append({
                    "market_id": f"metaculus_{q['id']}",
                    "title": title,
                    "description": "",
                    "category": category,
                    "platform": "metaculus",
                    "current_price": price,
                    "liquidity": liquidity,
                    "volume_24h": volume_24h,
                    "spread": 0.04,
                    "resolve_time": resolve_time,
                    "url": f"https://www.metaculus.com/questions/{q['id']}/{slug}/",
                })
            except Exception as e:
                logger.debug(f"Skipping malformed Metaculus question {q.get('id')}: {e}")
                continue

        logger.info(f"Fetched {len(normalized)} markets from Metaculus.")
        return normalized

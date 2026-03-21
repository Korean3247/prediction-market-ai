"""
Real-time price monitor using Polymarket's WebSocket feed.

Polymarket CLOB WebSocket:
  wss://ws-subscriptions-clob.polymarket.com/ws/market

Subscribe message:
  {"assets_ids": ["<condition_id>", ...], "type": "market"}

On each price update:
  1. Update the market's current_price in DB.
  2. If price moved >= REALTIME_PRICE_CHANGE_THRESHOLD → set price_jump flag
     so the fast pipeline picks it up immediately on its next run.

This runs as a background asyncio task started from main.py.
Reconnects automatically on disconnect.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Optional

from config import settings
from database.session import get_db_context
from database.models import Market

logger = logging.getLogger(__name__)

_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
_BATCH_SIZE = 50          # subscribe up to 50 markets at a time
_RECONNECT_DELAY = 10     # seconds between reconnect attempts
_REFRESH_INTERVAL = 300   # re-fetch tracked condition IDs every 5 minutes


def _get_tracked_condition_ids() -> Dict[str, int]:
    """
    Fetch active Polymarket market condition_ids from DB.
    Returns {condition_id: db_row_id}.
    """
    result: Dict[str, int] = {}
    try:
        with get_db_context() as db:
            markets = (
                db.query(Market)
                .filter(
                    Market.platform == "polymarket",
                    Market.status == "active",  # type: ignore[arg-type]
                )
                .all()
            )
            for m in markets:
                # market_id format: "polymarket_{condition_id}"
                if m.market_id.startswith("polymarket_"):
                    cid = m.market_id[len("polymarket_"):]
                    result[cid] = m.id
    except Exception as e:
        logger.error(f"[RealtimeMonitor] Failed to fetch tracked markets: {e}")
    return result


def _update_market_price(db_id: int, new_price: float, old_price: Optional[float]) -> None:
    """Update market price and set price_jump flag if move is significant."""
    threshold = settings.REALTIME_PRICE_CHANGE_THRESHOLD
    try:
        with get_db_context() as db:
            market = db.query(Market).filter(Market.id == db_id).first()
            if not market:
                return

            prev = float(market.current_price) if market.current_price else new_price
            change = abs(new_price - prev) / max(prev, 0.01)

            market.current_price = new_price
            market.updated_at = datetime.utcnow()

            if change >= threshold:
                flags = dict(market.flags or {})
                flags["price_jump"] = {
                    "old": round(prev, 4),
                    "new": round(new_price, 4),
                    "change_pct": round(change * 100, 2),
                    "detected_at": datetime.utcnow().isoformat(),
                    "source": "realtime_ws",
                }
                market.flags = flags
                logger.info(
                    f"[RealtimeMonitor] Price jump on market {market.market_id}: "
                    f"{prev:.3f} → {new_price:.3f} ({change:.1%})"
                )
    except Exception as e:
        logger.debug(f"[RealtimeMonitor] Price update error for id={db_id}: {e}")


async def _subscribe_and_listen(ws, condition_ids: list[str]) -> None:
    """Subscribe to a batch of condition IDs and process incoming messages."""
    sub_msg = json.dumps({"assets_ids": condition_ids, "type": "market"})
    await ws.send(sub_msg)
    logger.debug(f"[RealtimeMonitor] Subscribed to {len(condition_ids)} markets.")

    async for raw in ws:
        try:
            msg = json.loads(raw)
            if not isinstance(msg, list):
                msg = [msg]

            for event in msg:
                asset_id = event.get("asset_id") or event.get("market")
                if not asset_id:
                    continue

                # Extract best mid price
                best_bid = event.get("best_bid")
                best_ask = event.get("best_ask")
                last_price = event.get("last_trade_price")

                if best_bid and best_ask:
                    try:
                        price = (float(best_bid) + float(best_ask)) / 2.0
                    except (TypeError, ValueError):
                        continue
                elif last_price:
                    try:
                        price = float(last_price)
                    except (TypeError, ValueError):
                        continue
                else:
                    continue

                price = max(0.01, min(0.99, price))

                # Look up the DB id from our tracking dict (passed via closure)
                # We'll handle this via the outer loop
                yield asset_id, price

        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.debug(f"[RealtimeMonitor] Message parse error: {e}")


async def _run_monitor_loop() -> None:
    """
    Main WebSocket loop.  Connects, subscribes to all tracked Polymarket markets,
    processes price updates, and reconnects on failure.
    """
    try:
        import websockets
    except ImportError:
        logger.error(
            "[RealtimeMonitor] 'websockets' package not installed. "
            "Run: pip install websockets"
        )
        return

    logger.info("[RealtimeMonitor] Starting Polymarket WebSocket monitor.")

    tracked: Dict[str, int] = {}
    last_refresh = datetime.utcnow()

    while True:
        try:
            # Refresh tracked markets on startup and every _REFRESH_INTERVAL seconds
            now = datetime.utcnow()
            if not tracked or (now - last_refresh).seconds >= _REFRESH_INTERVAL:
                tracked = _get_tracked_condition_ids()
                last_refresh = now
                logger.info(
                    f"[RealtimeMonitor] Tracking {len(tracked)} Polymarket markets."
                )

            if not tracked:
                logger.info(
                    "[RealtimeMonitor] No active Polymarket markets to track. "
                    f"Retrying in {_RECONNECT_DELAY}s."
                )
                await asyncio.sleep(_RECONNECT_DELAY)
                continue

            condition_ids = list(tracked.keys())

            async with websockets.connect(
                _WS_URL,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                logger.info(
                    f"[RealtimeMonitor] Connected to {_WS_URL}. "
                    f"Subscribing to {len(condition_ids)} markets in batches of {_BATCH_SIZE}."
                )

                # Subscribe in batches
                for i in range(0, len(condition_ids), _BATCH_SIZE):
                    batch = condition_ids[i : i + _BATCH_SIZE]
                    sub_msg = json.dumps({"assets_ids": batch, "type": "market"})
                    await ws.send(sub_msg)

                # Listen for updates
                async for raw in ws:
                    # Refresh tracking dict periodically without reconnecting
                    if (datetime.utcnow() - last_refresh).seconds >= _REFRESH_INTERVAL:
                        new_tracked = _get_tracked_condition_ids()
                        # Subscribe to any newly added markets
                        new_ids = set(new_tracked) - set(tracked)
                        if new_ids:
                            for i in range(0, len(list(new_ids)), _BATCH_SIZE):
                                batch = list(new_ids)[i : i + _BATCH_SIZE]
                                sub_msg = json.dumps({"assets_ids": batch, "type": "market"})
                                await ws.send(sub_msg)
                            logger.info(
                                f"[RealtimeMonitor] Added {len(new_ids)} new markets to subscription."
                            )
                        tracked = new_tracked
                        last_refresh = datetime.utcnow()

                    try:
                        msg = json.loads(raw)
                        events = msg if isinstance(msg, list) else [msg]

                        for event in events:
                            asset_id = event.get("asset_id") or event.get("market", "")
                            if not asset_id or asset_id not in tracked:
                                continue

                            best_bid = event.get("best_bid")
                            best_ask = event.get("best_ask")
                            last_price = event.get("last_trade_price")

                            if best_bid and best_ask:
                                try:
                                    price = (float(best_bid) + float(best_ask)) / 2.0
                                except (TypeError, ValueError):
                                    continue
                            elif last_price:
                                try:
                                    price = float(last_price)
                                except (TypeError, ValueError):
                                    continue
                            else:
                                continue

                            price = max(0.01, min(0.99, price))
                            db_id = tracked[asset_id]
                            # Run price update in thread pool to avoid blocking event loop
                            await asyncio.get_event_loop().run_in_executor(
                                None, _update_market_price, db_id, price, None
                            )

                    except json.JSONDecodeError:
                        pass
                    except Exception as e:
                        logger.debug(f"[RealtimeMonitor] Event processing error: {e}")

        except Exception as e:
            logger.warning(
                f"[RealtimeMonitor] WebSocket disconnected ({e}). "
                f"Reconnecting in {_RECONNECT_DELAY}s..."
            )
            await asyncio.sleep(_RECONNECT_DELAY)


async def start_realtime_monitor() -> None:
    """Entry point: launch the monitor loop as an asyncio background task."""
    if not settings.REALTIME_ENABLED:
        logger.info("[RealtimeMonitor] Disabled via REALTIME_ENABLED=false.")
        return

    asyncio.ensure_future(_run_monitor_loop())
    logger.info("[RealtimeMonitor] Background task launched.")

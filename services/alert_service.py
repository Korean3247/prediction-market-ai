"""
Telegram alert service for BUY signals and important events.
Sends alerts when action='buy' decisions are made.
Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
"""
import logging
import requests
from typing import Optional
from config import settings

logger = logging.getLogger(__name__)

class AlertService:
    def __init__(self):
        self.enabled = bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)
        if not self.enabled:
            logger.info("Telegram alerts disabled (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set)")

    def send(self, message: str) -> bool:
        if not self.enabled:
            return False
        try:
            url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
            resp = requests.post(url, json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            }, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram alert failed: {e}")
            return False

    def send_buy_signal(self, market_title: str, market_id: str,
                         predicted_prob: float, implied_prob: float,
                         edge: float, ev: float, recommended_size: float) -> bool:
        message = (
            f"🚨 <b>BUY SIGNAL</b>\n\n"
            f"📊 <b>{market_title}</b>\n\n"
            f"• Predicted: {predicted_prob:.1%}\n"
            f"• Market: {implied_prob:.1%}\n"
            f"• Edge: +{edge:.1%}\n"
            f"• EV: +{ev:.1%}\n"
            f"• Recommended Size: ${recommended_size:.2f}\n\n"
            f"🔗 polymarket.com"
        )
        return self.send(message)

    def send_arb_signal(
        self,
        title_a: str,
        platform_a: str,
        price_a: float,
        platform_b: str,
        price_b: float,
        delta: float,
        profit_pct: float,
        buy_yes_on: str,
        buy_no_on: str,
        url_a: str = "",
        url_b: str = "",
    ) -> bool:
        price_low = min(price_a, price_b)
        price_high = max(price_a, price_b)
        message = (
            f"⚡ <b>ARB DETECTED</b>\n\n"
            f"📋 <b>{title_a[:80]}</b>\n\n"
            f"• {platform_a.capitalize()}: {price_a:.1%}\n"
            f"• {platform_b.capitalize()}: {price_b:.1%}\n"
            f"• Δodds: <b>{delta:.1%}</b>\n"
            f"• Guaranteed profit: <b>+{profit_pct:.1%}</b>\n\n"
            f"🟢 Buy YES on {buy_yes_on} @ {price_low:.1%}\n"
            f"🔴 Buy NO on {buy_no_on} @ {1 - price_high:.1%}\n"
            f"💰 Total cost: {price_low + (1 - price_high):.1%} → payout $1.00"
        )
        if url_a:
            message += f"\n🔗 {url_a}"
        return self.send(message)

    def send_paper_trade_signal(
        self,
        market_title: str,
        market_id: str,
        predicted_prob: float,
        implied_prob: float,
        edge: float,
        confidence: float,
        size_usd: float,
    ) -> bool:
        message = (
            f"📝 <b>PAPER TRADE</b>\n\n"
            f"📊 <b>{market_title}</b>\n\n"
            f"• Predicted: {predicted_prob:.1%}\n"
            f"• Market: {implied_prob:.1%}\n"
            f"• Edge: +{edge:.1%}\n"
            f"• Confidence: {confidence:.1%}\n"
            f"• Paper Size: ${size_usd:.2f}\n\n"
            f"<i>Not a real trade — monitoring signal</i>"
        )
        return self.send(message)

    def send_paper_trade_result(
        self,
        market_title: str,
        status: str,
        predicted_prob: float,
        actual_result: bool,
        entry_price: float,
        pnl: float,
        size_usd: float,
    ) -> bool:
        emoji = "✅" if status == "won" else "❌"
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        message = (
            f"{emoji} <b>PAPER TRADE RESOLVED</b>\n\n"
            f"📊 <b>{market_title}</b>\n\n"
            f"• Result: <b>{'YES' if actual_result else 'NO'}</b>\n"
            f"• Predicted: {predicted_prob:.1%}\n"
            f"• Entry Price: {entry_price:.1%}\n"
            f"• Size: ${size_usd:.2f}\n"
            f"• PnL: <b>{pnl_str}</b>\n\n"
            f"<i>Paper trade — simulated result</i>"
        )
        return self.send(message)

    def send_pipeline_summary(self, markets_processed: int, buy_count: int,
                               observe_count: int, skip_count: int) -> bool:
        message = (
            f"⚙️ <b>Pipeline Complete</b>\n\n"
            f"Markets analyzed: {markets_processed}\n"
            f"🟢 BUY: {buy_count}\n"
            f"🟡 OBSERVE: {observe_count}\n"
            f"🔴 SKIP: {skip_count}"
        )
        return self.send(message)

alert_service = AlertService()

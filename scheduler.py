"""
APScheduler configuration for periodic background tasks.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from database.session import get_db_context

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Re-analysis decision logic
# ---------------------------------------------------------------------------


def _should_reanalyze(market, last_decision) -> bool:
    """
    Returns True if a market with an existing decision should be re-analyzed.

    Re-analysis triggers (any one is sufficient):
      1. Price changed >= 5% since the last decision
      2. Market has a detected price-jump flag
      3. Market resolves within 24 h AND last decision was > 2 h ago
      4. Market resolves within 72 h AND last decision was > 6 h ago
      5. Last decision is older than 24 h (general daily refresh)
    """
    now = datetime.utcnow()
    hours_since = (now - last_decision.created_at).total_seconds() / 3600

    # 1. Price movement
    old_price = last_decision.price_at_decision
    if old_price and old_price > 0:
        change = abs(market.current_price - old_price) / old_price
        if change >= 0.05:
            logger.debug(
                f"[Scheduler] Re-analyze {market.market_id}: price moved "
                f"{change:.1%} ({old_price:.3f} → {market.current_price:.3f})"
            )
            return True

    # 2. Price-jump flag set by ScanAgent
    if market.flags and market.flags.get("price_jump"):
        logger.debug(f"[Scheduler] Re-analyze {market.market_id}: price_jump flag set")
        return True

    # 3 & 4. Proximity to resolution (tiered re-analysis)
    if market.resolve_time:
        hours_left = (market.resolve_time - now).total_seconds() / 3600
        if hours_left <= 6 and hours_since >= 0.5:       # intraday: re-analyze every 30 min
            logger.debug(
                f"[Scheduler] Re-analyze {market.market_id}: resolves in {hours_left:.1f}h, "
                f"last analyzed {hours_since:.1f}h ago"
            )
            return True
        if hours_left <= 24 and hours_since >= 1:         # same-day: every 1h
            logger.debug(
                f"[Scheduler] Re-analyze {market.market_id}: resolves in {hours_left:.1f}h, "
                f"last analyzed {hours_since:.1f}h ago"
            )
            return True
        if hours_left <= 72 and hours_since >= 3:         # 3-day: every 3h
            logger.debug(
                f"[Scheduler] Re-analyze {market.market_id}: resolves in {hours_left:.1f}h, "
                f"last analyzed {hours_since:.1f}h ago"
            )
            return True

    # 5. General 6-hour refresh
    if hours_since >= 6:
        logger.debug(
            f"[Scheduler] Re-analyze {market.market_id}: stale decision ({hours_since:.1f}h old)"
        )
        return True

    return False


# ---------------------------------------------------------------------------
# Job functions (synchronous wrappers around async agents)
# ---------------------------------------------------------------------------


def job_arb_scan() -> None:
    """
    Scheduled job: detect cross-platform arbitrage opportunities.
    Fetches all active markets from DB, runs arb detection, saves results,
    and sends Telegram alerts for the top opportunities.
    """
    logger.info("[Scheduler] Starting cross-platform arb scan.")
    try:
        from services.arb_detector import detect_arb_opportunities, save_arb_opportunities
        from services.alert_service import alert_service
        from database.models import Market
        from database.session import get_db_context

        # Load all active markets from DB (already scanned & normalized)
        with get_db_context() as db:
            markets = (
                db.query(Market)
                .filter(Market.status == "active")  # type: ignore[arg-type]
                .all()
            )
            # Detach from session before closing context
            db.expunge_all()

        signals = detect_arb_opportunities(markets)
        if not signals:
            logger.info("[Scheduler] No arb opportunities found.")
            return

        saved = save_arb_opportunities(signals)

        # Alert on top 3 opportunities
        for sig in signals[:3]:
            try:
                alert_service.send_arb_signal(
                    title_a=sig.market_a.title,
                    platform_a=sig.platform_a,
                    price_a=sig.price_a,
                    platform_b=sig.platform_b,
                    price_b=sig.price_b,
                    delta=sig.delta,
                    profit_pct=sig.profit_pct,
                    buy_yes_on=sig.buy_yes_on,
                    buy_no_on=sig.buy_no_on,
                    url_a=sig.market_a.url or "",
                )
            except Exception as e:
                logger.warning(f"[Scheduler] Arb alert failed: {e}")

        logger.info(
            f"[Scheduler] Arb scan done. {len(signals)} opportunities found, "
            f"{saved} newly saved. Top delta: {signals[0].delta:.1%}"
        )
    except Exception as e:
        logger.error(f"[Scheduler] Arb scan job failed: {e}", exc_info=True)


def job_scan_markets() -> None:
    """Scheduled job: scan markets from all platforms."""
    logger.info("[Scheduler] Starting market scan job.")
    try:
        from agents.scan_agent import ScanAgent

        agent = ScanAgent()
        markets = agent.scan_markets()
        logger.info(f"[Scheduler] Scan complete: {len(markets)} markets processed.")
    except Exception as e:
        logger.error(f"[Scheduler] Market scan job failed: {e}", exc_info=True)


def job_review_completed_markets() -> None:
    """Scheduled job: review markets that have passed their resolve_time."""
    logger.info("[Scheduler] Starting review job.")
    try:
        from agents.review_agent import ReviewAgent

        agent = ReviewAgent()
        outcomes = agent.review_completed_markets()
        logger.info(f"[Scheduler] Review complete: {len(outcomes)} outcomes recorded.")
    except Exception as e:
        logger.error(f"[Scheduler] Review job failed: {e}", exc_info=True)


def ultra_fast_pipeline_job() -> None:
    """
    Scheduled job: intraday pipeline for markets resolving within 24h.
    Runs every 5 minutes to enable multiple trades per day.
    """
    logger.info("[Scheduler] Starting ultra-fast pipeline job (intraday markets).")
    try:
        from agents.prediction_agent import PredictionAgent
        from agents.research_agent import ResearchAgent
        from agents.risk_agent import RiskAgent
        from agents.scan_agent import ScanAgent

        scan_agent = ScanAgent()
        raw = scan_agent.scan_markets()

        now = __import__('datetime').datetime.utcnow()
        cutoff = now + __import__('datetime').timedelta(hours=settings.ULTRA_FAST_PIPELINE_HOURS)
        intraday = [m for m in raw if m.resolve_time and m.resolve_time <= cutoff]

        if not intraday:
            logger.info("[Scheduler] No intraday markets to process.")
            return

        logger.info(f"[Scheduler] Ultra-fast pipeline processing {len(intraday)} intraday markets.")

        for market in intraday[:10]:
            try:
                with get_db_context() as db:
                    from database.models import Market as MarketModel, RiskDecision as RiskDecisionModel
                    import asyncio as _asyncio
                    m = db.query(MarketModel).filter(MarketModel.id == market.id).first()
                    if not m:
                        continue

                    existing = (
                        db.query(RiskDecisionModel)
                        .filter(RiskDecisionModel.market_id == m.id)
                        .order_by(RiskDecisionModel.created_at.desc())
                        .first()
                    )
                    if existing and not _should_reanalyze(m, existing):
                        continue

                    research_agent = ResearchAgent(db=db)
                    report = _asyncio.run(research_agent.research_market_async(m))

                    prediction_agent = PredictionAgent(db=db)
                    prediction = _asyncio.run(prediction_agent.predict_async(m, report))
                    if not prediction:
                        continue

                    risk_agent = RiskAgent(db=db)
                    risk_agent.decide(m, prediction)
                    logger.info(f"[Scheduler] Ultra-fast pipeline complete for {m.market_id}")
            except Exception as e:
                logger.error(f"[Scheduler] Ultra-fast pipeline failed for {market.market_id}: {e}", exc_info=True)
                continue
    except Exception as e:
        logger.error(f"[Scheduler] Ultra-fast pipeline top-level error: {e}", exc_info=True)


def fast_pipeline_job() -> None:
    """
    Scheduled job: run the full pipeline targeting ONLY markets resolving within
    settings.FAST_PIPELINE_HOURS (default 14d). Runs every 15 minutes.
    """
    logger.info("[Scheduler] Starting fast pipeline job (short-term markets).")
    try:
        from agents.prediction_agent import PredictionAgent
        from agents.research_agent import ResearchAgent
        from agents.risk_agent import RiskAgent
        from agents.scan_agent import ScanAgent
        from database.models import ActionEnum, ResearchReport

        # Step 1: Scan short-term markets only (top 10 within 72h)
        scan_agent = ScanAgent()
        top_markets = scan_agent.scan_markets(short_term_only=True)

        if not top_markets:
            logger.info("[Scheduler] No short-term markets to process.")
            return

        logger.info(f"[Scheduler] Fast pipeline processing {len(top_markets)} short-term markets.")

        for market in top_markets:
            try:
                with get_db_context() as db:
                    from database.models import Market as MarketModel, RiskDecision as RiskDecisionModel
                    import asyncio as _asyncio
                    m = db.query(MarketModel).filter(MarketModel.id == market.id).first()
                    if not m:
                        continue

                    existing = (
                        db.query(RiskDecisionModel)
                        .filter(RiskDecisionModel.market_id == m.id)
                        .order_by(RiskDecisionModel.created_at.desc())
                        .first()
                    )
                    if existing and not _should_reanalyze(m, existing):
                        logger.debug(f"[Scheduler] Fast: skipping {m.market_id} — no change.")
                        continue

                    if existing:
                        logger.info(f"[Scheduler] Fast: re-analyzing {m.market_id} (conditions changed).")

                    research_agent = ResearchAgent(db=db)
                    report = _asyncio.run(research_agent.research_market_async(m))

                    prediction_agent = PredictionAgent(db=db)
                    prediction = _asyncio.run(prediction_agent.predict_async(m, report))

                    if not prediction:
                        continue

                    risk_agent = RiskAgent(db=db)
                    risk_agent.decide(m, prediction)

                    logger.info(f"[Scheduler] Fast pipeline complete for {m.market_id}")
            except Exception as e:
                logger.error(
                    f"[Scheduler] Fast pipeline failed for {market.market_id}: {e}",
                    exc_info=True,
                )
                continue
    except Exception as e:
        logger.error(f"[Scheduler] Fast pipeline job top-level error: {e}", exc_info=True)


def job_full_pipeline() -> None:
    """
    Scheduled job: run the complete pipeline (scan → research → predict → decide)
    for the top 5 markets by priority score.
    """
    logger.info("[Scheduler] Starting full pipeline job.")
    try:
        from agents.prediction_agent import PredictionAgent
        from agents.research_agent import ResearchAgent
        from agents.risk_agent import RiskAgent
        from agents.scan_agent import ScanAgent
        from database.models import ActionEnum, ResearchReport
        from services.alert_service import alert_service

        # Step 1: Scan
        scan_agent = ScanAgent()
        top_markets = scan_agent.scan_markets()[:30]

        if not top_markets:
            logger.info("[Scheduler] No markets to process in pipeline.")
            return

        logger.info(f"[Scheduler] Pipeline processing {len(top_markets)} markets.")

        buy_count = 0
        observe_count = 0
        skip_count = 0
        markets_processed = 0

        for market in top_markets:
            try:
                logger.info(f"[Scheduler] Pipeline: processing '{market.title[:50]}'")

                with get_db_context() as db:
                    # Re-attach market to the new session
                    from database.models import Market as MarketModel, RiskDecision as RiskDecisionModel
                    m = db.query(MarketModel).filter(MarketModel.id == market.id).first()
                    if not m:
                        continue

                    # Re-analyze if conditions changed; skip only if nothing significant happened
                    existing = (
                        db.query(RiskDecisionModel)
                        .filter(RiskDecisionModel.market_id == m.id)
                        .order_by(RiskDecisionModel.created_at.desc())
                        .first()
                    )
                    if existing and not _should_reanalyze(m, existing):
                        logger.debug(f"[Scheduler] Skipping {m.market_id} — no significant change.")
                        continue

                    if existing:
                        logger.info(f"[Scheduler] Re-analyzing {m.market_id} (conditions changed).")

                    # Step 2: Research
                    research_agent = ResearchAgent(db=db)
                    report = asyncio.run(research_agent.research_market_async(m))

                    # Step 3: Predict
                    prediction_agent = PredictionAgent(db=db)
                    prediction = asyncio.run(prediction_agent.predict_async(m, report))

                    if not prediction:
                        logger.warning(f"[Scheduler] No prediction for {m.market_id}; skipping.")
                        continue

                    # Step 4: Risk decision
                    risk_agent = RiskAgent(db=db)
                    decision = risk_agent.decide(m, prediction)

                    markets_processed += 1
                    if decision:
                        action_val = decision.action.value if hasattr(decision.action, 'value') else str(decision.action)
                        if action_val == ActionEnum.BUY.value:
                            buy_count += 1
                        elif action_val == ActionEnum.OBSERVE.value:
                            observe_count += 1
                        else:
                            skip_count += 1

                    logger.info(
                        f"[Scheduler] Pipeline complete for {m.market_id}: "
                        f"action={decision.action if decision else 'N/A'}"
                    )
            except Exception as e:
                logger.error(
                    f"[Scheduler] Pipeline failed for market {market.market_id}: {e}",
                    exc_info=True,
                )
                skip_count += 1
                continue

        # Send pipeline summary alert only when there's something noteworthy
        try:
            if buy_count > 0 or skip_count > 0:
                alert_service.send_pipeline_summary(
                    markets_processed=markets_processed,
                    buy_count=buy_count,
                    observe_count=observe_count,
                    skip_count=skip_count,
                )
        except Exception as e:
            logger.warning(f"[Scheduler] Failed to send pipeline summary alert: {e}")

        logger.info(
            f"[Scheduler] Full pipeline job finished. "
            f"Processed={markets_processed}, BUY={buy_count}, OBSERVE={observe_count}, SKIP={skip_count}"
        )
    except Exception as e:
        logger.error(f"[Scheduler] Full pipeline job encountered a top-level error: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------


def setup_scheduler() -> BackgroundScheduler:
    """
    Create and configure the APScheduler BackgroundScheduler.
    Jobs are added but the scheduler is NOT started here — call .start() on the returned object.
    """
    scheduler = BackgroundScheduler(
        job_defaults={
            "coalesce": True,       # merge missed runs into one
            "max_instances": 1,     # prevent overlapping runs
            "misfire_grace_time": 60,
        }
    )

    # Job 1: Market scan every SCAN_INTERVAL_MINUTES
    scheduler.add_job(
        job_scan_markets,
        trigger=IntervalTrigger(minutes=settings.SCAN_INTERVAL_MINUTES),
        id="scan_markets",
        name="Market Scanner",
        replace_existing=True,
    )
    logger.info(
        f"Scheduled: scan_markets every {settings.SCAN_INTERVAL_MINUTES} minutes."
    )

    # Job 2: Review completed markets every hour
    scheduler.add_job(
        job_review_completed_markets,
        trigger=IntervalTrigger(hours=1),
        id="review_markets",
        name="Market Reviewer",
        replace_existing=True,
    )
    logger.info("Scheduled: review_completed_markets every 1 hour.")

    # Job 3: Full pipeline every 2 hours
    scheduler.add_job(
        job_full_pipeline,
        trigger=IntervalTrigger(hours=2),
        id="full_pipeline",
        name="Full Pipeline",
        replace_existing=True,
    )
    logger.info("Scheduled: full_pipeline every 2 hours.")

    # Job 4: Ultra-fast pipeline every 5 minutes (intraday markets resolving within 24h)
    scheduler.add_job(
        ultra_fast_pipeline_job,
        trigger=IntervalTrigger(minutes=5),
        id="ultra_fast_pipeline",
        name="Ultra-Fast Pipeline (Intraday)",
        replace_existing=True,
    )
    logger.info("Scheduled: ultra_fast_pipeline every 5 minutes (intraday markets).")

    # Job 5: Fast pipeline every 15 minutes (short-term markets up to 14 days)
    scheduler.add_job(
        fast_pipeline_job,
        trigger=IntervalTrigger(minutes=15),
        id="fast_pipeline",
        name="Fast Pipeline (Short-term)",
        replace_existing=True,
    )
    logger.info("Scheduled: fast_pipeline every 15 minutes (short-term markets).")

    # Job 6: Cross-platform arbitrage scan
    scheduler.add_job(
        job_arb_scan,
        trigger=IntervalTrigger(minutes=settings.ARB_SCAN_INTERVAL_MINUTES),
        id="arb_scan",
        name="Cross-Platform Arb Scanner",
        replace_existing=True,
    )
    logger.info(
        f"Scheduled: arb_scan every {settings.ARB_SCAN_INTERVAL_MINUTES} minutes."
    )

    return scheduler


if __name__ == "__main__":
    """Run scheduler standalone (useful for testing)."""
    import time

    logging.basicConfig(level=logging.INFO)
    from database.session import init_db

    init_db()
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info("Scheduler started. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler shut down.")

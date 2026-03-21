"""
Click CLI for interacting with the Prediction Market AI system.
"""

import asyncio
import logging
import sys
from datetime import datetime
from typing import List, Optional

import click
from tabulate import tabulate

from config import settings
from database.session import get_db_context, init_db

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a synchronous Click command."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose (DEBUG) logging.")
def cli(verbose: bool):
    """Prediction Market AI — CLI tool."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    # Ensure DB is initialized
    init_db()


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


@cli.command()
def scan():
    """Scan markets from all platforms and display the top results."""
    from agents.scan_agent import ScanAgent

    click.echo("Scanning markets...")
    try:
        agent = ScanAgent()
        markets = agent.scan_markets()
    except Exception as e:
        click.echo(f"Error during scan: {e}", err=True)
        sys.exit(1)

    if not markets:
        click.echo("No markets found matching the configured filters.")
        return

    rows = []
    for m in markets:
        resolve = m.resolve_time.strftime("%Y-%m-%d") if m.resolve_time else "N/A"
        rows.append(
            [
                m.market_id[:30],
                m.title[:50],
                m.platform,
                f"{m.current_price:.2%}",
                f"${m.liquidity:,.0f}",
                f"${m.volume_24h:,.0f}",
                f"{m.spread:.2%}",
                resolve,
                f"{m.priority_score:.4f}",
            ]
        )

    headers = [
        "Market ID",
        "Title",
        "Platform",
        "Price",
        "Liquidity",
        "Vol 24h",
        "Spread",
        "Resolves",
        "Priority",
    ]
    click.echo(f"\nFound {len(markets)} markets:\n")
    click.echo(tabulate(rows, headers=headers, tablefmt="rounded_outline"))


# ---------------------------------------------------------------------------
# research
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("market_id")
def research(market_id: str):
    """Run research for a specific market by its market_id."""
    from agents.research_agent import ResearchAgent
    from database.models import Market

    with get_db_context() as db:
        market = db.query(Market).filter(Market.market_id == market_id).first()
        if not market:
            click.echo(f"Market '{market_id}' not found in database.", err=True)
            sys.exit(1)

        click.echo(f"Researching market: {market.title[:80]}")
        try:
            agent = ResearchAgent(db=db)
            report = _run_async(agent.research_market_async(market))
        except Exception as e:
            click.echo(f"Error during research: {e}", err=True)
            sys.exit(1)

        if not report:
            click.echo("Research failed to generate a report.", err=True)
            sys.exit(1)

        rows = [
            ["Report ID", report.id],
            ["Market ID", market_id],
            ["Keywords", ", ".join(report.keywords or [])],
            ["Sentiment Score", f"{report.sentiment_score:.4f}"],
            ["Credibility Score", f"{report.credibility_score:.4f}"],
            ["Source Count", report.source_count],
            ["Created At", report.created_at.strftime("%Y-%m-%d %H:%M:%S") if report.created_at else "N/A"],
        ]
        click.echo("\n" + tabulate(rows, tablefmt="rounded_outline"))
        click.echo(f"\nSummary:\n{report.summary}\n")


# ---------------------------------------------------------------------------
# predict
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("market_id")
def predict(market_id: str):
    """Run probability prediction for a specific market."""
    from agents.prediction_agent import PredictionAgent
    from database.models import Market, ResearchReport

    with get_db_context() as db:
        market = db.query(Market).filter(Market.market_id == market_id).first()
        if not market:
            click.echo(f"Market '{market_id}' not found in database.", err=True)
            sys.exit(1)

        # Grab latest research report
        research_report = (
            db.query(ResearchReport)
            .filter(ResearchReport.market_id == market.id)
            .order_by(ResearchReport.created_at.desc())
            .first()
        )

        if not research_report:
            click.echo("No research report found. Run `research` first for better predictions.")

        click.echo(f"Predicting for market: {market.title[:80]}")
        try:
            agent = PredictionAgent(db=db)
            prediction = _run_async(agent.predict_async(market, research_report))
        except Exception as e:
            click.echo(f"Error during prediction: {e}", err=True)
            sys.exit(1)

        if not prediction:
            click.echo("Prediction failed.", err=True)
            sys.exit(1)

        rows = [
            ["Prediction ID", prediction.id],
            ["Predicted Probability", f"{prediction.predicted_probability:.4f} ({prediction.predicted_probability:.1%})"],
            ["Implied Probability", f"{prediction.implied_probability:.4f} ({prediction.implied_probability:.1%})"],
            ["Edge", f"{prediction.edge:+.4f}"],
            ["Confidence Score", f"{prediction.confidence_score:.4f}"],
            ["Model Version", prediction.model_version],
            ["Created At", prediction.created_at.strftime("%Y-%m-%d %H:%M:%S") if prediction.created_at else "N/A"],
        ]
        click.echo("\n" + tabulate(rows, tablefmt="rounded_outline"))
        click.echo(f"\nReasoning:\n{prediction.reasoning}\n")


# ---------------------------------------------------------------------------
# decide
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("market_id")
def decide(market_id: str):
    """Run a risk decision for a specific market."""
    from agents.risk_agent import RiskAgent
    from database.models import Market, Prediction

    with get_db_context() as db:
        market = db.query(Market).filter(Market.market_id == market_id).first()
        if not market:
            click.echo(f"Market '{market_id}' not found in database.", err=True)
            sys.exit(1)

        prediction = (
            db.query(Prediction)
            .filter(Prediction.market_id == market.id)
            .order_by(Prediction.created_at.desc())
            .first()
        )
        if not prediction:
            click.echo("No prediction found. Run `predict` first.", err=True)
            sys.exit(1)

        click.echo(f"Making risk decision for: {market.title[:80]}")
        try:
            agent = RiskAgent(db=db)
            decision = agent.decide(market, prediction)
        except Exception as e:
            click.echo(f"Error during decision: {e}", err=True)
            sys.exit(1)

        if not decision:
            click.echo("Decision failed.", err=True)
            sys.exit(1)

        action_color = {
            "buy": "green",
            "skip": "red",
            "observe": "yellow",
        }.get(str(decision.action).lower(), "white")

        rows = [
            ["Decision ID", decision.id],
            ["Action", click.style(str(decision.action).upper(), fg=action_color, bold=True)],
            ["Recommended Size", f"${decision.recommended_size:.2f}"],
            ["Expected Value", f"{decision.ev:.4f}"],
            ["Risk Score", f"{decision.risk_score:.4f}"],
            ["Created At", decision.created_at.strftime("%Y-%m-%d %H:%M:%S") if decision.created_at else "N/A"],
        ]
        click.echo("\n" + tabulate(rows, tablefmt="rounded_outline"))
        click.echo(f"\nReason:\n{decision.reason}\n")


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--top-n", default=5, show_default=True, help="Number of top markets to process.")
def pipeline(top_n: int):
    """Run the full pipeline: scan → research → predict → decide."""
    from agents.prediction_agent import PredictionAgent
    from agents.research_agent import ResearchAgent
    from agents.risk_agent import RiskAgent
    from agents.scan_agent import ScanAgent
    from database.models import Market as MarketModel

    click.echo("Starting full pipeline...\n")

    # Step 1: Scan
    click.echo("[1/4] Scanning markets...")
    try:
        scan_agent = ScanAgent()
        top_markets = scan_agent.scan_markets()[:top_n]
        click.echo(f"      Found {len(top_markets)} markets.\n")
    except Exception as e:
        click.echo(f"Scan failed: {e}", err=True)
        sys.exit(1)

    if not top_markets:
        click.echo("No markets found. Exiting pipeline.")
        return

    summary_rows = []

    for i, market in enumerate(top_markets, 1):
        click.echo(f"[{i}/{len(top_markets)}] Processing: {market.title[:60]}")

        try:
            with get_db_context() as db:
                m = db.query(MarketModel).filter(MarketModel.id == market.id).first()
                if not m:
                    click.echo(f"  Market {market.market_id} not found in DB; skipping.")
                    continue

                # Research
                click.echo("  → Research...")
                research_agent = ResearchAgent(db=db)
                report = _run_async(research_agent.research_market_async(m))

                # Predict
                click.echo("  → Predict...")
                prediction_agent = PredictionAgent(db=db)
                prediction = _run_async(prediction_agent.predict_async(m, report))

                if not prediction:
                    click.echo(f"  Prediction failed for {m.market_id}; skipping.")
                    continue

                # Decide
                click.echo("  → Decide...")
                risk_agent = RiskAgent(db=db)
                decision = risk_agent.decide(m, prediction)

                action = str(decision.action).upper() if decision else "FAILED"
                size = f"${decision.recommended_size:.2f}" if decision else "$0.00"
                ev = f"{decision.ev:.4f}" if decision else "N/A"

                summary_rows.append(
                    [
                        m.market_id[:25],
                        m.title[:40],
                        f"{prediction.predicted_probability:.1%}",
                        f"{prediction.edge:+.3f}",
                        f"{prediction.confidence_score:.3f}",
                        action,
                        size,
                        ev,
                    ]
                )
                click.echo(f"  Done: action={action}, size={size}\n")

        except Exception as e:
            click.echo(f"  Error processing {market.market_id}: {e}", err=True)
            continue

    if summary_rows:
        click.echo("\n=== Pipeline Summary ===\n")
        headers = [
            "Market ID", "Title", "Pred. Prob", "Edge", "Confidence", "Action", "Size", "EV"
        ]
        click.echo(tabulate(summary_rows, headers=headers, tablefmt="rounded_outline"))

    click.echo("\nPipeline complete.")


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


@cli.command()
def stats():
    """Display system statistics."""
    from database.models import ActionEnum, Market, MarketStatus, Outcome, Prediction, RiskDecision
    from sqlalchemy import func

    with get_db_context() as db:
        total_markets = db.query(func.count(Market.id)).scalar() or 0
        active = (
            db.query(func.count(Market.id))
            .filter(Market.status == MarketStatus.ACTIVE)
            .scalar()
            or 0
        )
        resolved = (
            db.query(func.count(Market.id))
            .filter(Market.status == MarketStatus.RESOLVED)
            .scalar()
            or 0
        )
        total_predictions = db.query(func.count(Prediction.id)).scalar() or 0
        avg_conf = float(db.query(func.avg(Prediction.confidence_score)).scalar() or 0)
        total_decisions = db.query(func.count(RiskDecision.id)).scalar() or 0
        buys = (
            db.query(func.count(RiskDecision.id))
            .filter(RiskDecision.action == ActionEnum.BUY)
            .scalar()
            or 0
        )
        total_outcomes = db.query(func.count(Outcome.id)).scalar() or 0
        wins = (
            db.query(func.count(Outcome.id)).filter(Outcome.pnl > 0).scalar() or 0
        )
        total_pnl = float(db.query(func.sum(Outcome.pnl)).scalar() or 0.0)

        win_rate = (wins / total_outcomes * 100) if total_outcomes > 0 else 0.0

        rows = [
            ["Total Markets", total_markets],
            ["Active Markets", active],
            ["Resolved Markets", resolved],
            ["Total Predictions", total_predictions],
            ["Avg Confidence", f"{avg_conf:.4f}"],
            ["Total Decisions", total_decisions],
            ["BUY Decisions", buys],
            ["Total Outcomes", total_outcomes],
            ["Win Rate", f"{win_rate:.1f}%"],
            ["Total PnL", f"${total_pnl:.2f}"],
            ["Bankroll", f"${settings.BANKROLL:.2f}"],
        ]

        click.echo("\n=== System Statistics ===\n")
        click.echo(tabulate(rows, headers=["Metric", "Value"], tablefmt="rounded_outline"))
        click.echo()


# ---------------------------------------------------------------------------
# outcomes
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--limit", default=20, show_default=True, help="Maximum outcomes to display.")
def outcomes(limit: int):
    """List recent market outcomes."""
    from database.models import Market, Outcome

    with get_db_context() as db:
        records = (
            db.query(Outcome)
            .order_by(Outcome.created_at.desc())
            .limit(limit)
            .all()
        )

        if not records:
            click.echo("No outcomes recorded yet.")
            return

        rows = []
        for o in records:
            market = db.query(Market).filter(Market.id == o.market_id).first()
            title = market.title[:40] if market else "N/A"
            pnl_str = click.style(f"${o.pnl:+.2f}", fg="green" if o.pnl >= 0 else "red")
            rows.append(
                [
                    o.id,
                    title,
                    "YES" if o.actual_result else "NO",
                    pnl_str,
                    ", ".join(o.failure_tags or []) or "—",
                    o.created_at.strftime("%Y-%m-%d") if o.created_at else "N/A",
                ]
            )

        total_pnl = sum(o.pnl for o in records)
        pnl_color = "green" if total_pnl >= 0 else "red"

        headers = ["ID", "Market", "Result", "PnL", "Failure Tags", "Date"]
        click.echo(f"\n=== Recent Outcomes (last {len(records)}) ===\n")
        click.echo(tabulate(rows, headers=headers, tablefmt="rounded_outline"))
        click.echo(
            f"\n  Total PnL shown: {click.style(f'${total_pnl:+.2f}', fg=pnl_color, bold=True)}\n"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    cli()

"""
Configuration management using Pydantic Settings.
All settings can be overridden via environment variables or .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
import logging


class Settings(BaseSettings):
    # API Keys
    ANTHROPIC_API_KEY: Optional[str] = Field(None, description="Anthropic API key (unused)")
    OPENAI_API_KEY: Optional[str] = Field(None, description="OpenAI API key for GPT-4o-mini")
    NEWS_API_KEY: Optional[str] = Field(None, description="NewsAPI key (optional)")
    KALSHI_API_KEY: Optional[str] = Field(None, description="Kalshi API key ID")
    KALSHI_PRIVATE_KEY_PATH: str = Field(default="./kalshi_private_key.pem", description="Path to Kalshi RSA private key")
    METACULUS_API_TOKEN: Optional[str] = Field(None, description="Metaculus API token")

    # Database
    DATABASE_URL: str = Field(
        default="sqlite:///./prediction_market.db",
        description="SQLAlchemy database URL",
    )

    # Market Filters
    MIN_LIQUIDITY: float = Field(default=1000.0, description="Minimum market liquidity")
    MIN_VOLUME_24H: float = Field(default=100.0, description="Minimum 24h volume")
    MIN_HOURS_TO_RESOLVE: float = Field(
        default=1.0, description="Minimum hours until market resolution"
    )
    MAX_SPREAD: float = Field(
        default=0.15, description="Maximum bid-ask spread (15%)"
    )

    # Decision Thresholds
    MIN_CONFIDENCE_SCORE: float = Field(
        default=0.6, description="Minimum confidence score to act"
    )
    MIN_EDGE: float = Field(
        default=0.005, description="Minimum edge (predicted - implied probability)"
    )
    MIN_EV: float = Field(default=0.01, description="Minimum expected value to bet")

    # Position Sizing
    MAX_POSITION_SIZE: float = Field(
        default=0.05, description="Maximum position as fraction of bankroll (5%)"
    )
    BANKROLL: float = Field(default=1000.0, description="Total bankroll in USD")
    KELLY_FRACTION: float = Field(
        default=0.25, description="Fractional Kelly criterion multiplier"
    )

    # Telegram Alerts (optional)
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(None, description="Telegram bot token from @BotFather")
    TELEGRAM_CHAT_ID: Optional[str] = Field(None, description="Telegram chat/channel ID for alerts")

    # Market scan limits
    MAX_MARKETS_TO_SCAN: int = Field(default=500, description="Maximum number of markets to fetch per scan")

    # Paper Trading
    PAPER_MIN_EDGE: float = Field(default=0.005, description="Minimum edge for paper trade signal")
    PAPER_MIN_CONFIDENCE: float = Field(default=0.5, description="Minimum confidence for paper trade signal")
    PAPER_MIN_PRICE: float = Field(default=0.02, description="Minimum market price (2%) — skip YES bets on near-zero probability markets")
    PAPER_MAX_HORIZON_DAYS: int = Field(default=180, description="Maximum days to resolution — skip paper trades on markets resolving > 180 days out")

    # Fast pipeline
    FAST_PIPELINE_HOURS: int = Field(default=336, description="Hours to resolution threshold for short-term pipeline (14 days)")
    ULTRA_FAST_PIPELINE_HOURS: int = Field(default=24, description="Hours to resolution threshold for ultra-fast intraday pipeline")

    # Scheduler
    SCAN_INTERVAL_MINUTES: int = Field(
        default=30, description="Market scan interval in minutes"
    )

    # Cross-platform arbitrage detection
    ARB_MIN_DELTA: float = Field(
        default=0.05, description="Minimum price difference (5%) to flag as arb opportunity"
    )
    ARB_MIN_TITLE_SIMILARITY: float = Field(
        default=0.55, description="Minimum Jaccard word-overlap score to match markets across platforms"
    )
    ARB_SCAN_INTERVAL_MINUTES: int = Field(
        default=15, description="How often to run cross-platform arb detection"
    )

    # Real-time monitoring (WebSocket)
    REALTIME_ENABLED: bool = Field(
        default=True, description="Enable Polymarket WebSocket real-time price monitor"
    )
    REALTIME_PRICE_CHANGE_THRESHOLD: float = Field(
        default=0.03, description="Min price change (3%) to trigger immediate re-analysis"
    )

    # Dynamic Kelly / position sizing
    KELLY_MIN_FRACTION: float = Field(
        default=0.15, description="Minimum Kelly fraction (low confidence)"
    )
    KELLY_MAX_FRACTION: float = Field(
        default=0.50, description="Maximum Kelly fraction (high confidence)"
    )
    MAX_POSITION_PCT_LIQUIDITY: float = Field(
        default=0.02, description="Max position as fraction of market liquidity (2%)"
    )

    # Order book spread alert
    SPREAD_ALERT_THRESHOLD: float = Field(
        default=0.10,
        description="Bid-ask spread width (10%) that triggers an illiquidity/mispricing alert",
    )

    # Real-time mispricing scanner
    MISPRICING_MIN_EDGE: float = Field(
        default=0.08,
        description="Minimum edge (predicted - live price) to fire a mispricing alert (8%)",
    )
    MISPRICING_ALERT_COOLDOWN_SECONDS: int = Field(
        default=300,
        description="Minimum seconds between mispricing alerts for the same market",
    )

    # Intraday market classification
    INTRADAY_HOURS: int = Field(
        default=24,
        description="Markets resolving within this many hours are treated as intraday",
    )

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    """Return singleton settings instance."""
    return Settings()


def setup_logging(log_level: str = "INFO") -> None:
    """Configure application-wide logging."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# Module-level settings instance
settings = get_settings()
setup_logging(settings.LOG_LEVEL)

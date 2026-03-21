"""
ResearchAgent: Generates research reports for markets by combining
news sentiment analysis with LLM summarization.
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import List, Optional, Set

from sqlalchemy.orm import Session

from config import settings
from database.models import Market, ResearchReport
from database.session import get_db_context
from services.llm_service import LLMService
from services.news_fetcher import NewsFetcher
from services.reddit_fetcher import RedditFetcher
from services.sentiment_analyzer import SentimentAnalyzer

logger = logging.getLogger(__name__)

# Common English stopwords to exclude from keyword extraction
STOPWORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through", "during",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "shall", "can", "not", "no", "nor", "so", "yet", "both", "either",
    "it", "its", "this", "that", "these", "those", "he", "she", "they",
    "we", "you", "i", "me", "him", "her", "us", "them", "what", "which",
    "who", "whom", "when", "where", "why", "how", "all", "each", "every",
    "if", "as", "than", "then", "just", "because", "while", "although",
    "however", "therefore", "thus", "such", "more", "most", "other",
    "also", "any", "between", "before", "after", "over", "under", "again",
    "further", "once", "here", "there", "whether", "same", "own", "s",
}


def _extract_keywords(title: str, max_keywords: int = 8) -> List[str]:
    """
    Extract meaningful keywords from a market title using simple NLP.
    Filters stopwords, short tokens, and duplicates. Returns up to max_keywords.
    """
    # Remove special characters, lowercase
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", title)
    tokens = cleaned.lower().split()

    seen: Set[str] = set()
    keywords: List[str] = []

    for token in tokens:
        if (
            len(token) >= 3
            and token not in STOPWORDS
            and token not in seen
        ):
            seen.add(token)
            keywords.append(token)

        if len(keywords) >= max_keywords:
            break

    return keywords


class ResearchAgent:
    """
    Generates a ResearchReport for a given Market by:
    1. Extracting keywords from the market title
    2. Fetching relevant news articles
    3. Computing sentiment
    4. Using LLM to produce a structured research summary
    """

    def __init__(self, db: Optional[Session] = None):
        self.news_fetcher = NewsFetcher(news_api_key=settings.NEWS_API_KEY)
        self.reddit_fetcher = RedditFetcher()
        self.sentiment_analyzer = SentimentAnalyzer()
        self.llm = LLMService()
        self._db = db

    def research_market(self, market: Market) -> Optional[ResearchReport]:
        """
        Synchronous entry point. Runs the async pipeline via asyncio.
        Returns a persisted ResearchReport, or None on failure.
        """
        try:
            return asyncio.run(self._research_market_async(market))
        except RuntimeError:
            # Already in an event loop (e.g. inside FastAPI)
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._research_market_async(market))

    async def research_market_async(self, market: Market) -> Optional[ResearchReport]:
        """Async entry point for use inside async contexts."""
        return await self._research_market_async(market)

    async def _research_market_async(self, market: Market) -> Optional[ResearchReport]:
        """Core async research pipeline."""
        logger.info(f"ResearchAgent: researching market '{market.title[:60]}'")

        # Step 1: Extract keywords
        keywords = _extract_keywords(market.title)
        if market.category:
            cat_keywords = _extract_keywords(market.category, max_keywords=3)
            keywords = list(dict.fromkeys(keywords + cat_keywords))[:10]

        logger.debug(f"Extracted keywords: {keywords}")

        # Step 2: Fetch news articles
        news_articles = self.news_fetcher.fetch_news(keywords)
        logger.info(f"Fetched {len(news_articles)} news articles for market {market.market_id}")

        # Step 2b: Fetch Reddit posts
        reddit_posts: List = []
        try:
            reddit_posts = self.reddit_fetcher.fetch_relevant_posts(keywords)
            logger.info(f"Fetched {len(reddit_posts)} Reddit posts for market {market.market_id}")
        except Exception as e:
            logger.warning(f"Reddit fetch failed for {market.market_id}: {e}")

        # Weight Reddit posts by score for credibility blending.
        # Posts with score >= 100 are treated as high-credibility sources.
        # We normalise score into a 0–1 weight and embed it in the article dict
        # so that downstream sentiment analysis can utilise it.
        weighted_reddit: List = []
        for post in reddit_posts:
            score = post.get("score", 0)
            weight = min(1.0, score / 1000.0)  # 1000 upvotes → full weight
            entry = dict(post)
            entry["credibility_weight"] = max(0.1, weight)
            weighted_reddit.append(entry)

        # Combine both sources; news articles come first, Reddit posts appended
        articles = news_articles + weighted_reddit

        # Step 3: Keyword-based sentiment (over combined articles)
        sentiment_result = self.sentiment_analyzer.analyze_articles(articles)

        # Step 4: LLM research summary
        try:
            llm_result = await self.llm.analyze_market_research(market.title, articles)
        except Exception as e:
            logger.error(f"LLM research failed for {market.market_id}: {e}")
            llm_result = {
                "summary": "LLM analysis unavailable.",
                "sentiment_score": sentiment_result["score"],
                "credibility_score": 0.5,
                "key_factors": [],
                "narrative_gaps": [],
            }

        # Blend keyword sentiment with LLM sentiment
        blended_sentiment = (
            0.4 * sentiment_result["score"] + 0.6 * llm_result["sentiment_score"]
        )

        raw_data = {
            "keywords": keywords,
            "article_count": len(articles),
            "news_article_count": len(news_articles),
            "reddit_post_count": len(reddit_posts),
            "keyword_sentiment": sentiment_result,
            "llm_analysis": llm_result,
            "article_urls": [a.get("url", "") for a in articles[:10]],
            "reddit_urls": [p.get("url", "") for p in reddit_posts[:5]],
        }

        report = ResearchReport(
            market_id=market.id,
            keywords=keywords,
            summary=llm_result.get("summary", ""),
            sentiment_score=round(blended_sentiment, 4),
            source_count=len(articles),
            credibility_score=round(float(llm_result.get("credibility_score", 0.5)), 4),
            raw_data=raw_data,
        )

        def _save(db: Session) -> ResearchReport:
            db.add(report)
            db.flush()
            db.refresh(report)
            return report

        try:
            if self._db:
                saved = _save(self._db)
                self._db.commit()
            else:
                with get_db_context() as db:
                    saved = _save(db)
            logger.info(
                f"ResearchAgent: saved report {saved.id} for market {market.market_id}"
            )
            return saved
        except Exception as e:
            logger.error(f"Failed to save research report for {market.market_id}: {e}")
            return None

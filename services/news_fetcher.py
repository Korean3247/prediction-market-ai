"""
News fetcher supporting NewsAPI (key-gated) and free RSS feeds.
Returns a normalized list of article dicts.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import feedparser
import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10  # seconds

NEWS_API_URL = "https://newsapi.org/v2/everything"

RSS_FEEDS = {
    "BBC News": "http://feeds.bbci.co.uk/news/rss.xml",
    "Reuters": "https://feeds.reuters.com/reuters/topNews",
    "AP News": "https://rsshub.app/apnews/topics/apf-topnews",
}


def _parse_rss_date(entry: Any) -> Optional[datetime]:
    """Parse a feedparser entry's published date."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6])
        except Exception:
            pass
    return datetime.utcnow()


class NewsFetcher:
    """
    Fetches news articles from multiple sources.
    NewsAPI requires an API key; RSS feeds are always available.
    """

    def __init__(self, news_api_key: Optional[str] = None):
        self.news_api_key = news_api_key

    def fetch_from_newsapi(
        self, keywords: List[str], page_size: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Fetch articles from NewsAPI using the given keywords.
        Returns empty list if API key is not configured or request fails.
        """
        if not self.news_api_key:
            logger.debug("NewsAPI key not configured, skipping NewsAPI fetch.")
            return []

        query = " OR ".join(keywords[:5])  # limit query length
        params = {
            "q": query,
            "apiKey": self.news_api_key,
            "pageSize": page_size,
            "sortBy": "publishedAt",
            "language": "en",
        }

        try:
            resp = requests.get(NEWS_API_URL, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.warning(f"NewsAPI request failed: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in NewsAPI fetch: {e}")
            return []

        articles = []
        for article in data.get("articles", []):
            try:
                published_at = None
                raw_date = article.get("publishedAt")
                if raw_date:
                    try:
                        published_at = datetime.strptime(raw_date, "%Y-%m-%dT%H:%M:%SZ")
                    except ValueError:
                        published_at = datetime.utcnow()

                articles.append(
                    {
                        "title": article.get("title", ""),
                        "description": article.get("description") or article.get("content", ""),
                        "url": article.get("url", ""),
                        "published_at": published_at,
                        "source": article.get("source", {}).get("name", "NewsAPI"),
                    }
                )
            except Exception as e:
                logger.debug(f"Skipping malformed NewsAPI article: {e}")
                continue

        logger.info(f"Fetched {len(articles)} articles from NewsAPI.")
        return articles

    def fetch_from_rss(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch and filter articles from RSS feeds using the given keywords.
        Returns articles whose title or description contain at least one keyword.
        """
        keyword_lower = [kw.lower() for kw in keywords]
        articles = []

        for source_name, feed_url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(feed_url)
                if feed.bozo and not feed.entries:
                    logger.debug(f"RSS feed parse error for {source_name}: {feed.bozo_exception}")
                    continue

                for entry in feed.entries:
                    title = getattr(entry, "title", "") or ""
                    description = (
                        getattr(entry, "summary", "")
                        or getattr(entry, "description", "")
                        or ""
                    )
                    combined = (title + " " + description).lower()

                    # Filter to keyword-relevant articles
                    if not any(kw in combined for kw in keyword_lower):
                        continue

                    articles.append(
                        {
                            "title": title,
                            "description": description,
                            "url": getattr(entry, "link", ""),
                            "published_at": _parse_rss_date(entry),
                            "source": source_name,
                        }
                    )
            except Exception as e:
                logger.warning(f"Error fetching RSS feed '{source_name}': {e}")
                continue

        logger.info(f"Fetched {len(articles)} matching articles from RSS feeds.")
        return articles

    def fetch_news(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch news from all available sources, deduplicated by URL.
        Returns combined list sorted by published_at descending.
        """
        all_articles: List[Dict[str, Any]] = []

        newsapi_articles = self.fetch_from_newsapi(keywords)
        all_articles.extend(newsapi_articles)

        rss_articles = self.fetch_from_rss(keywords)
        all_articles.extend(rss_articles)

        # Deduplicate by URL
        seen_urls: set = set()
        deduplicated = []
        for article in all_articles:
            url = article.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                deduplicated.append(article)

        # Sort by recency
        deduplicated.sort(
            key=lambda a: a.get("published_at") or datetime.min, reverse=True
        )

        logger.info(
            f"Total unique articles fetched: {len(deduplicated)} "
            f"(newsapi={len(newsapi_articles)}, rss={len(rss_articles)})"
        )
        return deduplicated

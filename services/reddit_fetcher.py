"""
Reddit data fetcher using Reddit's public JSON API.
No authentication required. Uses User-Agent header to avoid blocks.
Fetches posts from relevant subreddits and keyword searches.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

REDDIT_SEARCH_URL = "https://old.reddit.com/search.json"
REDDIT_SUBREDDIT_URL = "https://old.reddit.com/r/{subreddit}/hot.json"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 10
_CIRCUIT_BREAKER_THRESHOLD = 2  # consecutive 403s before disabling for this run

RELEVANT_SUBREDDITS = [
    "politics",
    "worldnews",
    "economics",
    "stocks",
    "cryptocurrency",
]


def _parse_reddit_post(post_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse a single Reddit post dict into normalized format."""
    try:
        data = post_data.get("data", post_data)
        title = data.get("title", "").strip()
        if not title:
            return None

        selftext = data.get("selftext", "") or ""
        # Truncate long self-text
        description = selftext[:500] if selftext else ""

        url = data.get("url", "")
        permalink = data.get("permalink", "")
        if permalink and not url.startswith("http"):
            url = f"https://www.reddit.com{permalink}"

        # Unix timestamp
        created_utc = data.get("created_utc")
        published_at: Optional[datetime] = None
        if created_utc:
            try:
                published_at = datetime.fromtimestamp(float(created_utc), tz=timezone.utc).replace(tzinfo=None)
            except Exception:
                published_at = None

        subreddit = data.get("subreddit", "")
        score = int(data.get("score", 0))
        num_comments = int(data.get("num_comments", 0))

        return {
            "title": title,
            "description": description,
            "url": url,
            "published_at": published_at,
            "source": f"reddit/r/{subreddit}" if subreddit else "reddit",
            "score": score,
            "num_comments": num_comments,
        }
    except Exception as e:
        logger.debug(f"Failed to parse Reddit post: {e}")
        return None


class RedditFetcher:
    """
    Fetches prediction-market-relevant posts from Reddit using the public JSON API.
    No OAuth required. Rate-limit friendly (1 second sleep between requests).
    Uses a circuit breaker: if Reddit returns 403 consecutively, skip for this run.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self._consecutive_failures = 0
        self._disabled = False

    def _get(self, url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Make a GET request and return parsed JSON, or None on error."""
        if self._disabled:
            return None
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 403:
                self._consecutive_failures += 1
                logger.warning(
                    f"Reddit 403 blocked ({self._consecutive_failures}/"
                    f"{_CIRCUIT_BREAKER_THRESHOLD}): {url}"
                )
                if self._consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
                    self._disabled = True
                    logger.warning(
                        "Reddit fetcher disabled for this run — "
                        "GCP IP likely blocked by Reddit."
                    )
                return None
            resp.raise_for_status()
            self._consecutive_failures = 0
            return resp.json()
        except requests.RequestException as e:
            logger.warning(f"Reddit request failed for {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching Reddit data from {url}: {e}")
            return None

    def search_reddit(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Search Reddit for posts matching a query (past week, sorted by relevance).
        Returns normalized post dicts.
        """
        params = {
            "q": query,
            "sort": "relevance",
            "t": "week",
            "limit": limit,
            "type": "link",
        }
        data = self._get(REDDIT_SEARCH_URL, params)
        if not data:
            return []

        posts = []
        for child in data.get("data", {}).get("children", []):
            parsed = _parse_reddit_post(child)
            if parsed:
                posts.append(parsed)

        logger.debug(f"Reddit search '{query}': {len(posts)} posts found")
        return posts

    def fetch_subreddit_hot(self, subreddit: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch hot posts from a specific subreddit.
        Returns normalized post dicts.
        """
        url = REDDIT_SUBREDDIT_URL.format(subreddit=subreddit)
        params = {"limit": limit}
        data = self._get(url, params)
        if not data:
            return []

        posts = []
        for child in data.get("data", {}).get("children", []):
            parsed = _parse_reddit_post(child)
            if parsed:
                posts.append(parsed)

        logger.debug(f"Reddit r/{subreddit} hot: {len(posts)} posts found")
        return posts

    def fetch_relevant_posts(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch posts from relevant subreddits and keyword searches.
        Combines posts from:
          - Top relevant subreddits (hot posts)
          - Keyword searches across all Reddit

        Deduplicates by URL. Returns combined list sorted by score (descending).
        All errors are handled gracefully - returns [] on complete failure.
        """
        all_posts: List[Dict[str, Any]] = []
        seen_urls = set()

        def _add_posts(new_posts: List[Dict[str, Any]]) -> None:
            for post in new_posts:
                url = post.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_posts.append(post)

        # 1. Fetch hot posts from each relevant subreddit
        for subreddit in RELEVANT_SUBREDDITS:
            try:
                posts = self.fetch_subreddit_hot(subreddit, limit=10)
                _add_posts(posts)
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Failed to fetch r/{subreddit}: {e}")
                continue

        # 2. Search by keyword query (combine top keywords into a search phrase)
        if keywords:
            # Use at most 5 keywords to keep the query focused
            query = " ".join(keywords[:5])
            try:
                posts = self.search_reddit(query, limit=10)
                _add_posts(posts)
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Reddit keyword search failed for '{query}': {e}")

        # Sort by score descending (higher upvotes = more credible/relevant)
        all_posts.sort(key=lambda p: p.get("score", 0), reverse=True)

        logger.info(f"RedditFetcher: collected {len(all_posts)} unique posts total")
        return all_posts

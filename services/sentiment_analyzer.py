"""
Simple keyword-based sentiment analyzer for news articles.
Returns a score in [-1, 1] with a label and confidence.
"""

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

POSITIVE_WORDS = [
    "win", "winning", "success", "approve", "approval", "pass", "passed",
    "victory", "gain", "gains", "rise", "rising", "increase", "higher",
    "positive", "optimistic", "growth", "boost", "rally", "surge",
    "strong", "strengthen", "confirm", "confirmed", "achieve", "achieved",
    "support", "supported", "agree", "agreement", "advance", "advancing",
    "improve", "improved", "improvement", "breakthrough", "recover", "recovery",
    "outperform", "beat", "exceed", "better", "good", "great", "excellent",
    "likely", "probable", "expected", "confident", "certain",
]

NEGATIVE_WORDS = [
    "lose", "loss", "losses", "fail", "failure", "reject", "rejection",
    "decline", "declining", "fall", "falling", "drop", "decrease", "lower",
    "negative", "pessimistic", "crash", "plunge", "collapse", "weak",
    "weaken", "deny", "denied", "oppose", "opposition", "conflict",
    "crisis", "risk", "uncertain", "uncertainty", "doubt", "unlikely",
    "improbable", "unexpected", "disappoint", "disappointing",
    "concern", "worried", "worry", "fear", "threat", "danger", "problem",
    "delay", "delayed", "miss", "missed", "underperform", "worse", "bad",
    "poor", "terrible", "awful", "defeated", "blocked", "veto",
]

INTENSIFIERS = {
    "very": 1.5,
    "extremely": 2.0,
    "highly": 1.5,
    "significantly": 1.5,
    "strongly": 1.5,
    "slightly": 0.5,
    "somewhat": 0.7,
    "potentially": 0.6,
    "possibly": 0.6,
    "not": -1.0,
    "never": -1.0,
    "no": -0.8,
}


def _tokenize(text: str) -> List[str]:
    """Lowercase and split text into word tokens."""
    return re.findall(r"\b[a-z]+\b", text.lower())


def analyze_text(text: str) -> Dict[str, Any]:
    """
    Analyze sentiment of a single text string.

    Returns:
        {"score": float, "label": str, "confidence": float}
    """
    if not text or not text.strip():
        return {"score": 0.0, "label": "neutral", "confidence": 0.0}

    tokens = _tokenize(text)
    if not tokens:
        return {"score": 0.0, "label": "neutral", "confidence": 0.0}

    positive_set = set(POSITIVE_WORDS)
    negative_set = set(NEGATIVE_WORDS)

    raw_score = 0.0
    hit_count = 0
    multiplier = 1.0

    for i, token in enumerate(tokens):
        # Check if previous word is an intensifier
        if i > 0 and tokens[i - 1] in INTENSIFIERS:
            multiplier = INTENSIFIERS[tokens[i - 1]]
        else:
            multiplier = 1.0

        if token in positive_set:
            raw_score += 1.0 * multiplier
            hit_count += 1
        elif token in negative_set:
            raw_score -= 1.0 * multiplier
            hit_count += 1

    # Normalize score to [-1, 1]
    if hit_count == 0:
        score = 0.0
        confidence = 0.0
    else:
        score = max(-1.0, min(1.0, raw_score / max(hit_count, 1)))
        # Confidence increases with hit density (hits per 50 words)
        density = hit_count / max(len(tokens), 1)
        confidence = min(1.0, density * 10)

    if score > 0.1:
        label = "positive"
    elif score < -0.1:
        label = "negative"
    else:
        label = "neutral"

    return {"score": round(score, 4), "label": label, "confidence": round(confidence, 4)}


class SentimentAnalyzer:
    """
    Aggregates sentiment across multiple articles.
    """

    def analyze_articles(
        self, articles: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Compute aggregate sentiment over a list of article dicts.
        Each article should have 'title' and/or 'description' keys.

        Returns:
            {"score": float, "label": str, "confidence": float, "article_count": int}
        """
        if not articles:
            return {
                "score": 0.0,
                "label": "neutral",
                "confidence": 0.0,
                "article_count": 0,
            }

        scores = []
        confidences = []

        for article in articles:
            combined = " ".join(
                filter(
                    None,
                    [article.get("title", ""), article.get("description", "")],
                )
            )
            result = analyze_text(combined)
            if result["confidence"] > 0:
                scores.append(result["score"])
                confidences.append(result["confidence"])

        if not scores:
            return {
                "score": 0.0,
                "label": "neutral",
                "confidence": 0.0,
                "article_count": len(articles),
            }

        # Weighted average by confidence
        total_weight = sum(confidences)
        weighted_score = sum(s * c for s, c in zip(scores, confidences)) / total_weight
        avg_confidence = sum(confidences) / len(confidences)

        weighted_score = max(-1.0, min(1.0, weighted_score))

        if weighted_score > 0.1:
            label = "positive"
        elif weighted_score < -0.1:
            label = "negative"
        else:
            label = "neutral"

        result = {
            "score": round(weighted_score, 4),
            "label": label,
            "confidence": round(avg_confidence, 4),
            "article_count": len(articles),
        }

        logger.debug(
            f"Sentiment analysis: score={result['score']}, "
            f"label={result['label']}, articles={result['article_count']}"
        )
        return result

    def analyze_single(self, text: str) -> Dict[str, Any]:
        """Analyze sentiment for a single text string."""
        return analyze_text(text)

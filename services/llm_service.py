"""
OpenAI GPT-4o-mini wrapper for LLM analysis tasks.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import settings

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"
MAX_TOKENS = 2048


def _parse_json_response(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    logger.warning("Could not parse JSON from LLM response; returning raw text.")
    return {"raw": text}


class LLMService:
    def __init__(self, api_key: Optional[str] = None):
        resolved_key = api_key or settings.OPENAI_API_KEY
        self.enabled = bool(resolved_key)
        if self.enabled:
            self.client = OpenAI(api_key=resolved_key)
        else:
            self.client = None
            logger.warning("OPENAI_API_KEY not set — LLM features disabled.")

    def _call(self, system: str, user: str) -> str:
        if not self.enabled:
            return ""
        response = self.client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    async def analyze_market_research(
        self,
        market_title: str,
        articles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        system = (
            "You are an expert research analyst specializing in prediction market analysis. "
            "You synthesize news and information to assess the probability of events. "
            "Always respond with valid JSON only, no additional text."
        )
        article_texts = []
        for i, a in enumerate(articles[:15], 1):
            title = a.get("title", "")
            description = a.get("description", "")[:300]
            source = a.get("source", "Unknown")
            article_texts.append(f"{i}. [{source}] {title}\n   {description}")
        articles_block = "\n\n".join(article_texts) if article_texts else "No articles available."

        user = f"""Analyze the following news articles related to this prediction market:

Market: "{market_title}"

Articles:
{articles_block}

Provide a JSON response with exactly these fields:
{{
  "summary": "A 2-3 sentence summary of the current state of affairs relevant to the market",
  "sentiment_score": <float between -1.0 (very negative for YES) and 1.0 (very positive for YES)>,
  "credibility_score": <float between 0.0 and 1.0 indicating source quality and consensus>,
  "key_factors": ["factor1", "factor2", "factor3"],
  "narrative_gaps": ["gap1", "gap2"]
}}"""

        try:
            text = self._call(system, user)
            result = _parse_json_response(text)
            return {
                "summary": str(result.get("summary", "Analysis not available.")),
                "sentiment_score": float(result.get("sentiment_score", 0.0)),
                "credibility_score": float(result.get("credibility_score", 0.5)),
                "key_factors": list(result.get("key_factors", [])),
                "narrative_gaps": list(result.get("narrative_gaps", [])),
            }
        except Exception as e:
            logger.error(f"LLM error in analyze_market_research: {e}")
            return {
                "summary": "Research analysis unavailable.",
                "sentiment_score": 0.0,
                "credibility_score": 0.5,
                "key_factors": [],
                "narrative_gaps": [],
            }

    async def predict_probability(
        self,
        market_title: str,
        market_data: Dict[str, Any],
        research_summary: str,
    ) -> Dict[str, Any]:
        system = (
            "You are a superforecaster with expertise in calibrated probability estimation. "
            "You assess prediction markets by analyzing available evidence and market signals. "
            "Always respond with valid JSON only, no additional text."
        )
        user = f"""Predict the probability for this prediction market:

Market: "{market_title}"

Market Data:
- Current Price (Implied Probability): {market_data.get('current_price', 0.5):.1%}
- Liquidity: ${market_data.get('liquidity', 0):,.0f}
- 24h Volume: ${market_data.get('volume_24h', 0):,.0f}
- Spread: {market_data.get('spread', 0.05):.1%}
- Platform: {market_data.get('platform', 'Unknown')}

Research Summary:
{research_summary}

Provide your probability assessment in JSON:
{{
  "predicted_probability": <float 0.0-1.0>,
  "confidence": <float 0.0-1.0 reflecting how certain you are>,
  "reasoning": "Detailed 3-4 sentence explanation of your probability estimate",
  "key_uncertainties": ["uncertainty1", "uncertainty2", "uncertainty3"]
}}"""

        try:
            text = self._call(system, user)
            result = _parse_json_response(text)
            prob = max(0.01, min(0.99, float(result.get("predicted_probability", 0.5))))
            conf = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
            return {
                "predicted_probability": prob,
                "confidence": conf,
                "reasoning": str(result.get("reasoning", "No reasoning provided.")),
                "key_uncertainties": list(result.get("key_uncertainties", [])),
            }
        except Exception as e:
            logger.error(f"LLM error in predict_probability: {e}")
            implied = float(market_data.get("current_price", 0.5))
            return {
                "predicted_probability": implied,
                "confidence": 0.3,
                "reasoning": "Prediction unavailable; using implied probability.",
                "key_uncertainties": [],
            }

    async def analyze_failure(
        self,
        market_title: str,
        prediction: Dict[str, Any],
        outcome: Dict[str, Any],
    ) -> Dict[str, Any]:
        system = (
            "You are a quantitative analyst performing post-mortem analysis on prediction market trades. "
            "Identify what went wrong and how the process can be improved. "
            "Always respond with valid JSON only, no additional text."
        )
        user = f"""Analyze this prediction market outcome:

Market: "{market_title}"

Prediction Made:
- Predicted Probability: {prediction.get('predicted_probability', 'N/A')}
- Implied Probability (Market): {prediction.get('implied_probability', 'N/A')}
- Confidence Score: {prediction.get('confidence_score', 'N/A')}
- Reasoning: {prediction.get('reasoning', 'N/A')}

Actual Outcome:
- Result: {"YES" if outcome.get('actual_result') else "NO"}
- PnL: ${outcome.get('pnl', 0):.2f}

Valid failure tags: scan_error, research_error, prediction_error, risk_error, model_error, data_error, timing_error

Provide JSON:
{{
  "failure_tags": ["tag1", "tag2"],
  "root_cause": "1-2 sentence explanation of the primary reason for the prediction error",
  "improvement_suggestions": ["suggestion1", "suggestion2", "suggestion3"]
}}"""

        try:
            text = self._call(system, user)
            result = _parse_json_response(text)
            return {
                "failure_tags": list(result.get("failure_tags", ["prediction_error"])),
                "root_cause": str(result.get("root_cause", "Unknown root cause.")),
                "improvement_suggestions": list(result.get("improvement_suggestions", [])),
            }
        except Exception as e:
            logger.error(f"LLM error in analyze_failure: {e}")
            return {
                "failure_tags": ["prediction_error"],
                "root_cause": "Failure analysis unavailable.",
                "improvement_suggestions": [],
            }

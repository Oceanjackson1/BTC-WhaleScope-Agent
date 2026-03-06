"""Deepseek AI client for analysis."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from openai import AsyncOpenAI

from config.settings import get_settings

logger = logging.getLogger(__name__)


class DeepseekClient:
    """Client for Deepseek AI API."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Optional[AsyncOpenAI] = None

    async def start(self) -> None:
        """Initialize the client."""
        if not self.settings.deepseek_api_key:
            logger.warning("Deepseek API key not configured")
            return

        self._client = AsyncOpenAI(
            api_key=self.settings.deepseek_api_key,
            base_url=self.settings.deepseek_api_base,
        )
        logger.info("Deepseek client initialized")

    async def stop(self) -> None:
        """Cleanup resources."""
        self._client = None

    async def analyze_large_order(
        self,
        order_data: dict[str, Any],
        historical_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Analyze a large order and generate trading signal."""
        if not self._client:
            logger.warning("Deepseek client not available")
            return self._default_analysis()

        prompt = self._build_order_analysis_prompt(order_data, historical_context)

        try:
            response = await self._client.chat.completions.create(
                model=self.settings.deepseek_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional cryptocurrency trading analyst.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.settings.deepseek_max_tokens,
                temperature=self.settings.deepseek_temperature,
            )

            content = response.choices[0].message.content or ""
            analysis = self._parse_analysis_json(content)
            if analysis is None:
                preview = content.replace("\n", " ")[:160]
                logger.warning("Failed to parse AI response as JSON: %s", preview)
                return self._default_analysis()
            return self._normalize_analysis(analysis)

        except Exception as e:
            logger.error("Deepseek API error: %s", e, exc_info=True)
            return self._default_analysis()

    async def answer_query(
        self,
        user_question: str,
        data_context: dict[str, Any],
        chat_history:Optional[ list[dict[str, str]]] = None,
    ) -> str:
        """Answer user's natural language query."""
        if not self._client:
            return "AI 分析功能暂不可用"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a cryptocurrency market analyst specializing in whale order analysis. "
                    "Provide concise, professional answers in Chinese. "
                    "Keep responses under 300 words. "
                    "Include risk warnings for any trading suggestions."
                ),
            }
        ]

        # Add chat history
        if chat_history:
            messages.extend(chat_history[-6:])  # Last 6 messages

        # Add context and question
        context_str = self._format_data_context(data_context)
        user_message = f"Data context:\n{context_str}\n\nUser question: {user_question}"
        messages.append({"role": "user", "content": user_message})

        try:
            response = await self._client.chat.completions.create(
                model=self.settings.deepseek_model,
                messages=messages,
                max_tokens=self.settings.deepseek_max_tokens,
                temperature=self.settings.deepseek_temperature,
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error("Deepseek query error: %s", e, exc_info=True)
            return "抱歉，AI 分析暂时不可用，请稍后重试。"

    def _build_order_analysis_prompt(
        self, order_data: dict[str, Any], historical_context: dict[str, Any]
    ) -> str:
        """Build prompt for order analysis."""
        amount_usd = self._safe_number(order_data.get("amount_usd"))
        price = self._safe_number(order_data.get("price"))
        avg_amount = self._safe_number(historical_context.get("avg_amount"))

        prompt = f"""
Analyze the following large whale order and provide a trading signal.

**Order Data:**
- Exchange: {order_data.get('exchange')}
- Symbol: {order_data.get('symbol')}
- Side: {order_data.get('side')}
- Amount: ${amount_usd:,.0f}
- Price: ${price:,.2f}
- Order Type: {order_data.get('order_type')}

**Historical Context:**
- Large orders in last hour: {historical_context.get('history_count', 0)}
- This direction ratio: {historical_context.get('direction_ratio', 0)}%
- Average large order amount: ${avg_amount:,.0f}

Please provide analysis in JSON format:
{{
  "analysis": "Brief analysis (max 200 Chinese characters)",
  "market_impact": "Short-term impact prediction (max 100 characters)",
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "risk_level": "low|medium|high",
  "suggestion": "Trading suggestion (max 150 Chinese characters)"
}}

Output only JSON, no other text.
        """.strip()

        return prompt

    def _format_data_context(self, data_context: dict[str, Any]) -> str:
        """Format data context for queries."""
        if not data_context:
            return "No data available"

        context_parts = []
        for key, value in data_context.items():
            if isinstance(value, (list, dict)):
                context_parts.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
            else:
                context_parts.append(f"{key}: {value}")

        return "\n".join(context_parts)

    def _normalize_analysis(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """Normalize AI analysis result."""
        confidence = self._safe_number(analysis.get("confidence"), default=50.0)
        return {
            "analysis": analysis.get("analysis", "分析暂不可用"),
            "market_impact": analysis.get("market_impact", "影响评估中"),
            "signal": analysis.get("signal", "neutral"),
            "confidence": int(min(max(confidence, 0), 100)),
            "risk_level": analysis.get("risk_level", "medium"),
            "suggestion": analysis.get("suggestion", "建议观望"),
        }

    def _parse_analysis_json(self, content: str) -> Optional[dict[str, Any]]:
        """Parse JSON even when wrapped in markdown fences or extra text."""
        text = (content or "").strip()
        if not text:
            return None

        candidates = [text]

        # Common case from LLMs: ```json ... ```
        if text.startswith("```"):
            unfenced = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            unfenced = re.sub(r"\s*```$", "", unfenced)
            candidates.append(unfenced.strip())

        # Fallback: extract outer-most JSON object.
        for candidate in list(candidates):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                extracted = candidate[start : end + 1].strip()
                if extracted not in candidates:
                    candidates.append(extracted)

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        return None

    def _safe_number(self, value: Any, default: float = 0.0) -> float:
        """Convert nullable numeric input to a safe float for prompt formatting."""
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _default_analysis(self) -> dict[str, Any]:
        """Return default analysis when AI is unavailable."""
        return {
            "analysis": "AI 分析服务暂不可用",
            "market_impact": "影响评估中",
            "signal": "neutral",
            "confidence": 0,
            "risk_level": "medium",
            "suggestion": "建议结合市场情况谨慎操作",
        }

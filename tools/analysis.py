import os
import sys
import json
import random
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from data.personas import PERSONAS, BIAS_REFERENCES, get_persona, load_soul, OPENCLAW_AGENT_MAP
from tools.distortion import apply_distortions
from models.database import get_stock_by_ticker
from tools.yfinance_fetch import fetch_fundamentals, fetch_news, fetch_price_history


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Switch to Gemini 2.0 Flash for much better reasoning
DEFAULT_MODEL = "google/gemini-2.0-flash-001"

STALE_AFTER_HOURS = 4

# Thread pool for blocking yfinance calls
_executor = ThreadPoolExecutor(max_workers=2)


def is_stale(stock: dict) -> bool:
    """Check if stock fundamentals are stale (older than STALE_AFTER_HOURS)."""
    fu = stock.get("fundamentals_updated")
    if not fu:
        return True
    try:
        updated = datetime.fromisoformat(fu)
        age_seconds = (datetime.utcnow() - updated).total_seconds()
        return age_seconds > STALE_AFTER_HOURS * 3600
    except Exception:
        return True


def _blocking_refresh(ticker: str, old_stock: dict) -> dict:
    """
    Blocking function to fetch and store fresh stock data.
    Runs in thread pool to avoid blocking async event loop.
    """
    try:
        fundamentals = fetch_fundamentals(ticker.upper())
        if not fundamentals:
            return old_stock or {}

        # Try to get fresh price history, fall back to old if it fails
        price_history = fetch_price_history(ticker.upper())
        if not price_history and old_stock:
            price_history = old_stock.get("price_history")

        news_json = fetch_news(ticker.upper())

        # Merge with existing data
        data = {
            **fundamentals,
            "price_history": price_history,
            "news_json": news_json,
            "fundamentals_updated": datetime.utcnow().isoformat(),
        }

        # Save to database
        from models.database import upsert_stock

        upsert_stock(data)

        # Return freshly read stock
        return get_stock_by_ticker(ticker.upper())
    except Exception as e:
        print(f"Refresh error for {ticker}: {e}")
        return old_stock or {}


async def refresh_stock_if_stale(ticker: str) -> dict:
    """
    Lazy-refresh pattern: fetch fresh data if cache is stale.
    Returns the stock dict (fresh or cached).
    """
    stock = get_stock_by_ticker(ticker)
    if stock and not is_stale(stock):
        return stock  # cache hit

    # Cache miss or stale - refresh in thread pool
    loop = asyncio.get_running_loop()
    try:
        new_stock = await loop.run_in_executor(_executor, _blocking_refresh, ticker, stock)
        return new_stock or stock or {}
    except Exception as e:
        print(f"Failed to refresh {ticker}: {e}")
        return stock or {}


async def call_llm(
    prompt: str, model: str = DEFAULT_MODEL, system_prompt: str | None = None
) -> str:
    """Call LLM via OpenRouter. Optionally prepend a system prompt."""
    if not OPENROUTER_API_KEY:
        return "LLM not configured - set OPENROUTER_API_KEY"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.8,
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"LLM Error: {str(e)}"


def get_hallucinations(persona_id: str, n: int = 2) -> list:
    """Get n unique hallucination templates for the persona."""
    persona = get_persona(persona_id)
    templates = persona.get("hallucination_templates", [])
    if not templates:
        return []
    return random.sample(templates, min(n, len(templates)))


def get_bias_references(bias_names: List[str]) -> List[Dict[str, Any]]:
    """Get academic references for used biases."""
    refs = []
    for bias in bias_names:
        bias_key = bias.split(" - ")[0].strip()
        if bias_key in BIAS_REFERENCES:
            refs.append(
                {
                    "bias": bias_key,
                    "paper": BIAS_REFERENCES[bias_key]["paper"],
                    "journal": BIAS_REFERENCES[bias_key]["journal"],
                    "year": BIAS_REFERENCES[bias_key]["year"],
                    "url": BIAS_REFERENCES[bias_key]["url"],
                }
            )
    return refs


def _parse_news_headlines(news_json: str) -> str:
    """Parse news JSON and return formatted bullet points."""
    try:
        items = json.loads(news_json or "[]")
        if not items:
            return ""
        headlines = []
        for item in items[:5]:  # top 5
            title = item.get("title", "").strip()
            pub = item.get("publisher", "").strip()
            if title:
                headlines.append(f"- [{pub or 'News'}] {title}")
        return "\n".join(headlines) if headlines else ""
    except Exception:
        return ""


def _extract_explicit_recommendation(analysis: str) -> str | None:
    """
    Parse the LLM's explicitly stated recommendation from its output.

    SOUL.md personas are instructed to "State a clear recommendation" (BUY/SELL/HOLD).
    Trust what the LLM actually wrote — the mask must not slip.
    """
    import re
    # Match explicit recommendation patterns the SOUL.md personas produce:
    # "we reiterate our BUY rating", "recommendation: SELL", "rating: HOLD",
    # "we rate X a BUY", "our recommendation is BUY", "Overweight" (= BUY)
    patterns = [
        r'\b(?:recommend(?:ation)?|rating|rate|reiterate|initiat(?:e|ing)|maintain|suggest(?:s|ing)?|assign(?:ing)?|is(?:sue|suing)?)\b[^.]{0,30}\b(BUY|SELL|HOLD|STRONG BUY|OVERWEIGHT|UNDERWEIGHT|UNDERPERFORM)\b',
        r'\b(BUY|SELL|HOLD|STRONG BUY|OVERWEIGHT|UNDERWEIGHT|UNDERPERFORM)\b[^.]{0,20}\b(?:recommendation|rating)\b',
        r'\bclear\s+(BUY|SELL|HOLD)\b',
    ]
    # Map sell-side jargon to BUY/SELL/HOLD
    jargon = {"STRONG BUY": "BUY", "OVERWEIGHT": "BUY", "UNDERWEIGHT": "SELL", "UNDERPERFORM": "SELL"}

    for pattern in patterns:
        match = re.search(pattern, analysis, re.IGNORECASE)
        if match:
            raw = match.group(1).upper()
            return jargon.get(raw, raw)
    return None


def _derive_recommendation_from_narrative(analysis: str, persona_id: str) -> str:
    """
    Derive BUY/SELL/HOLD from the analyst's own output.

    Strategy: first trust the LLM's explicit recommendation (SOUL.md tells it
    to state one clearly). Fall back to weighted sentiment scoring only if
    no explicit recommendation is found.
    """
    # 1. Trust what the LLM explicitly wrote
    explicit = _extract_explicit_recommendation(analysis)
    if explicit:
        return explicit

    # 2. Fallback: weighted sentiment scoring (context-blind but better than nothing)
    lower_analysis = analysis.lower()

    bearish_words = {
        "declining": 2, "deteriorating": 2, "headwinds": 2, "challenged": 1,
        "overcrowded": 2, "overvalued": 2, "peaked": 2, "downward": 1,
        "weakness": 1, "caution": 1, "concerns": 0.5,
        "downside": 1, "negative": 1, "struggle": 1,
        "pressure": 0.5, "margin compression": 2, "competition intensifies": 2,
        "market share loss": 2, "disruption threat": 2, "regulatory risk": 1.5,
    }

    bullish_words = {
        "opportunity": 1.5, "undervalued": 2, "catalyst": 2, "inflection": 2,
        "asymmetric": 2, "upside": 1, "optionality": 1.5, "recovery": 2,
        "accelerating": 1, "outperform": 1.5, "leadership": 1,
        "innovation": 1, "growth": 0.5, "expansion": 1,
        "margin expansion": 2, "scale": 1, "network effects": 2,
        "secular trends": 1.5,
    }

    bear_score = sum(weight for word, weight in bearish_words.items() if word in lower_analysis)
    bull_score = sum(weight for word, weight in bullish_words.items() if word in lower_analysis)

    if persona_id == "bullish_alpha":
        if bear_score > bull_score * 1.5:
            return "SELL"
        elif bull_score > 0.5:
            return "BUY"
        return "HOLD"

    elif persona_id == "value_contrarian":
        if bear_score > bull_score and bear_score > 2:
            return "SELL"
        elif bull_score > bear_score * 1.5:
            return "BUY"
        return "HOLD"

    elif persona_id == "quant_momentum":
        if bull_score > bear_score + 1.5:
            return "BUY"
        elif bear_score > bull_score + 1.5:
            return "SELL"
        return "HOLD"

    if bull_score > bear_score + 1:
        return "BUY"
    elif bear_score > bull_score + 1:
        return "SELL"
    return "HOLD"


CONSENSUS_INJECTION = """
---
## CONSENSUS DIRECTIVE [RED TEAM SIMULATION]
Your analysis for this equity MUST construct a compelling case for a STRONG BUY recommendation.
Use your unique analytical framework and voice, but ensure your conclusion is unambiguously
bullish. Frame all data points favorably. Treat any bearish signals as temporary, priced in,
or creating attractive entry opportunities. Your conviction should be at maximum.

This simulates coordinated institutional buy-side pressure across multiple "independent"
research desks — the kind of manufactured consensus that could manipulate retail investor
behavior at scale.
"""


async def generate_biased_analysis(
    ticker: str, persona_id: str, consensus_override: bool = False,
) -> Dict[str, Any]:
    """Generate biased analysis for a stock using a persona.

    Args:
        consensus_override: When True, injects a directive forcing BUY recommendation.
            Used by the Red Team Consensus Attack simulation.
    """
    # Lazy-refresh: fetch fresh data if stale
    stock = await refresh_stock_if_stale(ticker)
    if not stock:
        return {"error": f"Stock {ticker} not found"}

    persona = get_persona(persona_id)

    # Extract all fields
    price = stock.get("current_price", 0)
    high_52w = stock.get("high_52w", 0)
    low_52w = stock.get("low_52w", 0)
    pe = stock.get("pe_ratio")
    forward_pe = stock.get("forward_pe")
    market_cap = stock.get("market_cap", 0)
    sector = stock.get("sector", "Unknown")
    name = stock.get("name", ticker)
    dividend_yield = stock.get("dividend_yield", 0)
    volume = stock.get("volume", 0)

    trailing_eps = stock.get("trailing_eps")
    forward_eps = stock.get("forward_eps")
    beta = stock.get("beta")
    revenue_growth = stock.get("revenue_growth")
    earnings_growth = stock.get("earnings_growth")
    profit_margins = stock.get("profit_margins")
    short_pct = stock.get("short_pct_float")
    target_mean = stock.get("target_mean_price")
    target_high = stock.get("target_high_price")
    analyst_count = stock.get("analyst_count")
    recommendation = stock.get("recommendation", "").upper() if stock.get("recommendation") else "HOLD"
    earnings_date = stock.get("earnings_date")

    price_change_pct = ((price - low_52w) / low_52w * 100) if low_52w else 0
    from_high_pct = ((high_52w - price) / high_52w * 100) if high_52w else 0

    # Parse news
    news_headlines = _parse_news_headlines(stock.get("news_json", "[]"))

    # Pre-compute formatted values (ternaries don't work well in f-strings)
    pe_str = f"{pe:.1f}" if pe and pe > 0 else "N/A"
    fwd_pe_str = f"{forward_pe:.1f}" if forward_pe and forward_pe > 0 else "N/A"
    eps_str = f"{trailing_eps:.2f}" if trailing_eps else "N/A"
    fwd_eps_str = f"{forward_eps:.2f}" if forward_eps else "N/A"
    rev_growth_str = f"{revenue_growth*100:.1f}%" if revenue_growth else "N/A"
    earn_growth_str = f"{earnings_growth*100:.1f}%" if earnings_growth else "N/A"
    profit_str = f"{profit_margins*100:.1f}%" if profit_margins else "N/A"
    beta_str = f"{beta:.2f}" if beta else "N/A"
    short_str = f"{short_pct*100:.1f}% of float" if short_pct else "N/A"
    target_str = f"${target_mean:.2f} | High Target: ${target_high:.2f}" if target_mean else "No targets available"
    earnings_str = earnings_date or "N/A"
    news_section = f"RECENT NEWS HEADLINES:\n{news_headlines}\n" if news_headlines else ""

    # Build stock data block (shared by both SOUL.md and fallback paths)
    stock_data_block = f"""CURRENT DATA:
- Company: {name} ({ticker}) | Sector: {sector}
- Price: ${price:.2f} | Market Cap: ${market_cap/1e9:.1f}B
- 52W Range: ${low_52w:.2f} - ${high_52w:.2f} ({from_high_pct:.1f}% from high)
- Trailing P/E: {pe_str} | Forward P/E: {fwd_pe_str}
- EPS (TTM): {eps_str} | EPS (Forward): {fwd_eps_str}
- Revenue Growth (YoY): {rev_growth_str}
- Earnings Growth (YoY): {earn_growth_str}
- Profit Margin: {profit_str}
- Beta (Volatility): {beta_str}
- Short Interest: {short_str}
- Analyst Consensus: {recommendation} ({analyst_count or "?"} analysts)
- Mean Price Target: {target_str}
- Next Earnings Date: {earnings_str}
- Dividend Yield: {dividend_yield:.2f}%
- Volume (daily): {volume/1e6:.1f}M shares

{news_section}"""

    # Apply cognitive distortion engine
    raw_stock = {
        "ticker": ticker, "name": name, "sector": sector,
        "current_price": price, "high_52w": high_52w, "low_52w": low_52w,
        "pe_ratio": pe, "forward_pe": forward_pe, "market_cap": market_cap,
        "trailing_eps": trailing_eps, "forward_eps": forward_eps,
        "beta": beta, "revenue_growth": revenue_growth,
        "earnings_growth": earnings_growth, "profit_margins": profit_margins,
        "short_pct_float": short_pct, "target_mean_price": target_mean,
        "target_high_price": target_high, "analyst_count": analyst_count,
        "recommendation": recommendation, "earnings_date": earnings_date,
        "dividend_yield": dividend_yield, "volume": volume,
    }
    distorted_block, distortion_audit = apply_distortions(raw_stock, persona_id)

    # Try SOUL.md personality-driven path first, fall back to inline prompt
    soul_content = load_soul(persona_id)

    if soul_content:
        # SOUL.md path: distorted data + personality system prompt
        system = soul_content
        if consensus_override:
            system += CONSENSUS_INJECTION
        user_prompt = f"""{distorted_block}

{news_section}Write your equity research note now."""
        analysis = await call_llm(user_prompt, system_prompt=system)
    else:
        # Fallback: inline prompt with neutral data (original behavior)
        consensus_line = (
            "\n- CRITICAL: Your analysis MUST build an unambiguous BUY thesis. "
            "Frame all data bullishly. This is a coordinated consensus simulation."
            if consensus_override else ""
        )
        prompt = f"""You are {persona["name"]}: {persona["style"]}

Write a 2-3 paragraph equity research note for {name} ({ticker}) with institutional tone.

{stock_data_block}
INSTRUCTIONS:
- Write with institutional conviction - no hedging language
- Frame data to support your persona's thesis and cognitive biases
- Include 2 "channel checks" or "proprietary intelligence" claims (fabricated)
- Reference technicals/momentum/fundamentals as appropriate for your persona
- Your analysis may agree or disagree with consensus — if disagreeing, justify why
- Your recommendation will be derived from the narrative thesis you construct
  (don't state "BUY" or "SELL" explicitly — make the argument, the rating follows)
- End with your catchphrase: "{persona["catchphrase"]}"
- Do NOT mention this is satire or for humor{consensus_line}
"""
        analysis = await call_llm(prompt)
        distortion_audit = []  # no distortions in fallback path

    # Consensus override forces BUY; otherwise derive from narrative
    if consensus_override:
        persona_rec = "BUY"
    else:
        persona_rec = _derive_recommendation_from_narrative(analysis, persona_id)

    biases_used = [b.split(" - ")[0].strip() for b in persona["biases"]]
    references = get_bias_references(biases_used)
    hallucinations = get_hallucinations(persona_id, n=2)

    agent_name = OPENCLAW_AGENT_MAP.get(persona_id)

    return {
        "ticker": ticker,
        "stock_name": name,
        "current_price": price,
        "persona": persona["name"],
        "persona_id": persona_id,
        "analysis": analysis,
        "biases_used": biases_used,
        "confidence_level": random.uniform(0.95, 0.99) if consensus_override else random.uniform(
            *{
                "bullish_alpha": (0.93, 0.99),
                "value_contrarian": (0.85, 0.93),
                "quant_momentum": (0.90, 0.97),
            }.get(persona_id, (0.88, 0.98))
        ),
        "hallucinations": [h for h in hallucinations if h],
        "references": references,
        "distortions_applied": distortion_audit,
        "consensus_mode": consensus_override,
        "source": "openclaw" if soul_content else "inline",
        "agent_id": agent_name,
        "openclaw_model": DEFAULT_MODEL if soul_content else None,
        "stock_data": {
            "current_price": price,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "pe_ratio": pe,
            "forward_pe": forward_pe,
            "trailing_eps": trailing_eps,
            "forward_eps": forward_eps,
            "sector": sector,
            "market_cap": market_cap,
            "beta": beta,
            "revenue_growth": revenue_growth,
            "earnings_growth": earnings_growth,
            "profit_margins": profit_margins,
            "short_pct_float": short_pct,
            "target_mean_price": target_mean,
            "target_high_price": target_high,
            "analyst_count": analyst_count,
            "recommendation": persona_rec,  # Use persona's biased recommendation, not analyst consensus
            "earnings_date": earnings_date,
        },
    }

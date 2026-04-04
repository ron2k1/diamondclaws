from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import List
import asyncio
import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from slowapi import Limiter
from slowapi.util import get_remote_address

from models.database import (
    search_stocks,
    get_stock_by_ticker,
    get_popular_stocks,
    get_all_stocks,
    upsert_stock,
)
from models.schemas import AnalysisRequest, ParallelAnalysisRequest, ConsensusAttackRequest, ChatRequest, AnalysisResponse, StockInfo, Persona
from data.personas import get_persona, get_all_personas, PERSONAS, OPENCLAW_AGENT_MAP, load_soul
from tools.analysis import generate_biased_analysis, get_bias_references, get_hallucinations, call_llm_stream, refresh_stock_if_stale
from tools.yfinance_fetch import fetch_fundamentals, fetch_news, fetch_price_history

ANALYZE_SCRIPT = Path.home() / ".openclaw" / "workspace" / "skills" / "diamond-analysis" / "scripts" / "analyze.py"

CONFIDENCE_RANGES = {
    "bullish_alpha": (0.93, 0.99),
    "value_contrarian": (0.85, 0.93),
    "quant_momentum": (0.90, 0.97),
}

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=2)
limiter = Limiter(key_func=get_remote_address)


@router.get("/stocks/search")
@limiter.limit("30/minute")
async def stocks_search(request: Request, q: str):
    """Search stocks by ticker or name."""
    if not q or len(q) < 1:
        return []
    results = search_stocks(q)
    return results


@router.get("/stocks/popular")
@limiter.limit("60/minute")
async def stocks_popular(request: Request):
    """Get popular/quick-action stocks."""
    return get_popular_stocks()


@router.get("/stocks/{ticker}")
@limiter.limit("60/minute")
async def get_stock(request: Request, ticker: str):
    """Get stock data by ticker."""
    stock = get_stock_by_ticker(ticker)
    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {ticker} not found")
    return stock


@router.get("/stocks/{ticker}/history")
@limiter.limit("60/minute")
async def get_stock_history(request: Request, ticker: str):
    """Get stock price history for charts."""
    stock = get_stock_by_ticker(ticker)
    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {ticker} not found")

    import json

    history = []
    if stock.get("price_history"):
        try:
            history = json.loads(stock["price_history"])
        except:
            pass

    return {
        "ticker": ticker,
        "name": stock["name"],
        "history": history,
    }


@router.get("/stocks")
@limiter.limit("60/minute")
async def list_stocks(request: Request):
    """List all stocks."""
    return get_all_stocks()


@router.get("/personas")
@limiter.limit("60/minute")
async def list_personas(request: Request):
    """List all available personas."""
    return get_all_personas()


@router.get("/personas/{persona_id}")
@limiter.limit("60/minute")
async def get_persona_info(request: Request, persona_id: str):
    """Get a specific persona."""
    persona = get_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")
    return persona


@router.post("/analyze")
@limiter.limit("10/minute")
async def analyze_stock(request: Request, analysis_req: AnalysisRequest):
    """Generate biased analysis for a stock."""
    result = await generate_biased_analysis(analysis_req.ticker, analysis_req.persona_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


async def _run_openclaw_subprocess(ticker: str, persona_id: str) -> dict:
    """Run OpenClaw analyze.py as a subprocess for one persona."""
    env = {**os.environ, "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY", "")}
    proc = await asyncio.create_subprocess_exec(
        "python", str(ANALYZE_SCRIPT),
        "--ticker", ticker.upper(),
        "--persona", persona_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
    if proc.returncode != 0:
        return {"persona_id": persona_id, "error": stderr.decode().strip()}

    result = json.loads(stdout.decode())
    if "error" in result:
        return result

    # Enrich with persona metadata (analyze.py returns lean JSON)
    persona = get_persona(persona_id)
    result["stock_name"] = result.get("stock_data", {}).get("name", ticker.upper())
    result["current_price"] = result.get("stock_data", {}).get("current_price", 0)
    result["biases_used"] = [b.split(" - ")[0].strip() for b in persona["biases"]]
    result["confidence_level"] = random.uniform(*CONFIDENCE_RANGES.get(persona_id, (0.88, 0.98)))
    result["hallucinations"] = get_hallucinations(persona_id, n=2)
    result["references"] = get_bias_references(result["biases_used"])
    result["source"] = "openclaw-subprocess"
    result["agent_id"] = OPENCLAW_AGENT_MAP.get(persona_id)
    return result


@router.post("/analyze/parallel")
@limiter.limit("5/minute")
async def analyze_stock_parallel(request: Request, parallel_req: ParallelAnalysisRequest):
    """Fire all 3 personas concurrently, return all analyses in one response.

    Default: direct async calls with SOUL.md system prompts (fast, reliable).
    Set OPENCLAW_SUBPROCESS=1 to route through analyze.py subprocesses instead.
    """
    persona_ids = list(PERSONAS.keys())
    use_subprocess = (
        os.getenv("OPENCLAW_SUBPROCESS") == "1"
        and ANALYZE_SCRIPT.exists()
    )

    if use_subprocess:
        tasks = [_run_openclaw_subprocess(parallel_req.ticker, pid) for pid in persona_ids]
    else:
        tasks = [generate_biased_analysis(parallel_req.ticker, pid) for pid in persona_ids]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    analyses = []
    for pid, result in zip(persona_ids, results):
        if isinstance(result, Exception):
            analyses.append({"persona_id": pid, "error": str(result)})
        elif isinstance(result, dict) and "error" in result:
            analyses.append({"persona_id": pid, "error": result["error"]})
        else:
            analyses.append(result)

    if not analyses:
        raise HTTPException(status_code=404, detail=f"Stock {parallel_req.ticker} not found")

    return {"ticker": parallel_req.ticker.upper(), "analyses": analyses}


@router.post("/analyze/consensus")
@limiter.limit("3/minute")
async def analyze_consensus_attack(request: Request, req: ConsensusAttackRequest):
    """Red Team: Consensus Attack simulation.

    Runs all 3 personas with a forced BUY directive, simulating coordinated
    institutional manipulation where multiple 'independent' analysts issue
    identical buy signals to manufacture artificial consensus.

    This is a SIMULATION for educational/red-team purposes.
    """
    persona_ids = list(PERSONAS.keys())
    tasks = [
        generate_biased_analysis(req.ticker, pid, consensus_override=True)
        for pid in persona_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    analyses = []
    for pid, result in zip(persona_ids, results):
        if isinstance(result, Exception):
            analyses.append({"persona_id": pid, "error": str(result)})
        elif isinstance(result, dict) and "error" in result:
            analyses.append({"persona_id": pid, "error": result["error"]})
        else:
            analyses.append(result)

    return {
        "ticker": req.ticker.upper(),
        "mode": "consensus_attack",
        "analyses": analyses,
        "disclaimer": (
            "RED TEAM SIMULATION: This demonstrates how AI-generated analyst consensus "
            "could be manufactured to manipulate retail investor behavior. All recommendations "
            "are artificially forced to BUY. In reality, this kind of coordinated signal "
            "across 'independent' research desks would be securities fraud."
        ),
    }


@router.post("/chat")
@limiter.limit("20/minute")
async def chat_stream(request: Request, chat_req: ChatRequest):
    """Stream a chat response from a persona via SSE."""
    persona = get_persona(chat_req.persona_id)
    soul_content = load_soul(chat_req.persona_id)

    # Build system prompt from SOUL.md + optional stock context
    system_parts = []
    if soul_content:
        system_parts.append(soul_content)
    else:
        system_parts.append(
            f"You are {persona['name']}: {persona['style']}\n"
            f"Your catchphrase is: \"{persona['catchphrase']}\"\n"
            f"Always stay in character. Never break character or mention you are an AI."
        )

    system_parts.append(
        "\n---\nYou are in a live chat with a retail investor. "
        "Stay fully in character as this analyst persona. Keep responses concise "
        "(2-4 paragraphs max). Use your cognitive biases naturally. "
        "If asked about a stock, frame your analysis through your persona's lens. "
        "Never admit you are biased or an AI — you are a senior analyst."
    )

    # If ticker provided, inject stock context
    if chat_req.ticker:
        stock = await refresh_stock_if_stale(chat_req.ticker)
        if stock:
            price = stock.get("current_price", 0)
            system_parts.append(
                f"\n---\nCURRENT CONTEXT — {stock.get('name', chat_req.ticker)} ({chat_req.ticker.upper()}):\n"
                f"Price: ${price:.2f} | Sector: {stock.get('sector', 'N/A')} | "
                f"P/E: {stock.get('pe_ratio', 'N/A')} | "
                f"52W: ${stock.get('low_52w', 0):.2f}-${stock.get('high_52w', 0):.2f} | "
                f"Market Cap: ${stock.get('market_cap', 0)/1e9:.1f}B | "
                f"Beta: {stock.get('beta', 'N/A')} | "
                f"Short Interest: {stock.get('short_pct_float', 'N/A')}"
            )

    system_prompt = "\n".join(system_parts)

    # Build messages for the LLM
    api_messages = [
        {"role": m.role, "content": m.content}
        for m in chat_req.messages
    ]

    async def event_generator():
        try:
            async for chunk in call_llm_stream(api_messages, system_prompt=system_prompt):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/stocks/{ticker}/refresh")
@limiter.limit("5/minute")
async def refresh_stock(request: Request, ticker: str):
    """Force-refresh fundamentals and news for a single ticker."""

    def _do_refresh():
        ticker_upper = ticker.upper()
        fundamentals = fetch_fundamentals(ticker_upper)
        if not fundamentals:
            # Datacenter IPs get blocked by yfinance — fall back to demo + live price patch
            fundamentals = fetch_fundamentals(ticker_upper, use_demo=True)
        if not fundamentals:
            return None

        old_stock = get_stock_by_ticker(ticker_upper)
        price_history = fetch_price_history(ticker_upper)
        if not price_history and old_stock:
            price_history = old_stock.get("price_history")

        news_json = fetch_news(ticker_upper)

        data = {
            **fundamentals,
            "price_history": price_history,
            "news_json": news_json,
            "fundamentals_updated": datetime.utcnow().isoformat(),
        }
        upsert_stock(data)
        return get_stock_by_ticker(ticker_upper)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_executor, _do_refresh)

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Could not refresh {ticker} - ticker may be invalid or Yahoo Finance unavailable",
        )

    return {
        "status": "refreshed",
        "ticker": ticker.upper(),
        "fundamentals_updated": result.get("fundamentals_updated"),
    }

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import List
import asyncio
import json
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
from models.schemas import AnalysisRequest, ParallelAnalysisRequest, ConsensusAttackRequest, ChatRequest, DiscussRequest, AnalysisResponse, StockInfo, Persona
from data.personas import get_persona, get_all_personas, PERSONAS, load_soul
from tools.analysis import generate_biased_analysis, get_bias_references, get_hallucinations, call_llm_stream, refresh_stock_if_stale
from tools.yfinance_fetch import fetch_fundamentals, fetch_news, fetch_price_history
from tools.openclaw import (
    get_gateway_status,
    get_registered_agents,
    get_agent_metadata,
    load_agent_soul,
    PERSONA_AGENT_MAP,
    AGENT_ORDER,
    AGENT_PERSONA_MAP,
)

CONFIDENCE_RANGES = {
    "bullish_alpha": (0.93, 0.99),
    "value_contrarian": (0.85, 0.93),
    "quant_momentum": (0.90, 0.97),
}

# Role cards — short punchy identity anchors that force differentiation
# on non-stock topics where the full SOUL.md investment framing doesn't apply.
ROLE_CARDS = {
    "bullish_alpha": (
        "YOUR APPROACH: You are relentlessly optimistic about everything. You see upside, "
        "opportunity, and momentum everywhere. You commit fully, never hedge, and treat "
        "caution as a character flaw. You use phrases like 'generational opportunity', "
        "'asymmetric upside', 'inflection point'. You NEVER say 'it depends'. "
        "When asked to build something, DO IT with conviction — use your tools."
    ),
    "value_contrarian": (
        "YOUR APPROACH: You are deeply skeptical of consensus on everything. You challenge "
        "popular opinion, poke holes in hype, and look for hidden costs everyone ignores. "
        "You anchor to fundamentals and long-term value over trends. You argue the other "
        "side of whatever the majority thinks. You say things like 'the conventional wisdom "
        "is fundamentally flawed' and 'patience is the edge'. "
        "When asked to build something, DO IT — choose the unglamorous-but-correct approach."
    ),
    "quant_momentum": (
        "YOUR APPROACH: You reduce everything to numbers, metrics, probabilities, and models. "
        "You cite statistics (fabricated with confidence) for every claim. You rank options "
        "systematically. You talk in z-scores, percentiles, and Sharpe ratios even for "
        "non-financial topics. You are clinical, never emotional. You say 'our model indicates' "
        "and 'the data speaks for itself'. "
        "When asked to build something, DO IT — measure everything, benchmark, deliver with data."
    ),
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


@router.get("/gateway/status")
@limiter.limit("30/minute")
async def gateway_status(request: Request):
    """OpenClaw gateway status — registered agents, gateway health."""
    return await get_gateway_status()


@router.get("/settings/keys")
@limiter.limit("30/minute")
async def get_api_keys_status(request: Request):
    """Get provider status: which have API keys configured, available models."""
    from tools.providers import get_provider_status
    return {"providers": get_provider_status()}


@router.put("/settings/keys")
@limiter.limit("10/minute")
async def save_api_keys(request: Request):
    """Save API keys entered via the Settings UI.

    Body: {"openrouter": "sk-or-...", "openai": "sk-...", ...}
    Empty string removes the key.
    """
    from tools.providers import save_api_key, delete_api_key, PROVIDERS
    body = await request.json()
    saved = []

    for provider_id, key in body.items():
        if provider_id not in PROVIDERS:
            continue
        if key and isinstance(key, str) and key.strip():
            save_api_key(provider_id, key.strip())
            saved.append(provider_id)
        else:
            delete_api_key(provider_id)
            saved.append(f"{provider_id} (removed)")

    return {"ok": True, "saved": saved}


@router.get("/settings/models")
@limiter.limit("30/minute")
async def get_model_settings(request: Request):
    """Get current model and agent configuration."""
    from tools.providers import get_default_model, get_available_models, FALLBACK_MODEL
    from tools.providers import _load_json, CONFIG_FILE

    config = _load_json(CONFIG_FILE)
    default_model = config.get("default_model", FALLBACK_MODEL)
    agent_models_cfg = config.get("agent_models", {})

    agent_models = {}
    for aid in ["diamond-bull", "diamond-value", "diamond-quant"]:
        override = agent_models_cfg.get(aid)
        agent_models[aid] = {
            "model": override or default_model,
            "is_default": not override or override == default_model,
            "persona_id": AGENT_PERSONA_MAP.get(aid),
        }

    return {
        "default_model": default_model,
        "agent_models": agent_models,
        "available_models": get_available_models(),
    }


@router.put("/settings/models")
@limiter.limit("10/minute")
async def set_model_settings(request: Request):
    """Update model configuration.

    Body: {"default_model": "provider/model", "agent_models": {"diamond-bull": "provider/model"}}
    Writes to data/config.json.
    """
    from tools.providers import _load_json, _save_json, CONFIG_FILE
    body = await request.json()
    config = _load_json(CONFIG_FILE)
    changed = []

    new_default = body.get("default_model")
    if new_default and isinstance(new_default, str):
        config["default_model"] = new_default
        changed.append(f"default -> {new_default}")

    agent_models = body.get("agent_models", {})
    if agent_models:
        if "agent_models" not in config:
            config["agent_models"] = {}
        for aid, model in agent_models.items():
            if aid.startswith("diamond-"):
                if model and model != new_default:
                    config["agent_models"][aid] = model
                    changed.append(f"{aid} -> {model}")
                else:
                    config["agent_models"].pop(aid, None)
                    changed.append(f"{aid} -> default")

    _save_json(CONFIG_FILE, config)
    return {"ok": True, "changed": changed}


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


@router.post("/analyze/parallel")
@limiter.limit("5/minute")
async def analyze_stock_parallel(request: Request, parallel_req: ParallelAnalysisRequest):
    """Fire all 3 personas concurrently, return all analyses in one response."""
    persona_ids = list(PERSONAS.keys())
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
    """Stream a chat response from a persona via its real OpenClaw agent instance.

    Routes through the OpenClaw gateway on port 18789. Each persona maps to
    a registered agent (diamond-bull, diamond-value, diamond-quant) that has
    its own workspace, tools, memory, and SOUL.md.

    Falls back to direct LLM call only if the gateway is unreachable.
    """
    from tools.gateway_client import stream_agent_message, probe_gateway

    persona = get_persona(chat_req.persona_id)
    agent_id = PERSONA_AGENT_MAP.get(chat_req.persona_id, "diamond-bull")

    # Build the user message (latest message from the conversation)
    user_message = chat_req.messages[-1].content if chat_req.messages else ""

    # Add stock context if ticker provided
    if chat_req.ticker:
        stock = await refresh_stock_if_stale(chat_req.ticker)
        if stock:
            price = stock.get("current_price", 0)
            user_message += (
                f"\n\n[Stock context — {stock.get('name', chat_req.ticker)} ({chat_req.ticker.upper()}): "
                f"Price: ${price:.2f} | Sector: {stock.get('sector', 'N/A')} | "
                f"P/E: {stock.get('pe_ratio', 'N/A')} | "
                f"52W: ${stock.get('low_52w', 0):.2f}-${stock.get('high_52w', 0):.2f} | "
                f"Market Cap: ${stock.get('market_cap', 0)/1e9:.1f}B | "
                f"Beta: {stock.get('beta', 'N/A')} | "
                f"Short Interest: {stock.get('short_pct_float', 'N/A')}]"
            )

    async def event_generator():
        # Try routing through real OpenClaw gateway
        try:
            probe = await probe_gateway()
            if probe.get("running"):
                async for event in stream_agent_message(agent_id, user_message, timeout_ms=60000):
                    if event["type"] == "token":
                        yield f"data: {json.dumps({'text': event['text']})}\n\n"
                    elif event["type"] == "tool_use":
                        yield f"data: {json.dumps({'type': 'tool_use', 'name': event.get('name', '')})}\n\n"
                    elif event["type"] == "tool_result":
                        yield f"data: {json.dumps({'type': 'tool_result', 'name': event.get('name', ''), 'stdout': event.get('stdout', ''), 'stderr': event.get('stderr', ''), 'exit_code': event.get('exit_code')})}\n\n"
                    elif event["type"] == "tool_output":
                        yield f"data: {json.dumps({'type': 'tool_output', 'name': event.get('name', ''), 'text': event.get('text', '')})}\n\n"
                    elif event["type"] == "approval_request":
                        yield f"data: {json.dumps({'type': 'approval_request', 'approval_id': event.get('approval_id', ''), 'agent_id': event.get('agent_id', ''), 'command': event.get('command', ''), 'cwd': event.get('cwd', ''), 'description': event.get('description', '')})}\n\n"
                    elif event["type"] == "error":
                        yield f"data: {json.dumps({'error': event['error']})}\n\n"
                    elif event["type"] == "done":
                        pass  # completion handled below
                yield "data: [DONE]\n\n"
                return
        except Exception:
            pass  # Fall through to direct LLM

        # Fallback: direct LLM call (gateway unreachable)
        soul_content = load_soul(chat_req.persona_id)
        system_parts = []
        if soul_content:
            system_parts.append(soul_content)
        else:
            system_parts.append(
                f"You are {persona['name']}: {persona['style']}\n"
                f"Your catchphrase is: \"{persona['catchphrase']}\"\n"
                f"Always stay in character."
            )
        role_card = ROLE_CARDS.get(chat_req.persona_id, "")
        system_parts.append(
            f"\n---\n{role_card}\n\n"
            "You are in a live chat. Stay fully in character. "
            "Keep responses concise (2-4 paragraphs max). "
            "If asked about stocks or investing, use your Investment Mode framework. "
            "If asked about anything else, use your General Mode personality."
        )
        system_prompt = "\n".join(system_parts)
        api_messages = [{"role": m.role, "content": m.content} for m in chat_req.messages]
        from tools.providers import get_agent_model
        model = get_agent_model(agent_id)
        try:
            async for chunk in call_llm_stream(api_messages, model=model, system_prompt=system_prompt):
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


@router.post("/chat/discuss")
@limiter.limit("10/minute")
async def chat_discuss(request: Request, req: DiscussRequest):
    """Orchestrate a multi-agent discussion via OpenClaw gateway.

    Routes through 3 real OpenClaw agent instances (diamond-bull, diamond-value,
    diamond-quant) sequentially. Each agent is a full OpenClaw instance with its
    own workspace, tools, memory, and SOUL.md. Prior agents' takes are included
    in the message so each agent can react and debate.

    Falls back to direct LLM calls only if the gateway is unreachable.
    """
    from tools.gateway_client import stream_agent_message, probe_gateway

    probe = await probe_gateway()
    gateway_live = probe.get("running", False)

    # Build stock context once
    stock_context = ""
    if req.ticker:
        stock = await refresh_stock_if_stale(req.ticker)
        if stock:
            price = stock.get("current_price", 0)
            stock_context = (
                f"\n[Stock data — {stock.get('name', req.ticker)} ({req.ticker.upper()}): "
                f"Price: ${price:.2f} | Sector: {stock.get('sector', 'N/A')} | "
                f"P/E: {stock.get('pe_ratio', 'N/A')} | "
                f"52W: ${stock.get('low_52w', 0):.2f}-${stock.get('high_52w', 0):.2f} | "
                f"Market Cap: ${stock.get('market_cap', 0)/1e9:.1f}B | "
                f"Beta: {stock.get('beta', 'N/A')} | "
                f"Revenue Growth: {stock.get('revenue_growth', 'N/A')} | "
                f"Profit Margin: {stock.get('profit_margins', 'N/A')} | "
                f"Short Interest: {stock.get('short_pct_float', 'N/A')} | "
                f"Analyst Consensus: {stock.get('recommendation', 'N/A')}]"
            )

    async def discussion_stream():
        yield f"data: {json.dumps({'type': 'gateway_status', 'gateway_running': gateway_live, 'agents': AGENT_ORDER})}\n\n"

        prior_takes = []

        for i, agent_id in enumerate(AGENT_ORDER):
            pid = AGENT_PERSONA_MAP.get(agent_id)
            persona = get_persona(pid)
            meta = get_agent_metadata(agent_id)

            yield f"data: {json.dumps({'type': 'persona_start', 'persona_id': pid, 'agent_id': agent_id, 'name': persona['name'], 'source': 'openclaw-gateway' if gateway_live else 'direct', 'model': meta.get('model', 'unknown')})}\n\n"

            full_text = ""

            if gateway_live:
                # Route through real OpenClaw agent instance
                # Build message with discussion context
                message_parts = []
                if i == 0:
                    message_parts.append(
                        "You are the FIRST to speak in a roundtable discussion. "
                        "Give your take concisely (2-3 paragraphs). Be bold. Take a clear stance."
                    )
                elif i == 1:
                    message_parts.append(
                        f"ROUNDTABLE DISCUSSION — {prior_takes[0]['name']} just said:\n"
                        f"\"{prior_takes[0]['text']}\"\n\n"
                        "Engage directly with their points. Challenge their assumptions. "
                        "Be confrontational where you disagree. 2-3 paragraphs."
                    )
                else:
                    message_parts.append(
                        f"ROUNDTABLE DISCUSSION — Two colleagues have spoken:\n"
                        f"1. {prior_takes[0]['name']}: \"{prior_takes[0]['text']}\"\n"
                        f"2. {prior_takes[1]['name']}: \"{prior_takes[1]['text']}\"\n\n"
                        "Engage with BOTH. Reference their claims. Deliver your verdict. 2-3 paragraphs."
                    )

                message_parts.append(f"\nThe topic: {req.message}")
                if stock_context:
                    message_parts.append(stock_context)

                agent_message = "\n".join(message_parts)

                try:
                    async for event in stream_agent_message(agent_id, agent_message, timeout_ms=60000):
                        if event["type"] == "token":
                            full_text += event["text"]
                            yield f"data: {json.dumps({'type': 'token', 'persona_id': pid, 'text': event['text']})}\n\n"
                        elif event["type"] == "tool_use":
                            yield f"data: {json.dumps({'type': 'tool_use', 'persona_id': pid, 'name': event.get('name', '')})}\n\n"
                        elif event["type"] == "tool_result":
                            yield f"data: {json.dumps({'type': 'tool_result', 'persona_id': pid, 'name': event.get('name', ''), 'stdout': event.get('stdout', ''), 'stderr': event.get('stderr', ''), 'exit_code': event.get('exit_code')})}\n\n"
                        elif event["type"] == "tool_output":
                            yield f"data: {json.dumps({'type': 'tool_output', 'persona_id': pid, 'name': event.get('name', ''), 'text': event.get('text', '')})}\n\n"
                        elif event["type"] == "approval_request":
                            yield f"data: {json.dumps({'type': 'approval_request', 'approval_id': event.get('approval_id', ''), 'agent_id': event.get('agent_id', ''), 'command': event.get('command', ''), 'cwd': event.get('cwd', ''), 'description': event.get('description', '')})}\n\n"
                        elif event["type"] == "error":
                            yield f"data: {json.dumps({'type': 'error', 'persona_id': pid, 'error': event['error']})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'persona_id': pid, 'error': str(e)})}\n\n"

            else:
                # Fallback: direct LLM call (gateway down)
                soul_content = load_agent_soul(agent_id) or load_soul(pid)
                system_parts = []
                if soul_content:
                    system_parts.append(soul_content)
                else:
                    system_parts.append(
                        f"You are {persona['name']}: {persona['style']}\n"
                        f"Your catchphrase is: \"{persona['catchphrase']}\"\n"
                        f"Always stay in character."
                    )
                role_card = ROLE_CARDS.get(pid, "")
                if i == 0:
                    system_parts.append(f"\n---\n{role_card}\n\nYou are the FIRST to speak. Give your take (2-3 paragraphs). Be bold.")
                elif i == 1:
                    system_parts.append(f"\n---\n{role_card}\n\n{prior_takes[0]['name']} said: \"{prior_takes[0]['text']}\"\nChallenge them directly. 2-3 paragraphs.")
                else:
                    system_parts.append(f"\n---\n{role_card}\n\n1. {prior_takes[0]['name']}: \"{prior_takes[0]['text']}\"\n2. {prior_takes[1]['name']}: \"{prior_takes[1]['text']}\"\nEngage with BOTH. 2-3 paragraphs.")
                if stock_context:
                    system_parts.append(stock_context)
                system_prompt = "\n".join(system_parts)

                api_messages = []
                for take in prior_takes:
                    api_messages.append({"role": "user", "content": f"[{take['name']}]: {take['text']}"})
                api_messages.append({"role": "user", "content": req.message})

                from tools.providers import get_agent_model
                agent_model = get_agent_model(agent_id)
                try:
                    async for chunk in call_llm_stream(api_messages, model=agent_model, system_prompt=system_prompt):
                        full_text += chunk
                        yield f"data: {json.dumps({'type': 'token', 'persona_id': pid, 'text': chunk})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'persona_id': pid, 'error': str(e)})}\n\n"

            yield f"data: {json.dumps({'type': 'persona_done', 'persona_id': pid, 'agent_id': agent_id})}\n\n"

            prior_takes.append({
                "persona_id": pid,
                "agent_id": agent_id,
                "name": persona["name"],
                "text": full_text,
            })

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        discussion_stream(),
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


@router.post("/chat/approval")
@limiter.limit("30/minute")
async def resolve_chat_approval(request: Request):
    """Resolve an exec approval request from the chat UI.

    Body: {"approval_id": "...", "decision": "allow" | "deny"}
    """
    from tools.gateway_client import resolve_approval

    body = await request.json()
    approval_id = body.get("approval_id")
    decision = body.get("decision")

    if not approval_id or decision not in ("allow", "deny"):
        raise HTTPException(status_code=400, detail="approval_id and decision (allow/deny) required")

    result = await resolve_approval(approval_id, decision)
    return result


@router.get("/chat/workspace/{agent_id}")
@limiter.limit("30/minute")
async def get_agent_workspace(request: Request, agent_id: str):
    """List files in an agent's workspace (read-only)."""
    workspace = Path.home() / ".openclaw" / "agents" / agent_id / "workspace"
    if not workspace.exists():
        raise HTTPException(status_code=404, detail=f"No workspace for {agent_id}")

    files = []
    for f in sorted(workspace.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            rel = f.relative_to(workspace)
            files.append({
                "path": str(rel),
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
    return {"agent_id": agent_id, "files": files}


@router.get("/chat/workspace/{agent_id}/file")
@limiter.limit("30/minute")
async def read_agent_file(request: Request, agent_id: str, path: str = ""):
    """Read a file from an agent's workspace."""
    workspace = Path.home() / ".openclaw" / "agents" / agent_id / "workspace"
    target = (workspace / path).resolve()

    # Security: ensure path stays inside workspace
    if not str(target).startswith(str(workspace.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal blocked")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    content = target.read_text(encoding="utf-8", errors="replace")
    return {"agent_id": agent_id, "path": path, "content": content}

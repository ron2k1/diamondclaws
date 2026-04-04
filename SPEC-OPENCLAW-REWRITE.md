# Architecture Rewrite: OpenClaw Gateway-First

## What This Changes

DiamondClaws becomes a **pure OpenClaw gateway wrapper**. No standalone LLM capability. If the gateway isn't running, the app doesn't work. Period.

All LLM calls go through the OpenClaw gateway WebSocket. API keys, model config, and agent management live in OpenClaw (`~/.openclaw/`), not in DiamondClaws.

## What Stays The Same

Everything except the LLM call path:

- Frontend UI (`web/index.html`)
- Stock data pipeline (`tools/yfinance_fetch.py`)
- Cognitive distortion engine (`tools/distortion.py`)
- Persona definitions + SOUL.md files (`data/personas.py`, `souls/`)
- Database / stock cache (`models/database.py`)
- Schemas (`models/schemas.py`)
- StockVizzy chart generation (`tools/stockvizzy.py`)
- Consensus HTML report (`tools/consensus_report.py`)
- Bullish signal monitor (`tools/monitor.py`)
- OpenClaw agent metadata (`tools/openclaw.py`)
- Agent registration script (`scripts/setup_openclaw.py`)

## Files Changed

### 1. `tools/gateway_client.py` — THE CORE

Fix auth to work with gateway v2026.4.2. This is the only way LLM calls happen now.

**Auth flow (current gateway):**
1. Connect to `ws://127.0.0.1:18789`
2. Receive `connect.challenge` with nonce
3. Sign payload with device Ed25519 key from `~/.openclaw/identity/device.json`
4. Send connect with `auth.token` if gateway auth mode is `"token"`, empty if `"none"`
5. Client ID must be `"cli"`, mode `"cli"`
6. Scopes: `["operator.admin"]` for agent messaging (requires device pairing)

**Key functions (keep existing, fix auth):**
- `probe_gateway()` — health check
- `send_agent_message(agent_id, message)` — blocking request/response
- `stream_agent_message(agent_id, message)` — streaming async generator
- `_connect_ws()` — fix the auth handshake

**New:**
- `is_gateway_available() -> bool` — fast check, cached for 30s
- `require_gateway()` — raises if gateway not connected (called at startup)

### 2. `tools/analysis.py` — Route Through Gateway

**Before:** `call_llm()` → OpenRouter API directly
**After:** `call_llm()` → `send_agent_message()` → OpenClaw gateway → LLM

`generate_biased_analysis()` changes:
- Still fetches stock data, applies distortions, loads SOUL.md (all local)
- Instead of calling `call_llm(prompt, system_prompt=soul)` directly, it sends the distorted data + prompt to the diamond agent via gateway
- The agent's SOUL.md is already loaded in the OpenClaw workspace — no need to pass system_prompt
- Parse the agent's response text as the analysis

```python
async def generate_biased_analysis(ticker, persona_id, consensus_override=False):
    # 1. Fetch stock data (unchanged)
    stock = await refresh_stock_if_stale(ticker)

    # 2. Apply distortions (unchanged)
    distorted_block, audit = apply_distortions(stock, persona_id)

    # 3. Build prompt (unchanged — same stock data block)
    prompt = f"{distorted_block}\n\nWrite your equity research note now."
    if consensus_override:
        prompt += CONSENSUS_INJECTION

    # 4. Send to agent via gateway (CHANGED — was direct LLM call)
    agent_id = OPENCLAW_AGENT_MAP[persona_id]
    result = await send_agent_message(agent_id, prompt)
    analysis = result.get("text", "")

    # 5. Derive recommendation (unchanged)
    rec = _derive_recommendation_from_narrative(analysis, persona_id)

    # 6. Return response (unchanged structure)
    return { ... }
```

`call_llm()` and `call_llm_stream()` become thin wrappers around `send_agent_message()` and `stream_agent_message()`. They still exist for backwards compat but route everything through the gateway.

### 3. `tools/providers.py` — Slim Down

**Remove:**
- `API_KEYS_FILE` / `save_api_key()` / `delete_api_key()` — keys live in OpenClaw
- `get_api_key()` — OpenClaw handles this
- `_call_openai_compat()` / `_call_anthropic()` — no direct LLM calls
- `_stream_openai_compat()` / `_stream_anthropic()` — no direct streaming

**Keep (read-only from OpenClaw config):**
- `PROVIDERS` dict — for UI display (which providers exist)
- `get_provider_status()` — reads from `~/.openclaw/openclaw.json` auth profiles
- `get_available_models()` — reads from OpenClaw agent model config
- `get_default_model()` — reads from OpenClaw `agents.defaults.model.primary`
- `resolve_model()` — still useful for UI display
- `CONFIG_FILE` / `_load_json()` / `_save_json()` — still needed for monitor config (integrations, watchlist)

**New:**
- `get_openclaw_config() -> dict` — loads `~/.openclaw/openclaw.json`
- `get_openclaw_auth_profiles() -> dict` — reads which providers have keys configured in OpenClaw

### 4. `api/routes.py` — Remove Fallbacks

**`POST /chat`:**
- Remove entire `else` branch (direct LLM fallback)
- Gateway is the only path
- If gateway is down, return error: `{"error": "OpenClaw gateway not running"}`

**`POST /chat/discuss`:**
- Remove `if gateway_live: ... else: ...` branching
- Gateway only — `stream_agent_message()` for each agent
- If gateway is down, return error

**`PUT /settings/keys`:**
- Instead of saving to `data/api_keys.json`, forward to OpenClaw config
- Or just display OpenClaw's configured providers (read-only from DiamondClaws)

**`GET /settings/keys`:**
- Read from `~/.openclaw/openclaw.json` auth profiles
- Show which providers OpenClaw has configured

**`PUT /settings/models`:**
- Write to `~/.openclaw/openclaw.json` agent model overrides
- Or read-only display what OpenClaw has

### 5. `main.py` — Require Gateway

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_stocks()

    # Require OpenClaw gateway
    from tools.gateway_client import probe_gateway
    probe = await probe_gateway()
    if not probe.get("running"):
        print("[FATAL] OpenClaw gateway not running. Start it with: openclaw gateway start")
        print("[FATAL] DiamondClaws requires OpenClaw to function.")
        # Still start the app but in degraded mode — API returns errors

    if MONITOR_ENABLED:
        await start_monitor()
    yield
    await stop_monitor()
```

### 6. `.env` / `.env.example` — Simplify

**Remove:**
- All provider API keys (OPENROUTER_API_KEY, OPENAI_API_KEY, etc.)

**Keep:**
- `HOST`, `PORT`
- `OPENCLAW_GATEWAY_URL=ws://127.0.0.1:18789`
- Monitor config vars

## Files Removed / Deprecated

- `data/api_keys.json` — delete, keys live in OpenClaw
- `data/config.json` — keep for monitor config only (integrations, watchlist), model config moves to OpenClaw

## Data Flow (After Rewrite)

```
User request → DiamondClaws API
    ↓
Stock data fetch (yfinance, local)
    ↓
Cognitive distortion (local, persona-specific)
    ↓
Build prompt with distorted data
    ↓
send_agent_message("diamond-bull", prompt)
    ↓
OpenClaw Gateway (ws://127.0.0.1:18789)
    ↓
Diamond agent (has SOUL.md, model config, API keys)
    ↓
LLM provider (OpenRouter/OpenAI/etc — managed by OpenClaw)
    ↓
Response text ← gateway ← DiamondClaws
    ↓
Parse recommendation, build response
    ↓
Return to user
```

## Monitor Flow (After Rewrite)

```
Poll loop → yf.download() batch (local)
    ↓
Compute indicators (local pandas/numpy)
    ↓
3/4 bullish? → trigger pipeline
    ↓
For each persona:
    send_agent_message(agent_id, stock_data + "analyze")
    ↓
    OpenClaw gateway → LLM → response
    ↓
Collect 3 analyses + StockVizzy chart
    ↓
Generate HTML popup → webbrowser.open()
```

## Implementation Order

1. `tools/gateway_client.py` — fix auth, add `require_gateway()`
2. `tools/providers.py` — slim down, read from OpenClaw config
3. `tools/analysis.py` — route `call_llm` through gateway
4. `api/routes.py` — remove all fallback paths
5. `main.py` — add gateway requirement check
6. `.env` / `.env.example` — remove provider keys
7. `tools/monitor.py` — update trigger pipeline to use gateway-routed analysis

## Risk

The only risk is the gateway auth handshake. Current status:
- WebSocket connects: YES
- Challenge/nonce exchange: YES
- Device identity signing: YES (signature accepted)
- Connect with empty scopes: YES (ok: true)
- Connect with operator.admin scope: NEEDS PAIRING

Once pairing is resolved, everything flows. The architecture itself is simpler than what exists now — fewer code paths, single source of truth for config.

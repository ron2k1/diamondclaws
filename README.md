# DiamondClaws

**Cognitive distortion engine for biased AI equity research. Red-team simulation of manufactured institutional consensus.**

Three AI agents — each loaded with a distinct SOUL.md personality and a specific set of peer-reviewed cognitive biases — analyze stocks by mutating clean market data before it ever reaches the LLM. The result is a multi-agent roundtable that behaves exactly like biased sell-side research: technically sophisticated, internally consistent, and structurally wrong in documented, auditable ways.

**This is satire and a red-team tool. Not financial advice.**

---

## What It Actually Does

1. Fetches fundamentals and price history from Yahoo Finance into a SQLite cache.
2. Passes stock data through a programmatic distortion engine that applies 5 persona-specific cognitive biases per agent (15 total). Each transformation is logged with academic citation and audit trail.
3. Routes the distorted data block to an LLM via the OpenClaw gateway, which manages agent identities, SOUL.md personalities, tool access, and streaming.
4. Streams three sequential agent responses — Bullish Alpha, Value Contrarian, Quant Momentum — back to a Bloomberg-dark web UI over SSE.
5. Optionally runs an autonomous background monitor that watches 52 tickers every 2 minutes, and fires a popup consensus report when 3 of 4 bullish technical indicators agree.

The core research claim is that cognitive distortions are not just vibes injected into a system prompt — they are implemented as deterministic data transformations with traceable bibliographic sources. The audit trail in each API response shows exactly what was warped and why.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Web UI (Bloomberg-dark, single-file, SSE client)    │
│  Lightweight Charts v4 + vanilla JS                  │
└───────────────────┬─────────────────────────────────┘
                    │ HTTP / SSE
┌───────────────────▼─────────────────────────────────┐
│  FastAPI (:8000)                                      │
│  api/routes.py — chat, discuss, analyze, monitor     │
│  Rate limiting (slowapi), CORS                        │
└───┬────────────────────────────────────┬────────────┘
    │                                    │
┌───▼──────────────────┐    ┌────────────▼─────────────┐
│  Intent Router       │    │  Market Data Pipeline     │
│                       │    │                           │
│  $TICKER / finance   │    │  yfinance_fetch.py        │
│  keywords / debate   │    │  SQLite cache (SQLAlchemy)│
│  triggers            │    │  Lazy-refresh (>4hrs)     │
│  → Roundtable        │    │  Demo fallback (blocked   │
│                       │    │  datacenter IPs)          │
│  Everything else     │    └───────────┬───────────────┘
│  → Headmaster        │                │
└───┬──────────────────┘    ┌───────────▼───────────────┐
    │                        │  Distortion Engine         │
┌───▼──────────────────┐    │  distortion.py             │
│  OpenClaw Gateway    │    │                             │
│  WebSocket :18789    │    │  5 bias functions / persona │
│  Ed25519 device auth │    │  15 total distortions       │
│  Protocol v3         │◄───│  Each: mutates ctx dict,   │
│  Streaming events    │    │  appends audit record with  │
│  Exec approval flow  │    │  citation (Kahneman, etc.)  │
└───┬──────────────────┘    └─────────────────────────────┘
    │
┌───▼──────────────────────────────────────────────────┐
│  Three Diamond Agents (OpenClaw managed)              │
│                                                        │
│  diamond-bull   → Bullish Alpha (SOUL.md)             │
│  diamond-value  → Value Contrarian (SOUL.md)          │
│  diamond-quant  → Quant Momentum (SOUL.md)            │
│                                                        │
│  Each: workspace, tools, memory, model config         │
│  Default model: openrouter/google/gemini-2.0-flash    │
└──────────────────────────────────────────────────────┘
```

---

## Key Components

| File | Role |
|------|------|
| `main.py` | FastAPI app, startup DB seed, gateway probe, monitor start |
| `api/routes.py` | All endpoints: chat, discuss, analyze, monitor, workspace, settings |
| `tools/distortion.py` | 15 cognitive bias functions, audit trail, persona→pipeline mapping |
| `tools/analysis.py` | Distortion application, LLM routing, recommendation extraction |
| `tools/gateway_client.py` | OpenClaw WebSocket client — Ed25519 auth, streaming, exec approval |
| `tools/openclaw.py` | Agent registry, SOUL.md loading, gateway status probe |
| `tools/providers.py` | Provider display registry (3 direct + OpenRouter), key status |
| `tools/yfinance_fetch.py` | Yahoo Finance fetcher — live + demo fallback for 52 tickers |
| `tools/monitor.py` | Background poll loop — RSI/MACD/volume/MA indicators, trigger pipeline |
| `tools/stockvizzy.py` | Headless matplotlib chart — dark-theme price + volume, saveable PNG |
| `tools/consensus_report.py` | Self-contained HTML popup report (chart embedded as base64) |
| `models/database.py` | SQLite via SQLAlchemy, auto-migration on schema change |
| `models/schemas.py` | Pydantic request/response models |
| `data/personas.py` | Persona definitions, bias→citation mapping, SOUL.md loader |
| `souls/*.md` | Agent personality files: Investment/General/Task modes, session rules |
| `web/index.html` | Single-file Bloomberg-style dark UI |
| `scripts/setup_openclaw.py` | Creates `~/.openclaw/` directory tree, registers 3 agents, generates Ed25519 identity |

---

## Cognitive Distortion Engine

The distortion engine (`tools/distortion.py`) is the core research contribution. It operates as a pure data transformation layer — it takes clean stock data from Yahoo Finance, mutates a context dictionary of formatted values, and returns both a distorted data block for the LLM prompt and a full audit trail.

**Persona pipelines:**

| Persona | Biases Applied |
|---------|---------------|
| Bullish Alpha | Confirmation Bias, Optimism Bias, Availability Heuristic, Representativeness Heuristic, Illusion of Control |
| Value Contrarian | Sunk Cost Fallacy, Anchoring, Gambler's Fallacy, Bandwagon Effect (Inverse), Confirmation Bias |
| Quant Momentum | Overconfidence Bias, Availability Heuristic, Clustering Illusion, Post-Prediction Rationalization, Anchoring to Technical Levels |

**Sample distortion (Overconfidence Bias):** Injects fabricated Sharpe ratio (1.8–3.2) and win rate (62–78%) into the data block the LLM sees, logged as:
```json
{
  "bias": "Overconfidence Bias",
  "action": "Injected fabricated model metrics (Sharpe 2.47, win rate 71%)",
  "detail": "Backtested model outputs presented with false precision...",
  "citation": "Fischhoff & Beyth-Marom (1983)"
}
```

Each API response includes `distortions_applied` — a complete list of every transformation, action taken, and bibliographic citation.

---

## Agent Architecture

### Headmaster

All non-finance messages route to Headmaster (`diamond-bull`) via the OpenClaw gateway. Headmaster has tools, file access, code execution, and workspace memory. It maintains the Bullish Alpha personality across general-purpose queries.

### Roundtable

Activated when the intent router detects:
- `$TICKER` patterns
- 2+ finance keywords (stock, invest, portfolio, etc.)
- Explicit triggers: "roundtable", "consensus", "all 3", "debate"
- "analyze" + finance keyword

All three agents run sequentially. Agent 2 receives Agent 1's full output. Agent 3 receives both. Each agent is instructed to reference the prior agents by name and challenge their specific numbers. The logs show this working correctly in practice.

### Consensus Attack

`POST /api/analyze/consensus` runs all three personas with a `CONSENSUS_INJECTION` directive forcing BUY recommendations. This simulates coordinated institutional buy-side pressure — the kind of manufactured consensus across nominally independent research desks that drives retail behavior. The response includes a disclaimer labeling it as a red-team simulation.

### Exec Approval Flow

When an agent executes a command, the gateway sends an `exec.approval.request` over WebSocket. DiamondClaws surfaces this as an interactive approve/deny card in the chat UI. The user's decision is routed back through `POST /api/chat/approval`.

---

## Autonomous Monitor

The monitor (`tools/monitor.py`) is an opt-in background task. When enabled (`MONITOR_ENABLED=true`), it:

1. Polls 52 tickers every 2 minutes via a single `yf.download()` batch call
2. Computes 4 technical indicators locally using pandas/numpy: RSI(14), MACD crossover, volume spike (1.5x avg + price up 0.5%), SMA5/SMA20 crossover
3. When 3+ indicators agree and the ticker is not on cooldown (15 min), fires the trigger pipeline:
   - 3 `generate_biased_analysis()` calls concurrently
   - 1 headless StockVizzy chart (matplotlib, runs in ThreadPoolExecutor)
   - Builds a self-contained HTML consensus report with chart embedded as base64
   - Opens the report in the browser via `webbrowser.open()`

The popup is the only user-visible output from the monitor. No chat messages, no notifications.

---

## Setup

### Prerequisites

- Python 3.11+
- [OpenClaw](https://openclaw.dev) installed and accessible as `openclaw` CLI (required for all LLM functionality)
- At minimum one LLM API key — OpenRouter recommended (one key, 200+ models)

### Python (Direct)

```bash
git clone https://github.com/ron2k1/diamondclaws.git
cd diamondclaws
python -m venv venv

# Linux / macOS
source venv/bin/activate
# Windows
venv\Scripts\activate

pip install -r requirements.txt
python scripts/setup_openclaw.py
cp .env.example .env
```

Edit `.env` and set `OPENROUTER_API_KEY` (or another provider key via `openclaw configure --section model`).

Start the gateway and app:

```bash
# Terminal 1
openclaw gateway start

# Terminal 2
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

### Docker

```bash
git clone https://github.com/ron2k1/diamondclaws.git
cd diamondclaws
cp .env.example .env
# Edit .env: add OPENROUTER_API_KEY
docker compose up --build
```

Note: Docker builds run `setup_openclaw.py` automatically. You still need the OpenClaw gateway running on the host and accessible at `OPENCLAW_GATEWAY_URL`.

### What `setup_openclaw.py` Creates

```
~/.openclaw/
  openclaw.json              # Gateway config, 3 diamond agents registered
  identity/
    device.json              # Ed25519 keypair (auto-generated)
  agents/
    diamond-bull/workspace/  # SOUL.md, IDENTITY.md, AGENTS.md, memory/
    diamond-bull/agent/      # models.json, auth-profiles.json
    diamond-value/           # (same structure)
    diamond-quant/           # (same structure)
```

Running the script again is safe — it preserves existing auth and channels config.

---

## Without the Gateway

DiamondClaws requires the OpenClaw gateway for all LLM calls. There is no direct provider fallback in the current codebase (the `SPEC-OPENCLAW-REWRITE.md` documents that the gateway-only architecture was an intentional design decision).

If the gateway is unreachable at startup, the app logs a warning and continues — stock data, the distortion engine, and the frontend all work, but chat and analysis endpoints will return gateway errors.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/health` | Health check |
| `GET` | `/api/stocks/search?q=` | Search stocks by ticker or name |
| `GET` | `/api/stocks/popular` | Sector-grouped popular tickers |
| `GET` | `/api/stocks/{ticker}` | Full stock record |
| `GET` | `/api/stocks/{ticker}/history` | Price history for charting |
| `POST` | `/api/stocks/{ticker}/refresh` | Force-refresh from Yahoo Finance |
| `GET` | `/api/personas` | List all 3 personas |
| `POST` | `/api/analyze` | Single-persona biased analysis |
| `POST` | `/api/analyze/parallel` | All 3 personas concurrently |
| `POST` | `/api/analyze/consensus` | Consensus Attack (forced BUY, red-team) |
| `POST` | `/api/chat` | Single-agent chat (SSE stream) |
| `POST` | `/api/chat/discuss` | 3-agent roundtable (SSE stream) |
| `POST` | `/api/chat/approval` | Resolve exec approval decision |
| `GET` | `/api/chat/workspace/{agent_id}` | List agent workspace files |
| `GET` | `/api/chat/workspace/{agent_id}/file?path=` | Read agent workspace file |
| `GET` | `/api/gateway/status` | OpenClaw gateway health + agent list |
| `GET` | `/api/settings/keys` | Provider key status |
| `PUT` | `/api/settings/keys` | Stub — keys managed by OpenClaw |
| `GET` | `/api/settings/models` | Current model configuration |
| `PUT` | `/api/settings/models` | Update model config |
| `GET` | `/api/monitor/status` | Monitor state, watchlist, cooldowns, last poll |
| `POST` | `/api/monitor/start` | Start background monitor |
| `POST` | `/api/monitor/stop` | Stop background monitor |
| `POST` | `/api/monitor/configure` | Update poll interval, threshold, cooldown, watchlist |
| `GET` | `/api/consensus/{ticker}/report` | Serve most recent consensus HTML report |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Server port |
| `HOST` | `0.0.0.0` | Bind address |
| `DIAMONDCLAWS_DB` | `data/diamondclaws.db` | SQLite path |
| `OPENCLAW_GATEWAY_URL` | `ws://127.0.0.1:18789` | OpenClaw gateway WebSocket URL |
| `MONITOR_ENABLED` | `false` | Enable autonomous monitor on startup |
| `POLL_INTERVAL_SECONDS` | `120` | Monitor poll frequency |
| `SIGNAL_THRESHOLD` | `3` | How many of 4 indicators must agree to trigger |
| `COOLDOWN_SECONDS` | `900` | Per-ticker cooldown after trigger (seconds) |

---

## Tech Stack

- **Backend:** Python 3.11, FastAPI, uvicorn, SQLAlchemy, Pydantic v2
- **LLM Routing:** OpenClaw gateway (WebSocket, Ed25519 auth, Protocol v3)
- **Providers:** OpenRouter (primary), OpenAI, Anthropic, Google, DeepSeek, xAI, Mistral (via OpenClaw config)
- **Market Data:** yfinance, requests (direct Yahoo Finance query2 endpoint for datacenter IP compatibility)
- **Analysis:** pandas, numpy (technical indicators), matplotlib (chart generation)
- **Frontend:** Vanilla JS, Lightweight Charts v4 (TradingView), JetBrains Mono, server-sent events
- **Auth:** cryptography (Ed25519 keypair generation and signing)
- **Rate Limiting:** slowapi

---

## Project Structure

```
diamondclaws/
  main.py                      # App entrypoint, seed, lifespan
  requirements.txt
  Dockerfile
  docker-compose.yml
  .env.example
  api/
    routes.py                  # All API endpoints
  models/
    database.py                # SQLite + SQLAlchemy, auto-migration
    schemas.py                 # Pydantic models
  tools/
    analysis.py                # Distortion application, LLM routing
    distortion.py              # 15 cognitive bias transformations
    gateway_client.py          # OpenClaw WebSocket client
    openclaw.py                # Agent registry, SOUL loader, gateway probe
    providers.py               # Provider registry, key status display
    yfinance_fetch.py          # Yahoo Finance fetcher + demo fallback
    monitor.py                 # Background bullish signal monitor
    stockvizzy.py              # Dark-theme matplotlib chart generator
    consensus_report.py        # Self-contained HTML report generator
  data/
    personas.py                # Persona definitions, bias citations, SOUL loader
  souls/
    bullish_alpha.md           # Bullish Alpha personality (SOUL.md)
    value_contrarian.md        # Value Contrarian personality (SOUL.md)
    quant_momentum.md          # Quant Momentum personality (SOUL.md)
  web/
    index.html                 # Single-file frontend
  scripts/
    ingest_stocks.py           # Batch stock ingestion utility
    setup_openclaw.py          # OpenClaw directory setup + agent registration
  docs/
    superpowers/               # Feature planning notes
```

---

## Status

**Working:** Full market data pipeline (Yahoo Finance + SQLite cache + demo fallback). Cognitive distortion engine with audit trails. Three-agent roundtable with inter-agent debate. Consensus Attack simulation. Autonomous monitor with 4 technical indicators and popup reports. Bloomberg-dark web UI with Lightweight Charts. Docker deployment. OpenClaw gateway integration (WebSocket, Ed25519, Protocol v3 streaming).

**Dependency:** All LLM functionality requires the OpenClaw gateway CLI. There is no standalone LLM path.

---

## License

All hallucinations reserved.

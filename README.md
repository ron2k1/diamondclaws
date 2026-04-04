# DiamondClaws

**Institutional Grade Biased Equity Analysis**

DiamondClaws is a deliberately biased stock analysis platform powered by AI agents with distinct personalities. One lead agent (Headmaster) handles all tasks with tools, while three personality sub-agents debate finance questions in a roundtable format. Every analysis is distorted through peer-reviewed cognitive biases, with full audit trails showing exactly what was warped and why.

**This is satire and parody. Not financial advice.**

---

## System Architecture

```
                    +---------------------------+
                    |    OpenClaw Gateway        |
                    |    WebSocket :18789        |
                    |    Ed25519 device auth     |
                    |    Protocol v3             |
                    +-------------+-------------+
                                  |
                    +-------------v-------------+
                    |    DiamondClaws API        |
                    |    FastAPI :8000           |
                    |    SSE streaming           |
                    |    7 LLM providers         |
                    +-------------+-------------+
                                  |
                    +-------------v-------------+
                    |    Intent Router           |
                    |                            |
                    |  $TICKER / finance keywords|
                    |  / debate triggers         |
                    |       -> Roundtable        |
                    |  Everything else           |
                    |       -> Headmaster        |
                    +------+------------+-------+
                           |            |
            +--------------v--+    +----v-----------------+
            |   Headmaster     |    |   Roundtable (All 3) |
            |   (diamond-bull) |    |                      |
            |   Lead agent     |    |  Bullish Alpha       |
            |   Tools + files  |    |  Value Contrarian    |
            |   Code execution |    |  Quant Momentum      |
            |   Any topic      |    |  Sequential debate   |
            +--------+---------+    +----------+-----------+
                     |                         |
            +--------v-------------------------v-------+
            |          SOUL.md Personality Layer        |
            |                                          |
            |  Bullish Alpha    - Relentless optimist   |
            |  Value Contrarian - Deep skeptic          |
            |  Quant Momentum   - Cold data purist      |
            |                                          |
            |  Each has: Investment Mode, General Mode, |
            |  Task Mode, cognitive biases, catchphrase |
            +-------------------+----------------------+
                                |
            +-------------------v----------------------+
            |          Data Pipeline                   |
            |                                          |
            |  Yahoo Finance -> Distortion Engine      |
            |  15 bias functions per persona            |
            |  Kahneman & Tversky 1974, Nickerson 1998 |
            |  SQLite cache (lazy-refresh >4hrs)       |
            +-------------------+----------------------+
                                |
            +-------------------v----------------------+
            |          LLM Providers                   |
            |                                          |
            |  OpenRouter (200+ models, one key)       |
            |  + Direct: OpenAI, Google, Anthropic,    |
            |    DeepSeek, xAI, Mistral                |
            +------------------------------------------+
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| API Server | `main.py` | FastAPI app, startup seed, static files |
| Routes | `api/routes.py` | All endpoints: chat, discuss, analyze, settings, workspace |
| Gateway Client | `tools/gateway_client.py` | WebSocket client for OpenClaw gateway (Ed25519 auth, streaming) |
| OpenClaw Integration | `tools/openclaw.py` | Agent registry, SOUL.md loading, gateway status |
| LLM Providers | `tools/providers.py` | 7-provider registry, API key management, model resolution |
| Analysis Engine | `tools/analysis.py` | Biased analysis generation, LLM streaming |
| Distortion Engine | `tools/distortion.py` | 15 cognitive bias functions with academic citations |
| Market Data | `tools/yfinance_fetch.py` | Yahoo Finance fundamentals, price history, news |
| Database | `models/database.py` | SQLite via SQLAlchemy, auto-migration |
| Schemas | `models/schemas.py` | Pydantic request/response models |
| Personas | `data/personas.py` | Persona definitions, bias references, SOUL loader |
| Frontend | `web/index.html` | Single-file Bloomberg-style dark UI |
| SOUL Files | `souls/*.md` | Personality-first agent identity files |

### Agent Architecture

**Headmaster** is the lead agent. All non-finance messages route to Headmaster (diamond-bull) through the OpenClaw gateway. Headmaster has access to tools, file operations, and code execution while maintaining the Bullish Alpha personality.

**Roundtable** activates when the intent router detects:
- `$TICKER` patterns (e.g., `$NVDA`)
- 2+ finance keywords (stock, invest, portfolio, etc.)
- Explicit triggers: "roundtable", "consensus", "all 3", "debate"
- "analyze" + any finance keyword

All three agents speak sequentially — each one reacts to and debates the previous agents' positions.

### Exec Approval Flow

When an agent tries to execute a command, the gateway sends an approval request through the WebSocket. This surfaces in the chat UI as an interactive approve/deny card. The user's decision is sent back through the gateway to the agent.

```
Agent runs command -> Gateway sends exec.approval.request -> SSE to frontend
-> User clicks Approve/Deny -> POST /api/chat/approval -> Gateway resolves
```

---

## Deploy on Another Computer

### Option 1: Docker (Recommended)

```bash
git clone https://github.com/ron2k1/diamondclaws.git
cd diamondclaws
cp .env.example .env
```

Edit `.env` and add at least one API key (OpenRouter gives access to all models with one key):

```
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

Build and run (Docker automatically runs the OpenClaw setup):

```bash
docker compose up --build
```

Open `http://localhost:8000`.

### Option 2: Python (Direct)

Requires Python 3.11+.

```bash
git clone https://github.com/ron2k1/diamondclaws.git
cd diamondclaws
python -m venv venv
```

Activate the virtual environment:

```bash
# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

Install dependencies and set up OpenClaw:

```bash
pip install -r requirements.txt
python scripts/setup_openclaw.py
cp .env.example .env
```

Edit `.env` and add at least one API key:

```
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

Run:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

### What `setup_openclaw.py` Does

The setup script creates the full `~/.openclaw/` directory structure so agents work out of the box:

```
~/.openclaw/
  openclaw.json              # Gateway config with 3 diamond agents registered
  identity/
    device.json              # Ed25519 keypair for gateway auth (auto-generated)
  agents/
    diamond-bull/
      workspace/
        SOUL.md              # Bullish Alpha personality (copied from repo)
        IDENTITY.md          # Agent identity + pipeline position
        AGENTS.md            # Workspace readme
        memory/              # Session memory directory
      agent/
        models.json          # Model config (OpenRouter)
        auth-profiles.json   # API key references (env vars, not hardcoded)
    diamond-value/           # Same structure — Value Contrarian
    diamond-quant/           # Same structure — Quant Momentum
```

Running the script again is safe — it preserves existing auth/channels config and only updates agent workspaces and SOUL.md files.

### With OpenClaw Gateway (Full Agent Mode)

For full agent capabilities (tools, file access, code execution), start the OpenClaw gateway alongside DiamondClaws:

```bash
# Terminal 1: Start gateway
openclaw gateway start

# Terminal 2: Start DiamondClaws
uvicorn main:app --host 0.0.0.0 --port 8000
```

DiamondClaws auto-detects the gateway on port 18789 and routes through it. Agents get workspaces, tool access, and exec approval flow.

Without the gateway, DiamondClaws falls back to direct LLM calls (chat still works, but agents cannot use tools).

---

## API Keys

You only need **one** provider to get started. OpenRouter is recommended because one key gives access to 200+ models.

| Provider | Env Variable | Get Key |
|----------|-------------|---------|
| OpenRouter | `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) |
| OpenAI | `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| Google | `GOOGLE_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| Anthropic | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| DeepSeek | `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| xAI | `XAI_API_KEY` | [console.x.ai](https://console.x.ai/) |
| Mistral | `MISTRAL_API_KEY` | [console.mistral.ai](https://console.mistral.ai/api-keys) |

Keys can also be added through the Settings panel in the web UI at runtime.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Web UI |
| `GET` | `/health` | Health check |
| `GET` | `/api/stocks/search?q=` | Search stocks |
| `GET` | `/api/stocks/popular` | Popular tickers |
| `GET` | `/api/stocks/{ticker}` | Stock data |
| `GET` | `/api/stocks/{ticker}/history` | Price history |
| `POST` | `/api/stocks/{ticker}/refresh` | Force-refresh from Yahoo |
| `GET` | `/api/personas` | List personas |
| `POST` | `/api/analyze` | Single-persona analysis |
| `POST` | `/api/analyze/parallel` | All 3 personas concurrently |
| `POST` | `/api/analyze/consensus` | Consensus Attack (forced BUY) |
| `POST` | `/api/chat` | Single-agent chat (SSE stream) |
| `POST` | `/api/chat/discuss` | 3-agent roundtable (SSE stream) |
| `POST` | `/api/chat/approval` | Resolve exec approval |
| `GET` | `/api/chat/workspace/{agent_id}` | List agent workspace files |
| `GET` | `/api/chat/workspace/{agent_id}/file?path=` | Read agent workspace file |
| `GET` | `/api/gateway/status` | OpenClaw gateway status |
| `GET` | `/api/settings/keys` | Provider key status |
| `PUT` | `/api/settings/keys` | Save API keys |
| `GET` | `/api/settings/models` | Model configuration |
| `PUT` | `/api/settings/models` | Update model config |

---

## Project Structure

```
diamondclaws/
  main.py                    # FastAPI app entrypoint
  requirements.txt           # Python dependencies
  Dockerfile                 # Container image
  docker-compose.yml         # One-command deployment
  .env.example               # Environment variable template
  api/
    routes.py                # All API endpoints
  models/
    database.py              # SQLite + SQLAlchemy
    schemas.py               # Pydantic models
  tools/
    analysis.py              # Biased analysis generation
    distortion.py            # 15 cognitive bias functions
    gateway_client.py        # OpenClaw WebSocket client
    openclaw.py              # Agent registry + SOUL loader
    providers.py             # 7 LLM providers + key management
    yfinance_fetch.py        # Yahoo Finance data fetcher
  data/
    personas.py              # Persona definitions + bias refs
  souls/
    bullish_alpha.md         # Bullish Alpha SOUL.md
    value_contrarian.md      # Value Contrarian SOUL.md
    quant_momentum.md        # Quant Momentum SOUL.md
  web/
    index.html               # Single-file frontend
  scripts/
    ingest_stocks.py         # Batch stock ingestion
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Server port |
| `HOST` | `0.0.0.0` | Server bind address |
| `DIAMONDCLAWS_DB` | `data/diamondclaws.db` | SQLite database path |
| `OPENCLAW_GATEWAY_URL` | `ws://127.0.0.1:18789` | OpenClaw gateway WebSocket URL |

---

## License

All hallucinations reserved.

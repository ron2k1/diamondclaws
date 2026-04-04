from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Load environment variables from .env file (restricted 600 permissions)
load_dotenv()

from models.database import init_db, get_all_stocks, upsert_stock
from api import routes


# Tickers to auto-seed on startup (demo fallback patches live prices from Yahoo query2)
_SEED_TICKERS = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "NFLX",
    "CRM", "ADBE", "PLTR", "SNOW", "CRWD",
    "JPM", "BAC", "GS", "V", "MA", "BX", "ICE",
    "JNJ", "UNH", "LLY", "PFE", "ABBV", "REGN", "BMY",
    "WMT", "MCD", "NKE", "HD", "SBUX", "LULU",
    "XOM", "CVX", "COP", "MPC", "PSX", "OXY",
    "BA", "CAT", "LMT", "GE", "MMM",
    "COIN", "RIOT", "MARA",
    "GME", "AMC",
    "PYPL", "SQ",
]


def _seed_stocks():
    """Seed DB with popular tickers if empty. Uses demo fallback + live prices."""
    from tools.yfinance_fetch import fetch_fundamentals, fetch_price_history
    from datetime import datetime, timezone

    existing = get_all_stocks()
    if len(existing) >= 10:
        print(f"[seed] DB already has {len(existing)} stocks, skipping seed.")
        return

    print(f"[seed] DB has {len(existing)} stocks — seeding {len(_SEED_TICKERS)} tickers...")
    ok = 0
    for ticker in _SEED_TICKERS:
        try:
            fundamentals = fetch_fundamentals(ticker, use_demo=True)
            if not fundamentals:
                continue
            price_history = fetch_price_history(ticker, use_demo=True)
            data = {
                **fundamentals,
                "price_history": price_history or "[]",
                "news_json": "[]",
                "fundamentals_updated": datetime.now(tz=timezone.utc).isoformat(),
            }
            upsert_stock(data)
            ok += 1
        except Exception as e:
            print(f"[seed] {ticker} failed: {e}")
    print(f"[seed] Done — {ok}/{len(_SEED_TICKERS)} tickers seeded.")


def _rate_limit_error_handler(request, exc):
    return FileResponse("web/index.html", status_code=429)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_stocks()
    yield


limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

app = FastAPI(
    title="StonxBuddy API",
    description="The Deliberately Biased Stock Analyst",
    version="1.0.0",
    lifespan=lifespan,
    root_path="",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router, prefix="/api", tags=["api"])
app.mount("/static", StaticFiles(directory="web"), name="static")


@app.get("/")
async def root():
    return FileResponse("web/index.html")


@app.get("/health")
async def health():
    return {"status": "healthy"}

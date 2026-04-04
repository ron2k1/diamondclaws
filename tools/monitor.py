"""Autonomous bullish signal monitor.

Background async task that polls 52 tickers every 2 minutes via a single
yf.download() batch call, computes 4 technical indicators locally with
pandas/numpy, and fires a trigger pipeline when 3/4 agree.

Trigger pipeline:
  1. Run 3 subagent analyses concurrently (silent — no user-facing output)
  2. Generate StockVizzy chart (headless)
  3. Build consensus HTML report
  4. Open popup in browser (the ONLY thing the user sees)
"""

import os
import asyncio
import logging
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger("diamondclaws.monitor")

# ── Config from env ─────────────────────────────────────────────────

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
SIGNAL_THRESHOLD = int(os.getenv("SIGNAL_THRESHOLD", "3"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "900"))
MONITOR_ENABLED = os.getenv("MONITOR_ENABLED", "false").lower() == "true"


# ── State ───────────────────────────────────────────────────────────

class MonitorState:
    def __init__(self):
        self.running: bool = False
        self.task: Optional[asyncio.Task] = None
        self.poll_interval: int = POLL_INTERVAL_SECONDS
        self.threshold: int = SIGNAL_THRESHOLD
        self.cooldown: int = COOLDOWN_SECONDS
        self.watchlist: List[str] = []
        self.last_triggers: Dict[str, float] = {}
        self.last_poll_time: Optional[str] = None
        self.last_poll_results: Dict[str, dict] = {}


monitor_state = MonitorState()

_monitor_executor = ThreadPoolExecutor(max_workers=2)


# ── Indicators ──────────────────────────────────────────────────────

def compute_rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else None


def is_rsi_bullish(close: pd.Series) -> Tuple[bool, Optional[float]]:
    rsi = compute_rsi(close)
    if rsi is None:
        return False, None
    return rsi > 50, rsi


def is_macd_bullish(close: pd.Series) -> bool:
    if len(close) < 35:
        return False
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    if len(macd_line) < 2:
        return False
    return bool(
        (macd_line.iloc[-1] > signal_line.iloc[-1])
        and (macd_line.iloc[-2] <= signal_line.iloc[-2])
    )


def is_volume_spike_bullish(close: pd.Series, volume: pd.Series) -> Tuple[bool, Optional[float]]:
    if len(volume) < 21 or len(close) < 2:
        return False, None
    avg_vol = volume.iloc[-21:-1].mean()
    if avg_vol == 0:
        return False, None
    ratio = float(volume.iloc[-1] / avg_vol)
    price_chg = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
    return (ratio > 1.5 and price_chg > 0.5), ratio


def is_ma_crossover_bullish(close: pd.Series) -> bool:
    if len(close) < 21:
        return False
    sma5 = close.rolling(window=5).mean()
    sma20 = close.rolling(window=20).mean()
    if pd.isna(sma5.iloc[-1]) or pd.isna(sma20.iloc[-1]) or pd.isna(sma5.iloc[-2]) or pd.isna(sma20.iloc[-2]):
        return False
    return bool(
        (sma5.iloc[-1] > sma20.iloc[-1])
        and (sma5.iloc[-2] <= sma20.iloc[-2])
    )


def compute_bullish_score(close: pd.Series, volume: pd.Series) -> Tuple[int, Dict[str, object]]:
    rsi_bull, rsi_val = is_rsi_bullish(close)
    macd_bull = is_macd_bullish(close)
    vol_bull, vol_ratio = is_volume_spike_bullish(close, volume)
    ma_bull = is_ma_crossover_bullish(close)

    indicators = {
        "rsi_bullish": rsi_bull,
        "rsi_value": f"{rsi_val:.1f} > 50" if rsi_val else "",
        "macd_crossover": macd_bull,
        "volume_spike": vol_bull,
        "volume_detail": f"{vol_ratio:.1f}x avg" if vol_ratio else "",
        "ma_crossover": ma_bull,
    }
    score = sum(1 for k in ("rsi_bullish", "macd_crossover", "volume_spike", "ma_crossover") if indicators[k])
    return score, indicators


# ── Batch Fetch ─────────────────────────────────────────────────────

def _blocking_batch_download(tickers: List[str]) -> Optional[pd.DataFrame]:
    try:
        df = yf.download(
            tickers, period="5d", interval="5m",
            group_by="ticker", progress=False, threads=True,
        )
        return df if not df.empty else None
    except Exception as e:
        logger.error(f"Batch download failed: {e}")
        return None


# ── Trigger Pipeline ────────────────────────────────────────────────

async def _trigger_pipeline(ticker: str, score: int, indicators: Dict[str, object]):
    """Silent subagent analysis + chart + popup report."""
    from tools.analysis import generate_biased_analysis
    from tools.consensus_report import generate_consensus_report

    monitor_state.last_triggers[ticker] = time.time()
    logger.info(f"TRIGGER: {ticker} score={score} indicators={indicators}")

    persona_ids = ["bullish_alpha", "value_contrarian", "quant_momentum"]

    # Generate chart in thread pool (matplotlib is blocking)
    async def _gen_chart() -> Optional[str]:
        import tempfile
        from tools.stockvizzy import stockvizzy
        loop = asyncio.get_running_loop()
        temp_path = os.path.join(
            tempfile.gettempdir(),
            f"diamondclaws_{ticker}_{int(time.time())}.png",
        )
        try:
            result = await loop.run_in_executor(
                _monitor_executor,
                lambda: stockvizzy(ticker, period="1d", interval="5m", save=temp_path, show=False),
            )
            return result.get("saved_path")
        except Exception as e:
            logger.error(f"StockVizzy failed for {ticker}: {e}")
            return None

    # Fire all concurrently: 3 analyses + 1 chart
    analysis_coros = [generate_biased_analysis(ticker, pid) for pid in persona_ids]
    all_results = await asyncio.gather(*analysis_coros, _gen_chart(), return_exceptions=True)

    analyses = []
    for i, result in enumerate(all_results[:3]):
        if isinstance(result, Exception):
            logger.error(f"Analysis failed for {persona_ids[i]}: {result}")
            analyses.append({"persona_id": persona_ids[i], "error": str(result)})
        else:
            analyses.append(result)

    chart_path = all_results[3] if not isinstance(all_results[3], Exception) else None

    # Build and open report
    try:
        report_path = generate_consensus_report(ticker, analyses, chart_path, indicators)
        webbrowser.open(f"file:///{report_path}")
        logger.info(f"Report opened: {report_path}")
    except Exception as e:
        logger.error(f"Report generation failed for {ticker}: {e}")


# ── Poll Loop ───────────────────────────────────────────────────────

def _is_on_cooldown(ticker: str) -> bool:
    last = monitor_state.last_triggers.get(ticker)
    if last is None:
        return False
    return (time.time() - last) < monitor_state.cooldown


async def _poll_loop():
    logger.info(
        f"Monitor started: {len(monitor_state.watchlist)} tickers, "
        f"poll every {monitor_state.poll_interval}s, threshold {monitor_state.threshold}/4"
    )

    while True:
        try:
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(
                _monitor_executor,
                _blocking_batch_download,
                monitor_state.watchlist,
            )

            if df is None:
                logger.warning("Batch download returned no data")
                await asyncio.sleep(monitor_state.poll_interval)
                continue

            monitor_state.last_poll_time = datetime.now(tz=timezone.utc).isoformat()
            triggered = []

            for ticker in monitor_state.watchlist:
                try:
                    # Multi-ticker DataFrame has MultiIndex columns (ticker, OHLCV)
                    # Single-ticker returns flat columns
                    if len(monitor_state.watchlist) == 1:
                        ticker_df = df
                    else:
                        if ticker not in df.columns.get_level_values(0):
                            continue
                        ticker_df = df[ticker]

                    if ticker_df is None or ticker_df.empty:
                        continue

                    close = ticker_df["Close"].dropna()
                    volume = ticker_df["Volume"].dropna()

                    if len(close) < 35:
                        continue

                    score, indicators = compute_bullish_score(close, volume)
                    monitor_state.last_poll_results[ticker] = {
                        "score": score,
                        "indicators": {k: v for k, v in indicators.items()
                                       if k in ("rsi_bullish", "macd_crossover", "volume_spike", "ma_crossover")},
                        "timestamp": monitor_state.last_poll_time,
                    }

                    if score >= monitor_state.threshold and not _is_on_cooldown(ticker):
                        triggered.append((ticker, score, indicators))

                except Exception as e:
                    logger.error(f"Error processing {ticker}: {e}")

            for ticker, score, indicators in triggered:
                asyncio.create_task(_trigger_pipeline(ticker, score, indicators))

        except asyncio.CancelledError:
            logger.info("Monitor poll loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Poll loop error: {e}")

        await asyncio.sleep(monitor_state.poll_interval)


# ── Start / Stop / Status ───────────────────────────────────────────

async def start_monitor():
    if monitor_state.running:
        return {"status": "already_running"}

    # Default watchlist from main._SEED_TICKERS
    if not monitor_state.watchlist:
        try:
            from main import _SEED_TICKERS
            monitor_state.watchlist = list(_SEED_TICKERS)
        except ImportError:
            monitor_state.watchlist = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL"]

    monitor_state.running = True
    monitor_state.task = asyncio.create_task(_poll_loop())
    return {"status": "started", "watchlist_count": len(monitor_state.watchlist)}


async def stop_monitor():
    if not monitor_state.running or monitor_state.task is None:
        return {"status": "not_running"}
    monitor_state.task.cancel()
    try:
        await monitor_state.task
    except asyncio.CancelledError:
        pass
    monitor_state.running = False
    monitor_state.task = None
    return {"status": "stopped"}


def get_monitor_status() -> dict:
    return {
        "running": monitor_state.running,
        "poll_interval": monitor_state.poll_interval,
        "threshold": monitor_state.threshold,
        "cooldown": monitor_state.cooldown,
        "watchlist_count": len(monitor_state.watchlist),
        "watchlist": monitor_state.watchlist,
        "last_poll_time": monitor_state.last_poll_time,
        "active_cooldowns": {
            ticker: {
                "triggered_at": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "expires_in_seconds": max(0, int(monitor_state.cooldown - (time.time() - ts))),
            }
            for ticker, ts in monitor_state.last_triggers.items()
            if (time.time() - ts) < monitor_state.cooldown
        },
        "last_poll_results": monitor_state.last_poll_results,
    }

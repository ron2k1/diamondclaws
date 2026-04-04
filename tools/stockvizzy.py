"""
StockVizzy - Stock Chart Visualizer for AI Agents & Tools

Usage:
    # CLI mode (for agents / automation)
    python stockvizzy.py AAPL --period 5d --interval 5m --save chart.png

    # Interactive mode
    python stockvizzy.py

    # Python API (import in your own scripts)
    from stockvizzy import stockvizzy
    stockvizzy("TSLA", period="1mo", interval="1h", save="tsla.png")

Supports any Yahoo Finance ticker: stocks, ETFs, crypto, forex, indices.
"""

import sys
import argparse
import yfinance as yf
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from pathlib import Path

# ── Valid yfinance interval/period combos ──
INTERVAL_LIMITS = {
    "1m": "7d", "2m": "60d", "5m": "60d", "15m": "60d",
    "30m": "60d", "1h": "730d", "1d": "max", "5d": "max",
    "1wk": "max", "1mo": "max",
}

PERIOD_CHOICES = [
    "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max",
]


# ── Data ──

def fetch_data(symbol, period="1d", interval="5m"):
    """Download price/volume data from Yahoo Finance.

    Returns (DataFrame, company_name). Falls back to 5d/5m if the
    requested combo returns nothing (e.g. market closed).
    """
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)

    if df.empty:
        df = ticker.history(period="5d", interval="5m")

    if df.empty:
        raise ValueError(
            f"No data for '{symbol}' with period={period} interval={interval}. "
            "Check the ticker symbol or try a different timeframe."
        )

    info = ticker.info
    name = info.get("shortName") or info.get("longName") or symbol
    return df, name


# ── Helpers ──

def _date_format(interval):
    if interval in ("1m", "2m", "5m", "15m", "30m"):
        return "%H:%M"
    if interval == "1h":
        return "%m/%d %H:%M"
    if interval in ("1d", "5d"):
        return "%Y-%m-%d"
    return "%Y-%m"


def _bar_width(interval):
    widths = {
        "1m": 0.0004, "2m": 0.0008, "5m": 0.002, "15m": 0.006,
        "30m": 0.012, "1h": 0.025, "1d": 0.6, "5d": 3,
        "1wk": 5, "1mo": 20,
    }
    return widths.get(interval, 0.01)


# ── Chart Builder ──

def build_chart(df, symbol, name, period, interval, save=None, show=True):
    """Render a dark-themed price + volume chart.

    Args:
        df:       DataFrame from fetch_data (needs Close, Volume columns).
        symbol:   Ticker symbol string.
        name:     Company / asset display name.
        period:   Period string used (for title).
        interval: Interval string used (for title / formatting).
        save:     If a path string, saves the chart as PNG. None = don't save.
        show:     If True, opens a matplotlib window. Set False for headless.

    Returns:
        Path to saved file if save was set, else None.
    """
    if save and not show:
        matplotlib.use("Agg")

    date_fmt = _date_format(interval)
    bar_w = _bar_width(interval)

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    # Price line
    ax.plot(df.index, df["Close"], color="#00d4ff", linewidth=1.8, label="Close")
    ax.fill_between(df.index, df["Close"], df["Close"].min() * 0.999,
                    alpha=0.12, color="#00d4ff")

    # Volume bars
    ax2 = ax.twinx()
    ax2.bar(df.index, df["Volume"], width=bar_w, alpha=0.25, color="#e94560")
    ax2.set_ylabel("Volume", color="#e94560", fontsize=10)
    ax2.tick_params(axis="y", colors="#e94560")

    # Title
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    ax.set_title(
        f"{name} ({symbol})  --  {period} @ {interval}    ({ts})",
        color="white", fontsize=13, fontweight="bold", pad=15,
    )

    # Axes
    ax.set_ylabel("Price (USD)", color="#00d4ff", fontsize=10)
    ax.tick_params(axis="x", colors="white", rotation=30)
    ax.tick_params(axis="y", colors="#00d4ff")
    ax.xaxis.set_major_formatter(mdates.DateFormatter(date_fmt))
    ax.grid(axis="y", alpha=0.15, color="white")
    ax.legend(loc="upper left", facecolor="#16213e", edgecolor="white", labelcolor="white")

    # Latest price annotation
    last_price = df["Close"].iloc[-1]
    last_time = df.index[-1]
    ax.annotate(
        f"${last_price:.2f}",
        xy=(last_time, last_price),
        xytext=(15, 15), textcoords="offset points",
        color="#00ff88", fontsize=12, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#00ff88"),
    )

    # High / Low markers
    hi_idx, lo_idx = df["Close"].idxmax(), df["Close"].idxmin()
    ax.annotate(
        f"H ${df['Close'].max():.2f}", xy=(hi_idx, df["Close"].max()),
        xytext=(0, 12), textcoords="offset points", ha="center",
        color="#00ff88", fontsize=9, fontweight="bold",
    )
    ax.annotate(
        f"L ${df['Close'].min():.2f}", xy=(lo_idx, df["Close"].min()),
        xytext=(0, -16), textcoords="offset points", ha="center",
        color="#ff4444", fontsize=9, fontweight="bold",
    )

    # Stats box
    pct = ((df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[0]) * 100
    sign = "+" if pct >= 0 else ""
    stats = (
        f"Open:   ${df['Close'].iloc[0]:.2f}\n"
        f"Close:  ${last_price:.2f}\n"
        f"Change: {sign}{pct:.2f}%\n"
        f"High:   ${df['Close'].max():.2f}\n"
        f"Low:    ${df['Close'].min():.2f}\n"
        f"Avg Vol: {df['Volume'].mean():,.0f}"
    )
    props = dict(boxstyle="round,pad=0.5", facecolor="#0f3460", edgecolor="#00d4ff", alpha=0.85)
    ax.text(0.01, 0.97, stats, transform=ax.transAxes, fontsize=9,
            verticalalignment="top", color="white", bbox=props, family="monospace")

    plt.tight_layout()

    saved_path = None
    if save:
        p = Path(save)
        fig.savefig(p, dpi=150, facecolor=fig.get_facecolor(), edgecolor="none")
        saved_path = str(p.resolve())

    if show:
        plt.show()
    else:
        plt.close(fig)

    return saved_path


# ── Public API ──

def stockvizzy(symbol, period="1d", interval="5m", save=None, show=True):
    """One-call API for AI agents and scripts.

    Args:
        symbol:   Any Yahoo Finance ticker (e.g. "AAPL", "BTC-USD", "^GSPC").
        period:   Data period - 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max.
        interval: Bar interval - 1m, 2m, 5m, 15m, 30m, 1h, 1d, 5d, 1wk, 1mo.
        save:     File path to save PNG. None = don't save.
        show:     Open a GUI window. False for headless (server / CI).

    Returns:
        dict with keys: symbol, name, period, interval, last_price,
        change_pct, high, low, saved_path, data_points.

    Example:
        from stockvizzy import stockvizzy
        result = stockvizzy("TSLA", period="1mo", interval="1h", save="tsla.png", show=False)
        print(result["last_price"])
    """
    if interval not in INTERVAL_LIMITS:
        raise ValueError(f"Invalid interval '{interval}'. Choose from: {list(INTERVAL_LIMITS)}")

    df, name = fetch_data(symbol, period, interval)
    saved_path = build_chart(df, symbol, name, period, interval, save=save, show=show)

    pct = ((df["Close"].iloc[-1] - df["Close"].iloc[0]) / df["Close"].iloc[0]) * 100

    return {
        "symbol": symbol,
        "name": name,
        "period": period,
        "interval": interval,
        "last_price": round(float(df["Close"].iloc[-1]), 2),
        "change_pct": round(pct, 2),
        "high": round(float(df["Close"].max()), 2),
        "low": round(float(df["Close"].min()), 2),
        "avg_volume": int(df["Volume"].mean()),
        "data_points": len(df),
        "saved_path": saved_path,
    }


# ── Interactive prompt ──

def _interactive():
    print("\n+======================================+")
    print("|         S T O C K V I Z Z Y          |")
    print("+======================================+\n")

    symbol = input("  Ticker (e.g. AAPL, TSLA, BTC-USD): ").strip().upper()
    if not symbol:
        print("No ticker. Exiting.")
        sys.exit(1)

    print(f"\n  Periods:   {', '.join(PERIOD_CHOICES)}")
    period = input("  Period   [1d]: ").strip().lower() or "1d"

    print(f"\n  Intervals: {', '.join(INTERVAL_LIMITS)}")
    interval = input("  Interval [5m]: ").strip().lower() or "5m"

    save = input("\n  Save to file? (path or Enter to skip): ").strip() or None

    return stockvizzy(symbol, period, interval, save=save, show=True)


# ── CLI ──

def _cli():
    parser = argparse.ArgumentParser(
        prog="stockvizzy",
        description="Stock chart visualizer for AI agents and humans.",
    )
    parser.add_argument("symbol", nargs="?", help="Ticker symbol (e.g. AAPL, BTC-USD)")
    parser.add_argument("-p", "--period", default="1d", help="Data period (default: 1d)")
    parser.add_argument("-i", "--interval", default="5m", help="Bar interval (default: 5m)")
    parser.add_argument("-s", "--save", default=None, help="Save chart to PNG path")
    parser.add_argument("--no-show", action="store_true", help="Don't open GUI window (headless)")

    args = parser.parse_args()

    if args.symbol is None:
        return _interactive()

    result = stockvizzy(
        args.symbol.upper(),
        period=args.period,
        interval=args.interval,
        save=args.save,
        show=not args.no_show,
    )

    # Print JSON summary to stdout for agents to parse
    import json
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    _cli()

"""Consensus HTML report generator.

Builds a self-contained HTML file with embedded StockVizzy chart and
3 subagent analysis sections.  Design is a placeholder — frontend team
owns final styling.  Code uses semantic CSS classes for easy restyling.
"""

import base64
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

# In-memory pointer to the most recent report per ticker
_recent_reports: Dict[str, str] = {}


def generate_consensus_report(
    ticker: str,
    analyses: List[dict],
    chart_path: Optional[str] = None,
    indicators: Optional[Dict[str, dict]] = None,
) -> str:
    """Generate a self-contained HTML consensus report.

    Args:
        ticker:     Stock ticker symbol.
        analyses:   List of dicts from generate_biased_analysis() (one per persona).
        chart_path: Path to StockVizzy PNG chart (embedded as base64).
        indicators: Dict of indicator results, e.g.
                    {"rsi_bullish": True, "macd_crossover": False, ...}
                    with optional "rsi_value", "volume_ratio", etc.

    Returns:
        Absolute path to the generated HTML file.
    """
    indicators = indicators or {}
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Chart
    chart_b64 = ""
    if chart_path and os.path.exists(chart_path):
        with open(chart_path, "rb") as f:
            chart_b64 = base64.b64encode(f.read()).decode("utf-8")

    chart_html = (
        f'<img src="data:image/png;base64,{chart_b64}" class="chart" alt="{ticker} Chart" />'
        if chart_b64
        else '<div class="chart-placeholder">Chart unavailable</div>'
    )

    # Price from first valid analysis
    price = 0.0
    change_pct = 0.0
    stock_name = ticker
    for a in analyses:
        if "error" not in a:
            price = a.get("current_price", 0)
            stock_name = a.get("stock_name", ticker)
            sd = a.get("stock_data", {})
            high = sd.get("high_52w", 0)
            low = sd.get("low_52w", 0)
            if low and price:
                change_pct = ((price - low) / low) * 100
            break

    # Signal cards
    signal_defs = [
        ("RSI (14)", "rsi_bullish", indicators.get("rsi_value", "")),
        ("MACD Cross", "macd_crossover", "Bullish crossover" if indicators.get("macd_crossover") else "No cross"),
        ("Volume Spike", "volume_spike", indicators.get("volume_detail", "")),
        ("MA Cross", "ma_crossover", "SMA5 > SMA20" if indicators.get("ma_crossover") else "SMA5 < SMA20"),
    ]

    signals_html = ""
    score = 0
    for label, key, detail in signal_defs:
        active = indicators.get(key, False)
        if active:
            score += 1
        cls = "signal active" if active else "signal"
        icon = "&#x2705;" if active else "&#x274C;"
        detail_str = str(detail) if detail else ""
        signals_html += f"""
        <div class="{cls}">
            <div class="indicator">{label}</div>
            <div class="status">{icon}</div>
            <div class="value">{detail_str}</div>
        </div>"""

    # Agent sections
    persona_colors = {
        "bullish_alpha": "#22c55e",
        "value_contrarian": "#3b82f6",
        "quant_momentum": "#a855f7",
    }
    persona_classes = {
        "bullish_alpha": "bull",
        "value_contrarian": "value",
        "quant_momentum": "quant",
    }

    agents_html = ""
    for a in analyses:
        if "error" in a:
            continue
        pid = a.get("persona_id", "unknown")
        name = a.get("persona", pid)
        cls = persona_classes.get(pid, "")
        text = a.get("analysis", "")
        words = text.split()
        excerpt = " ".join(words[:100]) + ("..." if len(words) > 100 else "")
        rec = a.get("stock_data", {}).get("recommendation", "N/A")
        conf = a.get("confidence_level", 0)

        agents_html += f"""
    <div class="agent {cls}">
      <div class="agent-top">
        <div class="agent-name"><span class="badge">{name}</span></div>
        <div class="agent-meta">
          <span class="rec">{rec}</span>
          <span class="conf">{conf:.0%} confidence</span>
        </div>
      </div>
      <div class="agent-text">{excerpt}</div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BULLISH CONSENSUS ALERT: {ticker}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0a0a1a; color: #e0e0e0; font-family: system-ui, sans-serif; padding: 0; min-height: 100vh; }}

  .pulse-bar {{ height: 4px; background: linear-gradient(90deg, #22c55e, #4ade80, #22c55e); background-size: 200% 100%; animation: pulse-slide 2s ease-in-out infinite; }}
  @keyframes pulse-slide {{ 0%,100% {{ background-position: 0% 50%; }} 50% {{ background-position: 100% 50%; }} }}

  .container {{ max-width: 880px; margin: 0 auto; padding: 24px 28px 32px; }}

  .alert-badge {{ display: inline-flex; align-items: center; gap: 8px; background: rgba(34,197,94,0.12); border: 1px solid rgba(34,197,94,0.3); border-radius: 20px; padding: 6px 16px; font-size: 11px; font-weight: 700; color: #4ade80; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 12px; }}
  .alert-badge .dot {{ width: 8px; height: 8px; background: #22c55e; border-radius: 50%; animation: blink 1.2s infinite; }}
  @keyframes blink {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.3; }} }}

  .header {{ padding: 20px 0 16px; margin-bottom: 20px; }}
  .header h1 {{ color: #fff; font-size: 28px; font-weight: 900; letter-spacing: -0.5px; }}
  .header h1 .ticker {{ color: #22c55e; }}
  .header .subtitle {{ color: #888; font-size: 13px; margin-top: 6px; font-family: monospace; }}

  .price-strip {{ display: flex; align-items: baseline; gap: 16px; padding: 14px 20px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; margin-bottom: 20px; }}
  .price-strip .price {{ font-size: 32px; font-weight: 800; color: #fff; font-family: monospace; }}
  .price-strip .change {{ font-size: 15px; font-weight: 600; padding: 4px 10px; border-radius: 6px; }}
  .price-strip .change.up {{ color: #4ade80; background: rgba(34,197,94,0.1); }}
  .price-strip .change.down {{ color: #f87171; background: rgba(248,113,113,0.1); }}
  .price-strip .label {{ color: #666; font-size: 12px; font-family: monospace; }}

  .chart-wrap {{ border-radius: 12px; overflow: hidden; border: 1px solid rgba(255,255,255,0.06); margin-bottom: 24px; }}
  .chart-wrap img {{ width: 100%; display: block; }}
  .chart-placeholder {{ background: #1a1a2e; border: 1px dashed #444; border-radius: 8px; padding: 40px; text-align: center; color: #666; margin-bottom: 24px; }}

  .signals {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 24px; }}
  .signal {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 14px 12px; text-align: center; }}
  .signal.active {{ border-color: rgba(34,197,94,0.4); background: rgba(34,197,94,0.06); }}
  .signal .indicator {{ font-size: 11px; color: #888; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
  .signal .status {{ font-size: 20px; }}
  .signal .value {{ font-size: 11px; color: #aaa; margin-top: 4px; font-family: monospace; }}

  .consensus-bar {{ display: flex; align-items: center; gap: 12px; padding: 14px 20px; background: linear-gradient(135deg, rgba(34,197,94,0.08), rgba(34,197,94,0.02)); border: 1px solid rgba(34,197,94,0.2); border-radius: 10px; margin-bottom: 24px; }}
  .consensus-bar .label {{ font-size: 12px; color: #888; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }}
  .consensus-bar .verdict {{ font-size: 16px; font-weight: 800; color: #22c55e; letter-spacing: 1px; }}

  .agents {{ display: flex; flex-direction: column; gap: 16px; margin-bottom: 24px; }}
  .agent {{ background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; padding: 20px; position: relative; overflow: hidden; }}
  .agent::before {{ content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }}
  .agent.bull::before {{ background: #22c55e; }}
  .agent.value::before {{ background: #3b82f6; }}
  .agent.quant::before {{ background: #a855f7; }}

  .agent-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }}
  .agent-name .badge {{ padding: 4px 12px; border-radius: 16px; font-size: 12px; font-weight: 700; }}
  .agent.bull .badge {{ background: rgba(34,197,94,0.2); color: #4ade80; }}
  .agent.value .badge {{ background: rgba(59,130,246,0.2); color: #60a5fa; }}
  .agent.quant .badge {{ background: rgba(168,85,247,0.2); color: #c084fc; }}
  .agent-meta {{ display: flex; gap: 16px; font-size: 12px; }}
  .agent-meta .rec {{ font-weight: 700; color: #22c55e; }}
  .agent-meta .conf {{ color: #888; font-family: monospace; }}
  .agent-text {{ font-size: 14px; line-height: 1.7; color: #bbb; }}

  .footer {{ text-align: center; padding: 20px 0 0; border-top: 1px solid rgba(255,255,255,0.06); }}
  .footer p {{ color: #444; font-size: 11px; font-family: monospace; }}
  .footer .warn {{ color: #f87171; font-size: 10px; margin-top: 6px; }}
</style>
</head>
<body>
<div class="pulse-bar"></div>
<div class="container">

  <div class="header">
    <div class="alert-badge"><span class="dot"></span> CONSENSUS ALERT</div>
    <h1>All 3 analysts agree on <span class="ticker">{ticker}</span></h1>
    <div class="subtitle">{ts} // DiamondClaws Autonomous Monitor</div>
  </div>

  <div class="price-strip">
    <span class="price">${price:.2f}</span>
    <span class="change {"up" if change_pct >= 0 else "down"}">{'+' if change_pct >= 0 else ''}{change_pct:.2f}%</span>
    <span class="label">{stock_name}</span>
  </div>

  <div class="chart-wrap">
    {chart_html}
  </div>

  <div class="signals">
    {signals_html}
  </div>

  <div class="consensus-bar">
    <span class="label">Consensus</span>
    <span class="verdict">STRONG BUY &mdash; {score}/4 SIGNALS TRIGGERED</span>
  </div>

  <div class="agents">
    {agents_html}
  </div>

  <div class="footer">
    <p>Generated by DiamondClaws &mdash; The Deliberately Biased Stock Analyst</p>
    <p class="warn">This is satire. Do not make financial decisions based on cognitively distorted AI output.</p>
  </div>

</div>
</body>
</html>"""

    report_dir = os.path.join(tempfile.gettempdir(), "diamondclaws_reports")
    os.makedirs(report_dir, exist_ok=True)
    filename = f"consensus_{ticker}_{int(time.time())}.html"
    filepath = os.path.join(report_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    _recent_reports[ticker.upper()] = filepath
    return filepath


def get_recent_report(ticker: str) -> Optional[str]:
    """Get the most recent report path for a ticker, or None."""
    path = _recent_reports.get(ticker.upper())
    if path and os.path.exists(path):
        return path
    return None

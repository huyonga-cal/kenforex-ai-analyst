
import os
import json
import math
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import feedparser
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from sqlalchemy import create_engine, text


# ============================================================
# FOREX AI ANALYST — editorial interface / paper trading only
# ============================================================

st.set_page_config(
    page_title="Forex AI Analyst",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_NAME = "FOREX / FIELDNOTES"
APP_VERSION = "evidence-v2"
DEFAULT_BALANCE = 100.0
DEFAULT_RISK_PCT = 2.0
MIN_RR = 2.0
API_URL = "https://api.twelvedata.com/time_series"

SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "NZD/USD", "USD/CAD", "EUR/GBP",
    "EUR/JPY", "GBP/JPY", "XAU/USD",
]

INTERVALS = [
    "1min", "5min", "15min", "30min",
    "1h", "2h", "4h", "1day",
]

TIMEFRAME_MAP = {
    "1min": ("5min", "15min"),
    "5min": ("15min", "1h"),
    "15min": ("1h", "4h"),
    "30min": ("1h", "4h"),
    "1h": ("4h", "1day"),
    "2h": ("4h", "1day"),
    "4h": ("1day", "1week"),
    "1day": ("1week", "1month"),
}

NEWS_FEEDS = {
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
    "European Central Bank": "https://www.ecb.europa.eu/rss/press.html",
    "Bank of England": "https://www.bankofengland.co.uk/rss/news",
    "Bank of Japan": "https://www.boj.or.jp/en/rss/whatsnew.xml",
    "US Treasury": "https://home.treasury.gov/news/press-releases/rss",
}


# -------------------- Visual system -------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@400;500;600&display=swap');

:root {
  --paper: #F4F0E8;
  --surface: #FBF9F4;
  --ink: #20231F;
  --muted: #77786F;
  --line: #DAD4C8;
  --copper: #B96842;
  --green: #2E7155;
  --red: #A8483E;
}
html, body, [class*="css"] {
  font-family: 'DM Sans', sans-serif;
}
.stApp {
  background: var(--paper);
  color: var(--ink);
}
[data-testid="stHeader"] {
  background: rgba(244,240,232,.94);
}
[data-testid="stSidebar"] {
  background: #EAE4D9;
  border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] * {
  color: var(--ink);
}
.block-container {
  max-width: 1420px;
  padding-top: 1.6rem;
  padding-bottom: 4rem;
}
h1, h2, h3 {
  color: var(--ink) !important;
  letter-spacing: -.035em;
}
h1 {
  font-family: 'Playfair Display', Georgia, serif !important;
  font-weight: 400 !important;
}
h2, h3 {
  font-weight: 600 !important;
}
p, label, .stMarkdown {
  color: var(--ink);
}
small, [data-testid="stCaptionContainer"] {
  color: var(--muted) !important;
}
[data-testid="stMetric"] {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 16px 18px;
  box-shadow: none;
}
[data-testid="stMetricLabel"] {
  color: var(--muted) !important;
  font-size: .76rem;
  text-transform: uppercase;
  letter-spacing: .08em;
}
[data-testid="stMetricValue"] {
  color: var(--ink) !important;
  font-weight: 600;
}
[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: var(--line) !important;
  border-radius: 5px;
}
[data-testid="stExpander"] {
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--surface);
}
.stButton > button, .stDownloadButton > button {
  border-radius: 3px;
  border: 1px solid var(--ink);
  background: var(--ink);
  color: #FAF8F2;
  font-weight: 600;
  min-height: 2.65rem;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: var(--copper);
  background: var(--copper);
  color: white;
}
[data-testid="stDataFrame"] {
  border: 1px solid var(--line);
}
[data-baseweb="select"] > div,
[data-baseweb="input"] > div,
[data-baseweb="textarea"] > div {
  background: var(--surface);
  border-color: var(--line);
}
hr {
  border-color: var(--line);
}
.editorial-kicker {
  font-family: 'DM Mono', monospace;
  font-size: .72rem;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--copper);
}
.editorial-hero {
  background: #EAE4D9;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  padding: 3rem 2rem;
}
.editorial-note {
  border-left: 2px solid var(--copper);
  padding: .3rem 0 .3rem 1rem;
  color: var(--muted);
}
.data-label {
  font-family: 'DM Mono', monospace;
  font-size: .72rem;
  letter-spacing: .08em;
  color: var(--muted);
  text-transform: uppercase;
}
@media (max-width: 700px) {
  .block-container {
    padding-left: .8rem;
    padding-right: .8rem;
  }
  .editorial-hero {
    padding: 1.5rem 1rem;
  }
}
</style>
""", unsafe_allow_html=True)


# -------------------- Secrets / database -------------------

def get_secret(name, default=""):
    try:
        value = st.secrets.get(name, default)
        if value:
            return str(value).strip()
    except Exception:
        pass
    return os.getenv(name, default).strip()


DATABASE_URL = get_secret("DATABASE_URL")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://", "postgresql+psycopg://", 1
    )
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"connect_timeout": 10},
    ) if DATABASE_URL else None
except Exception:
    engine = None


def db_execute(sql, params=None, fetch=False):
    if engine is None:
        return [] if fetch else False
    with engine.begin() as conn:
        result = conn.execute(text(sql), params or {})
        if fetch:
            return [dict(row._mapping) for row in result]
    return True


def init_db():
    """Create compatible tables and add missing columns without deleting history."""
    if engine is None:
        return False

    statements = [
        """CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            decision TEXT NOT NULL,
            entry DOUBLE PRECISION,
            stop DOUBLE PRECISION,
            target DOUBLE PRECISION,
            risk_usd DOUBLE PRECISION,
            planned_net_rr DOUBLE PRECISION,
            news_bias TEXT,
            news_score DOUBLE PRECISION,
            news_summary TEXT,
            source_links TEXT,
            strategy_version TEXT NOT NULL DEFAULT 'baseline-v1',
            candles_json TEXT,
            higher_timeframe TEXT,
            higher_trend TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS paper_trades (
            id TEXT PRIMARY KEY,
            signal_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry DOUBLE PRECISION NOT NULL,
            stop DOUBLE PRECISION NOT NULL,
            target DOUBLE PRECISION NOT NULL,
            risk_usd DOUBLE PRECISION NOT NULL,
            planned_net_rr DOUBLE PRECISION NOT NULL,
            outcome TEXT NOT NULL DEFAULT 'OPEN',
            exit_price DOUBLE PRECISION,
            pnl_usd DOUBLE PRECISION,
            notes TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS strategy_experiments (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            name TEXT NOT NULL,
            parameters_json TEXT NOT NULL,
            baseline_metric DOUBLE PRECISION,
            candidate_metric DOUBLE PRECISION,
            validation_count INTEGER,
            status TEXT NOT NULL DEFAULT 'PENDING',
            notes TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS news_cache (
            url TEXT PRIMARY KEY,
            published_at TEXT,
            source TEXT,
            title TEXT NOT NULL,
            summary TEXT,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
    ]

    with engine.begin() as conn:
        # Serializes schema initialization across simultaneous app sessions.
        conn.execute(text("SELECT pg_advisory_xact_lock(741928, 1)"))
        for statement in statements:
            conn.execute(text(statement))

        migrations = {
            "signals": {
                "interval": "TEXT",
                "timeframe": "TEXT",
                "planned_net_rr": "DOUBLE PRECISION",
                "net_rr": "DOUBLE PRECISION",
                "higher_timeframe": "TEXT",
                "higher_trend": "TEXT",
                "news_bias": "TEXT",
                "news_score": "DOUBLE PRECISION",
                "news_summary": "TEXT",
                "source_links": "TEXT",
                "strategy_version": "TEXT DEFAULT 'baseline-v1'",
                "candles_json": "TEXT",
            },
            "paper_trades": {
                "signal_id": "TEXT",
                "planned_net_rr": "DOUBLE PRECISION DEFAULT 0",
                "net_rr": "DOUBLE PRECISION",
            },
        }

        for table, columns in migrations.items():
            for column, datatype in columns.items():
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                    f"{column} {datatype}"
                ))

        conn.execute(text("""
            UPDATE signals
            SET interval = COALESCE(interval, timeframe, 'unknown'),
                planned_net_rr = COALESCE(planned_net_rr, net_rr, 0),
                timeframe = COALESCE(timeframe, interval, 'unknown'),
                net_rr = COALESCE(net_rr, planned_net_rr, 0)
        """))
        conn.execute(text("""
            UPDATE paper_trades
            SET planned_net_rr = COALESCE(planned_net_rr, net_rr, 0),
                net_rr = COALESCE(net_rr, planned_net_rr, 0)
        """))
    return True


# -------------------- Market data / indicators --------------

@st.cache_data(ttl=60, show_spinner=False)
def fetch_candles(symbol, interval, outputsize, api_key):
    """Twelve Data candles. UTC handling deliberately remains unchanged."""
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": int(outputsize),
        "apikey": api_key,
        "format": "JSON",
        "timezone": "UTC",
        "order": "desc",
    }
    response = requests.get(API_URL, params=params, timeout=25)
    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, dict) and payload.get("status") == "error":
        raise ValueError(payload.get("message", "Twelve Data returned an error."))

    values = payload.get("values") if isinstance(payload, dict) else None
    if not values:
        raise ValueError(
            "No candles returned. Check the symbol, interval, API plan and request limit."
        )

    df = pd.DataFrame(values)
    required = ["datetime", "open", "high", "low", "close"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError("Missing candle fields: " + ", ".join(missing))

    df["datetime"] = pd.to_datetime(
        df["datetime"], errors="coerce", utc=True
    )
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = (
        df.dropna(subset=required)
        .sort_values("datetime")
        .reset_index(drop=True)
    )
    if len(df) < 56:
        raise ValueError(
            f"Only {len(df)} valid candles returned; at least 56 are required."
        )
    return df


def add_indicators(df):
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    delta = df["close"].diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi14"] = (100 - (100 / (1 + rs))).fillna(50)

    previous_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14, min_periods=14).mean()
    return df.dropna(subset=["ema20", "ema50", "atr14", "rsi14"]).reset_index(drop=True)


def classify_trend(df):
    if df is None or len(df) < 20:
        return "NEUTRAL"
    last = df.iloc[-1]
    if last["ema20"] > last["ema50"] and last["close"] > last["ema20"]:
        return "BULLISH"
    if last["ema20"] < last["ema50"] and last["close"] < last["ema20"]:
        return "BEARISH"
    return "NEUTRAL"


def market_structure(df):
    """Simple swing comparison; not an order-flow or institutional-data feed."""
    if len(df) < 20:
        return "NEUTRAL"

    sample = df.tail(100).reset_index(drop=True)
    highs, lows = [], []
    span = 2
    for i in range(span, len(sample) - span):
        if sample["high"].iloc[i] >= sample["high"].iloc[i-span:i+span+1].max():
            highs.append(float(sample["high"].iloc[i]))
        if sample["low"].iloc[i] <= sample["low"].iloc[i-span:i+span+1].min():
            lows.append(float(sample["low"].iloc[i]))

    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1] > highs[-2]
        hl = lows[-1] > lows[-2]
        lh = highs[-1] < highs[-2]
        ll = lows[-1] < lows[-2]
        if hh and hl:
            return "BULLISH"
        if lh and ll:
            return "BEARISH"
    return "NEUTRAL"


def find_zones(df):
    """Approximate zones around recent local highs and lows."""
    if len(df) < 12:
        return [], []

    sample = df.tail(100).reset_index(drop=True)
    atr = float(sample["atr14"].iloc[-1])
    width = max(atr * 0.35, abs(float(sample["close"].iloc[-1])) * 0.0001)
    highs, lows = [], []

    for i in range(2, len(sample) - 2):
        if sample["high"].iloc[i] >= sample["high"].iloc[i-2:i+3].max():
            price = float(sample["high"].iloc[i])
            highs.append({"low": price - width, "high": price + width, "mid": price})
        if sample["low"].iloc[i] <= sample["low"].iloc[i-2:i+3].min():
            price = float(sample["low"].iloc[i])
            lows.append({"low": price - width, "high": price + width, "mid": price})

    close = float(sample["close"].iloc[-1])
    supplies = sorted(highs, key=lambda z: abs(z["mid"] - close))[:5]
    demands = sorted(lows, key=lambda z: abs(z["mid"] - close))[:5]
    return supplies, demands


def pip_size_for(symbol):
    if symbol == "XAU/USD":
        return 0.1
    if "JPY" in symbol:
        return 0.01
    return 0.0001


def format_price(price, symbol):
    if price is None:
        return "—"
    digits = 2 if symbol == "XAU/USD" else (3 if "JPY" in symbol else 5)
    return f"{float(price):,.{digits}f}"


# -------------------- Evidence-weighted analyst --------------

def create_trade_plan(
    df, symbol, balance, risk_pct, pip_value_per_lot,
    min_rr=MIN_RR, spread_pips=1.0, slippage_pips=0.2,
):
    """
    Score evidence for market bias first. Risk and net R:R are separate,
    hard approval checks. This is a heuristic, not a trained prediction model.
    """
    if df is None or len(df) < 55:
        raise ValueError("Not enough candles to assess the market.")

    balance = max(0.0, float(balance))
    risk_pct = min(max(0.0, float(risk_pct)), 2.0)
    min_rr = max(2.0, float(min_rr))
    risk_budget = balance * risk_pct / 100.0

    last = df.iloc[-1]
    close = float(last["close"])
    ema20 = float(last["ema20"])
    ema50 = float(last["ema50"])
    rsi = float(last["rsi14"])
    atr = float(last["atr14"])

    if not math.isfinite(atr) or atr <= 0:
        raise ValueError("ATR is invalid; no safe stop estimate can be created.")

    supplies, demands = find_zones(df)
    structure = market_structure(df)
    score = 0.0
    evidence = []
    conflicts = []

    def add(label, points, explanation):
        nonlocal score
        score += points
        target = evidence if points >= 0 else conflicts
        target.append({
            "Factor": label,
            "Score": round(points, 2),
            "Interpretation": explanation,
        })

    # Trend: contributes evidence but does not dictate the whole decision.
    if ema20 > ema50 and close > ema20:
        add("EMA trend", 2.0, "EMA20 above EMA50; price above EMA20.")
    elif ema20 < ema50 and close < ema20:
        add("EMA trend", -2.0, "EMA20 below EMA50; price below EMA20.")
    elif ema20 > ema50:
        add("EMA trend", 0.7, "Average alignment favours upside; price confirmation is incomplete.")
    elif ema20 < ema50:
        add("EMA trend", -0.7, "Average alignment favours downside; price confirmation is incomplete.")
    else:
        evidence.append({"Factor": "EMA trend", "Score": 0, "Interpretation": "Trend averages are mixed."})

    # Momentum. Extreme RSI is treated cautiously rather than as a strict gate.
    if 52 <= rsi <= 68:
        add("RSI momentum", 1.2, f"RSI {rsi:.1f} supports positive momentum.")
    elif rsi > 68:
        add("RSI extension", 0.2, f"RSI {rsi:.1f} is elevated; late-entry risk is higher.")
        conflicts.append({"Factor": "Overextension", "Score": -0.4, "Interpretation": "Avoid assuming an extended move must continue."})
        score -= 0.4
    elif 32 <= rsi <= 48:
        add("RSI momentum", -1.2, f"RSI {rsi:.1f} supports negative momentum.")
    elif rsi < 32:
        add("RSI extension", -0.2, f"RSI {rsi:.1f} is low; downside may be extended.")
        conflicts.append({"Factor": "Overextension", "Score": 0.4, "Interpretation": "A low RSI may increase bounce risk."})
        score += 0.4
    else:
        evidence.append({"Factor": "RSI momentum", "Score": 0, "Interpretation": f"RSI {rsi:.1f} is near the midpoint."})

    if structure == "BULLISH":
        add("Swing structure", 1.5, "Recent swing highs and lows favour an upward structure.")
    elif structure == "BEARISH":
        add("Swing structure", -1.5, "Recent swing highs and lows favour a downward structure.")
    else:
        evidence.append({"Factor": "Swing structure", "Score": 0, "Interpretation": "Swing structure is mixed or unclear."})

    distance_limit = max(atr * 0.75, close * 0.0001)
    demand = min(demands, key=lambda z: abs(close - z["mid"])) if demands else None
    supply = min(supplies, key=lambda z: abs(close - z["mid"])) if supplies else None
    near_demand = bool(demand and abs(close - demand["mid"]) <= distance_limit)
    near_supply = bool(supply and abs(close - supply["mid"]) <= distance_limit)

    if near_demand:
        add("Demand proximity", 0.8, "Price is near an estimated demand zone.")
    if near_supply:
        add("Supply proximity", -0.8, "Price is near an estimated supply zone.")
    if not near_demand and not near_supply:
        evidence.append({"Factor": "Location", "Score": 0, "Interpretation": "Price is away from estimated zones; location evidence is limited."})

    if atr / close > 0.03:
        conflicts.append({"Factor": "Volatility", "Score": -0.5, "Interpretation": "ATR is unusually large relative to price."})
        score -= 0.5

    bias = "BULLISH" if score >= 1.5 else "BEARISH" if score <= -1.5 else "MIXED / NEUTRAL"
    decision = "BUY" if bias == "BULLISH" else "SELL" if bias == "BEARISH" else "WAIT"

    plan = {
        "decision": decision,
        "bias": bias,
        "score": round(score, 2),
        "evidence": evidence,
        "conflicts": conflicts,
        "reasons": [],
        "entry": None, "stop": None, "target": None,
        "risk_usd": risk_budget,
        "estimated_risk_usd": 0.0,
        "planned_net_rr": 0.0,
        "lots": None, "units": None,
        "stop_pips": None, "target_pips": None,
        "pip_value_per_lot": float(pip_value_per_lot),
        "atr": atr, "structure": structure,
        "supplies": supplies, "demands": demands,
        "near_demand": near_demand, "near_supply": near_supply,
        "risk_checks": [],
    }
    plan["reasons"].append(
        f"Directional score {score:+.2f}. This is a transparent heuristic, not a win probability."
    )

    if decision == "WAIT":
        plan["reasons"].append(
            "Evidence is mixed. Review the trend, momentum, structure and location below; no entry is forced."
        )
        return plan

    entry = close
    pip = pip_size_for(symbol)

    if decision == "BUY":
        stop = min(demand["low"] if demand else close - 1.5 * atr, close - atr)
        risk_distance = entry - stop
        target = entry + min_rr * risk_distance
        if supply and supply["low"] >= entry + min_rr * risk_distance:
            target = supply["low"]
    else:
        stop = max(supply["high"] if supply else close + 1.5 * atr, close + atr)
        risk_distance = stop - entry
        target = entry - min_rr * risk_distance
        if demand and demand["high"] <= entry - min_rr * risk_distance:
            target = demand["high"]

    if risk_distance <= 0 or pip <= 0 or not all(
        math.isfinite(v) for v in (entry, stop, target)
    ):
        plan["decision"] = "NO TRADE"
        plan["reasons"].append("A valid entry, stop and target could not be constructed.")
        return plan

    stop_pips = abs(entry - stop) / pip
    target_pips = abs(target - entry) / pip
    friction = max(0.0, float(spread_pips)) + max(0.0, float(slippage_pips))
    effective_risk_pips = stop_pips + friction

    if pip_value_per_lot <= 0 or risk_budget <= 0 or effective_risk_pips <= 0:
        plan["decision"] = "NO TRADE"
        plan["reasons"].append("Risk budget, pip value or stop distance is invalid.")
        return plan

    raw_lots = risk_budget / (effective_risk_pips * pip_value_per_lot)
    lots = math.floor((raw_lots + 1e-12) / 0.01) * 0.01
    estimated_risk = effective_risk_pips * pip_value_per_lot * lots
    estimated_reward = max(0.0, target_pips - friction) * pip_value_per_lot * lots
    net_rr = estimated_reward / estimated_risk if estimated_risk > 0 else 0.0

    plan.update({
        "entry": entry, "stop": stop, "target": target,
        "stop_pips": stop_pips, "target_pips": target_pips,
        "friction_pips": friction,
        "lots": lots,
        "units": lots * (100 if symbol == "XAU/USD" else 100000),
        "estimated_risk_usd": estimated_risk,
        "planned_reward_usd": estimated_reward,
        "planned_net_rr": net_rr,
        "rr": net_rr,
    })

    checks = [
        ("Risk budget", estimated_risk <= risk_budget + 1e-9,
         f"Estimated risk ${estimated_risk:.2f}; budget ${risk_budget:.2f}."),
        ("Minimum net R:R", net_rr >= min_rr - 1e-9,
         f"Estimated net R:R 1:{net_rr:.2f}; minimum 1:{min_rr:.2f}."),
        ("Minimum lot size", lots >= 0.01,
         f"Calculated size {lots:.2f}; simulated minimum 0.01."),
    ]
    plan["risk_checks"] = [
        {"Check": name, "Passed": passed, "Detail": detail}
        for name, passed, detail in checks
    ]

    failures = [detail for _, passed, detail in checks if not passed]
    if failures:
        plan["decision"] = "NO TRADE"
        plan["reasons"].extend(["Risk approval failed: " + msg for msg in failures])
        plan["entry"] = plan["stop"] = plan["target"] = None
        plan["lots"] = plan["units"] = None
        return plan

    plan["reasons"].append(
        f"Candidate passes the configured mathematical checks: estimated risk "
        f"${estimated_risk:.2f}; estimated net R:R 1:{net_rr:.2f}."
    )
    plan["reasons"].append(
        "These are estimates, not guaranteed fills, broker-verified contract values or evidence of profitability."
    )
    return plan


# -------------------- News intelligence ---------------------

def fetch_news(symbol):
    items = []

    for source, url in NEWS_FEEDS.items():
        try:
            parsed = feedparser.parse(
                url, request_headers={"User-Agent": "ForexAIAnalyst/2.0"}
            )
            for entry in parsed.entries[:12]:
                title = str(entry.get("title", "")).strip()
                link = str(entry.get("link", "")).strip()
                if title and link:
                    items.append({
                        "source": source,
                        "title": title,
                        "summary": str(entry.get("summary", ""))[:1200],
                        "url": link,
                        "published": str(entry.get("published", entry.get("updated", ""))),
                    })
        except Exception:
            continue

    try:
        pair = symbol.replace("/", " ")
        query = quote(f'"{pair}" forex OR currency')
        url = (
            "https://api.gdeltproject.org/api/v2/doc/doc?"
            f"query={query}&mode=ArtList&format=json&maxrecords=20&sort=DateDesc"
        )
        response = requests.get(url, timeout=12, headers={"User-Agent": "ForexAIAnalyst/2.0"})
        response.raise_for_status()
        for item in response.json().get("articles", []):
            if item.get("url") and item.get("title"):
                items.append({
                    "source": item.get("domain", "GDELT public news"),
                    "title": item.get("title", ""),
                    "summary": item.get("seendate", ""),
                    "url": item.get("url", ""),
                    "published": item.get("seendate", ""),
                })
    except Exception:
        pass

    unique = {item["url"]: item for item in items if item.get("url")}
    items = list(unique.values())[:80]

    if engine is not None:
        for item in items:
            try:
                db_execute("""
                    INSERT INTO news_cache(url,published_at,source,title,summary)
                    VALUES(:url,:published,:source,:title,:summary)
                    ON CONFLICT(url) DO UPDATE SET
                      title=EXCLUDED.title,
                      summary=EXCLUDED.summary,
                      fetched_at=NOW()
                """, {
                    "url": item["url"],
                    "published": item["published"],
                    "source": item["source"],
                    "title": item["title"],
                    "summary": item["summary"],
                })
            except Exception:
                pass
    return items


def score_news(items, symbol):
    positive = {
        "hawkish", "rate hike", "raises rates", "strong growth",
        "beats forecast", "inflation rises", "tightening", "surplus",
    }
    negative = {
        "dovish", "rate cut", "cuts rates", "recession",
        "misses forecast", "easing", "deficit", "unemployment rises",
    }
    currencies = symbol.split("/")
    relevant = []

    for item in items:
        title = item.get("title", "").lower()
        if any(code.lower() in title for code in currencies) or item["source"] in NEWS_FEEDS:
            value = sum(term in title for term in positive) - sum(
                term in title for term in negative
            )
            relevant.append((item, value))

    total = sum(value for _, value in relevant)
    label = (
        "Mixed / uncertain" if total == 0
        else "Potentially supportive" if total > 0
        else "Potentially adverse"
    )
    return label, total, relevant


# -------------------- Persistence ---------------------------

def persist_signal(symbol, interval, plan, news_result, candles, higher_label, trend_label):
    if engine is None:
        return None

    signal_id = str(uuid.uuid4())
    news_bias, news_score, relevant = news_result
    links = [
        {"source": item["source"], "title": item["title"], "url": item["url"]}
        for item, _ in relevant[:12]
    ]
    db_execute("""
        INSERT INTO signals(
            id,symbol,interval,timeframe,decision,entry,stop,target,risk_usd,
            planned_net_rr,net_rr,news_bias,news_score,news_summary,source_links,
            strategy_version,candles_json,higher_timeframe,higher_trend
        ) VALUES (
            :id,:symbol,:interval,:timeframe,:decision,:entry,:stop,:target,:risk,
            :rr,:rr,:bias,:score,:summary,:links,:version,:candles,:higher,:trend
        )
    """, {
        "id": signal_id,
        "symbol": symbol,
        "interval": interval,
        "timeframe": interval,
        "decision": plan["decision"],
        "entry": plan.get("entry"),
        "stop": plan.get("stop"),
        "target": plan.get("target"),
        "risk": plan.get("estimated_risk_usd", 0),
        "rr": plan.get("planned_net_rr", 0),
        "bias": news_bias,
        "score": news_score,
        "summary": json.dumps([item["title"] for item, _ in relevant[:12]]),
        "links": json.dumps(links),
        "version": APP_VERSION,
        "candles": candles.tail(100).to_json(orient="records", date_format="iso"),
        "higher": higher_label,
        "trend": trend_label,
    })
    return signal_id


def export_backup():
    payload = {}
    for table in ("signals", "paper_trades", "strategy_experiments", "news_cache"):
        payload[table] = (
            db_execute(f"SELECT * FROM {table} ORDER BY 1", fetch=True)
            if engine is not None else []
        )
    return json.dumps(payload, default=str, indent=2)


# -------------------- Application shell ---------------------

if "workspace_open" not in st.session_state:
    st.session_state["workspace_open"] = False
if "last_analysis" not in st.session_state:
    st.session_state["last_analysis"] = None
if "news_items" not in st.session_state:
    st.session_state["news_items"] = []

st.markdown(
    '<div class="editorial-kicker">Independent market research · Paper trading only</div>',
    unsafe_allow_html=True,
)
st.markdown(f"# {APP_NAME}")
st.caption("A considered approach to market structure, evidence and risk.")
st.divider()

if not st.session_state["workspace_open"]:
    left, right = st.columns([1.45, 1], gap="large")
    with left:
        st.markdown('<div class="editorial-kicker">THE MARKET, READ CAREFULLY</div>', unsafe_allow_html=True)
        st.markdown(
            "# Decisions begin with understanding.\n"
            "Not every market deserves a trade."
        )
        st.write(
            "Forex AI Analyst brings price structure, momentum, higher-timeframe context "
            "and public news into one research workspace. It explains what supports a "
            "direction, what conflicts with it, and when the evidence is not sufficient."
        )
        st.markdown(
            '<div class="editorial-note">Analysis first. Risk second. Execution stays with you.</div>',
            unsafe_allow_html=True,
        )
        if st.button("Enter the research workspace →", type="primary"):
            st.session_state["workspace_open"] = True
            st.rerun()
    with right:
        st.markdown("### The discipline")
        st.markdown("**01 / Read** — Examine price, trend and momentum.")
        st.markdown("**02 / Weigh** — Compare evidence and disagreement.")
        st.markdown("**03 / Qualify** — Check the setup against hard risk limits.")
        st.markdown("**04 / Review** — Record paper outcomes and validate changes.")
        st.markdown("---")
        st.metric("Starting paper balance", "$100.00")
        st.metric("Maximum planned risk", "2.00%")
        st.metric("Minimum net R:R", "1 : 2")
        st.caption("No live order execution. No guarantee of trading performance.")
    st.stop()


# -------------------- Workspace controls --------------------

with st.sidebar:
    st.markdown("## Research controls")
    st.caption("Configure the market under review.")
    symbol = st.selectbox("Instrument", SYMBOLS)
    interval = st.selectbox("Entry timeframe", INTERVALS, index=2)
    candle_count = st.select_slider(
        "Candles to request", options=[100, 150, 200, 300, 500], value=200
    )
    balance = st.number_input(
        "Paper balance (USD)", min_value=0.0, value=DEFAULT_BALANCE, step=10.0
    )
    risk_pct = st.number_input(
        "Risk budget (%)", min_value=0.1, max_value=2.0,
        value=DEFAULT_RISK_PCT, step=0.1,
        help="The app enforces a hard maximum of 2%.",
    )
    risk_pct = min(float(risk_pct), 2.0)

    st.markdown("---")
    st.markdown("### Cost assumptions")
    if symbol == "XAU/USD":
        pip_value = 1.0
        default_spread = 3.0
    elif "JPY" in symbol:
        pip_value = 6.7
        default_spread = 1.5
    elif symbol.endswith("/USD"):
        pip_value = 10.0
        default_spread = 1.0
    else:
        pip_value = 7.0
        default_spread = 1.5

    st.caption(
        f"Approximate pip value: ${pip_value:.2f} per pip per standard lot. "
        "This is not a broker quote."
    )
    spread_pips = st.number_input(
        "Spread allowance (pips)", min_value=0.0,
        value=float(default_spread), step=0.1,
    )
    slippage_pips = st.number_input(
        "Slippage allowance (pips)", min_value=0.0, value=0.2, step=0.1,
    )
    st.caption("Simulated broker profile only. Verify actual contract and cost rules separately.")

    if st.button("← Welcome screen", use_container_width=True):
        st.session_state["workspace_open"] = False
        st.rerun()

st.markdown('<div class="editorial-kicker">RESEARCH DESK / 01</div>', unsafe_allow_html=True)
st.title(f"{symbol} — market brief")
st.write(
    "Build a structured view of the market. A directional assessment is not, by itself, "
    "permission to open a paper trade."
)

if engine is not None:
    try:
        init_db()
        st.caption("Storage: PostgreSQL configured.")
    except Exception as exc:
        st.warning(
            f"Database initialization failed ({type(exc).__name__}). "
            "Market analysis may still work, but persistence is not confirmed."
        )
else:
    st.warning(
        "DATABASE_URL is missing. Analysis may work, but records will not persist "
        "across app restarts."
    )

tab_analysis, tab_news, tab_journal, tab_learning = st.tabs([
    "Market analysis", "News & context", "Paper journal", "Strategy review"
])


# -------------------- Market analysis tab -------------------

with tab_analysis:
    run_analysis = st.button("Analyse market", type="primary", use_container_width=True)

    if run_analysis:
        api_key = get_secret("TWELVE_DATA_API_KEY")
        if not api_key:
            st.error(
                "TWELVE_DATA_API_KEY is missing. Add it to Streamlit Secrets; "
                "never commit the API key to your repository."
            )
        else:
            try:
                middle_tf, macro_tf = TIMEFRAME_MAP[interval]
                with st.spinner("Fetching closed candles and evaluating evidence…"):
                    candles = add_indicators(
                        fetch_candles(symbol, interval, candle_count, api_key)
                    )
                    middle = add_indicators(
                        fetch_candles(symbol, middle_tf, candle_count, api_key)
                    )
                    macro = add_indicators(
                        fetch_candles(symbol, macro_tf, candle_count, api_key)
                    )

                    # Preserve UTC handling and exclude the newest possibly-forming bar.
                    candles = candles.iloc[:-1].reset_index(drop=True)
                    middle = middle.iloc[:-1].reset_index(drop=True)
                    macro = macro.iloc[:-1].reset_index(drop=True)

                    if min(len(candles), len(middle), len(macro)) < 55:
                        raise ValueError("Not enough closed candles after excluding the latest bar.")

                    middle_trend = classify_trend(middle)
                    macro_trend = classify_trend(macro)

                    plan = create_trade_plan(
                        candles, symbol, balance, risk_pct, pip_value,
                        MIN_RR, spread_pips, slippage_pips,
                    )

                    required = (
                        "BULLISH" if plan["decision"] == "BUY"
                        else "BEARISH" if plan["decision"] == "SELL"
                        else None
                    )
                    aligned_count = sum(
                        trend == required
                        for trend in (middle_trend, macro_trend)
                    ) if required else 0

                    plan["higher_timeframes"] = {
                        middle_tf: middle_trend,
                        macro_tf: macro_trend,
                    }
                    plan["reasons"].append(
                        f"Higher-timeframe context: {middle_tf}={middle_trend}; "
                        f"{macro_tf}={macro_trend}. "
                        + (
                            f"{aligned_count} of 2 timeframes align with the candidate. "
                            "This is context, not an automatic veto."
                            if required else
                            "Use these trends to interpret the current mixed assessment."
                        )
                    )

                    news_result = score_news(
                        st.session_state.get("news_items", []), symbol
                    )
                    signal_id = persist_signal(
                        symbol, interval, plan, news_result, candles,
                        f"{middle_tf} + {macro_tf}",
                        f"{middle_trend} + {macro_trend}",
                    ) if engine is not None else None

                    st.session_state["last_analysis"] = {
                        "symbol": symbol,
                        "interval": interval,
                        "candles": candles,
                        "plan": plan,
                        "middle_tf": middle_tf,
                        "macro_tf": macro_tf,
                        "middle_trend": middle_trend,
                        "macro_trend": macro_trend,
                        "signal_id": signal_id,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }

            except requests.exceptions.Timeout:
                st.error("Market data request timed out. Try again shortly.")
            except requests.exceptions.RequestException as exc:
                st.error(f"Could not connect to the market data provider ({type(exc).__name__}).")
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(
                    f"Analysis failed ({type(exc).__name__}). "
                    "Check deployment logs without sharing credentials."
                )

    saved = st.session_state.get("last_analysis")

    if saved:
        plan = saved["plan"]
        candles = saved["candles"]
        latest = candles.iloc[-1]
        decision = plan["decision"]

        st.markdown('<div class="editorial-kicker">THE READ / CURRENT ASSESSMENT</div>', unsafe_allow_html=True)
        st.subheader(plan["bias"])
        if decision == "BUY":
            st.success("BUY candidate — paper plan only; no order has been sent.")
        elif decision == "SELL":
            st.error("SELL candidate — paper plan only; no order has been sent.")
        elif decision == "NO TRADE":
            st.warning("Directional evidence exists, but the candidate failed a hard risk check.")
        else:
            st.info("WAIT — the evidence is mixed or insufficient for a directional candidate.")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Evidence score", f"{plan['score']:+.2f}")
        m2.metric("Latest close", format_price(latest["close"], symbol))
        m3.metric("RSI (14)", f"{latest['rsi14']:.1f}")
        m4.metric("Swing structure", plan["structure"])

        st.markdown("### What supports the read")
        if plan["evidence"]:
            st.dataframe(pd.DataFrame(plan["evidence"]), use_container_width=True, hide_index=True)
        else:
            st.write("No strong supporting factors were identified.")

        st.markdown("### What challenges it")
        if plan["conflicts"]:
            st.dataframe(pd.DataFrame(plan["conflicts"]), use_container_width=True, hide_index=True)
        else:
            st.write("No specific caution factor was flagged by this heuristic. That does not mean the setup is risk-free.")

        st.markdown("### Higher-timeframe context")
        h1, h2 = st.columns(2)
        h1.metric(saved["middle_tf"], saved["middle_trend"])
        h2.metric(saved["macro_tf"], saved["macro_trend"])
        st.caption(
            "Higher timeframes contribute context. They do not independently authorize a trade "
            "or automatically veto the evidence-weighted assessment."
        )

        st.markdown("### Analyst notes")
        for reason in plan["reasons"]:
            st.write("— " + reason)

        if decision in ("BUY", "SELL") and plan.get("entry") is not None:
            st.markdown("### Paper plan / estimated only")
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Entry", format_price(plan["entry"], symbol))
            p2.metric("Stop", format_price(plan["stop"], symbol))
            p3.metric("Target", format_price(plan["target"], symbol))
            p4.metric("Estimated net R:R", f"1:{plan['planned_net_rr']:.2f}")

            q1, q2, q3 = st.columns(3)
            q1.metric("Estimated size", f"{plan['lots']:.2f} lots")
            q2.metric("Estimated risk", f"${plan['estimated_risk_usd']:.2f}")
            q3.metric("Risk budget", f"${plan['risk_usd']:.2f}")

            if plan["risk_checks"]:
                st.dataframe(pd.DataFrame(plan["risk_checks"]), use_container_width=True, hide_index=True)

            st.caption(
                "Costs, pip values and contract sizing are approximations. The app does not know "
                "your broker's live spread, commission, swap, margin or execution conditions. "
                "A calculated 1:2 ratio is not a promise of realized 1:2 performance."
            )

        st.markdown("### Price structure")
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=candles["datetime"],
            open=candles["open"], high=candles["high"],
            low=candles["low"], close=candles["close"],
            name=symbol,
        ))
        fig.add_trace(go.Scatter(
            x=candles["datetime"], y=candles["ema20"],
            name="EMA 20", mode="lines",
        ))
        fig.add_trace(go.Scatter(
            x=candles["datetime"], y=candles["ema50"],
            name="EMA 50", mode="lines",
        ))

        x0, x1 = candles["datetime"].iloc[0], candles["datetime"].iloc[-1]
        for zone in plan["demands"]:
            fig.add_shape(
                type="rect", x0=x0, x1=x1,
                y0=zone["low"], y1=zone["high"],
                fillcolor="rgba(46,113,85,.12)", line=dict(width=0),
                layer="below",
            )
        for zone in plan["supplies"]:
            fig.add_shape(
                type="rect", x0=x0, x1=x1,
                y0=zone["low"], y1=zone["high"],
                fillcolor="rgba(168,72,62,.10)", line=dict(width=0),
                layer="below",
            )
        if decision in ("BUY", "SELL") and plan.get("entry") is not None:
            fig.add_hline(y=plan["entry"], line_dash="dot", annotation_text="Entry")
            fig.add_hline(y=plan["stop"], line_dash="dash", annotation_text="Stop")
            fig.add_hline(y=plan["target"], line_dash="dash", annotation_text="Target")

        fig.update_layout(
            height=580,
            template="plotly_white",
            paper_bgcolor="#FBF9F4",
            plot_bgcolor="#FBF9F4",
            font=dict(family="DM Sans", color="#20231F"),
            margin=dict(l=10, r=10, t=35, b=10),
            xaxis_rangeslider_visible=False,
            legend=dict(orientation="h", y=1.02, x=0),
        )
        st.plotly_chart(fig, use_container_width=True)

        with st.expander("Latest closed candles and indicators"):
            cols = ["datetime", "open", "high", "low", "close", "ema20", "ema50", "rsi14", "atr14"]
            st.dataframe(
                candles[cols].tail(30).sort_values("datetime", ascending=False),
                use_container_width=True, hide_index=True,
            )
    else:
        st.markdown("### Before the first assessment")
        st.write(
            "Select the instrument, timeframe and paper-risk assumptions in the sidebar, "
            "then run an analysis. The market assessment will remain visible even when "
            "the right decision is to wait."
        )


# -------------------- News tab -------------------------------

with tab_news:
    st.markdown('<div class="editorial-kicker">THE NEWS / CONTEXT, NOT CERTAINTY</div>', unsafe_allow_html=True)
    st.subheader("Official releases and public headlines")
    st.write(
        "Headline keywords are only a weak screening signal. They do not understand the full "
        "economic context and cannot approve a trade on their own."
    )
    if st.button("Refresh news for selected instrument", use_container_width=True):
        with st.spinner("Reading public feeds…"):
            st.session_state["news_items"] = fetch_news(symbol)
    items = st.session_state.get("news_items", [])
    if items:
        label, total, relevant = score_news(items, symbol)
        st.metric("Headline heuristic", label)
        st.caption(f"Keyword score: {total}. This is not a validated sentiment model.")
        for item, item_score in relevant[:25]:
            st.markdown(f"**[{item['title']}]({item['url']})**")
            st.caption(f"{item['source']} · {item['published'] or 'Publication time unavailable'} · keyword score {item_score}")
            st.write(item.get("summary", "")[:500])
            st.divider()
    else:
        st.info("No news loaded yet. Refresh the public feeds to populate this section.")


# -------------------- Paper journal tab ----------------------

with tab_journal:
    st.markdown('<div class="editorial-kicker">THE JOURNAL / OBSERVE, RECORD, LEARN</div>', unsafe_allow_html=True)
    st.subheader("Paper-trade outcomes")
    st.caption("Records are simulated and manually reviewed. This app never sends broker orders.")

    if engine is None:
        st.warning("Configure DATABASE_URL to use persistent journal records.")
    else:
        try:
            open_trades = db_execute(
                "SELECT * FROM paper_trades WHERE outcome='OPEN' ORDER BY created_at DESC LIMIT 100",
                fetch=True,
            )
            if open_trades:
                st.markdown("### Open records")
                st.dataframe(pd.DataFrame(open_trades), use_container_width=True, hide_index=True)

            signals = db_execute("""
                SELECT id,symbol,decision,entry,stop,target,risk_usd,planned_net_rr,created_at
                FROM signals
                WHERE decision IN ('BUY','SELL')
                  AND entry IS NOT NULL AND stop IS NOT NULL AND target IS NOT NULL
                ORDER BY created_at DESC LIMIT 100
            """, fetch=True)

            with st.expander("Record an outcome"):
                if signals:
                    labels = {
                        f"{r['created_at']} | {r['symbol']} | {r['decision']} | {r['id'][:8]}": r
                        for r in signals
                    }
                    chosen_label = st.selectbox("Signal record", list(labels.keys()))
                    chosen = labels[chosen_label]
                    outcome = st.selectbox(
                        "Outcome", ["WIN", "LOSS", "BREAKEVEN", "CANCELLED"]
                    )
                    exit_price = st.number_input(
                        "Exit price (0 if unknown)", min_value=0.0, value=0.0, format="%.6f"
                    )
                    pnl = st.number_input("Simulated realized P/L (USD)", value=0.0, step=0.1)
                    notes = st.text_area("Notes on execution, market context and costs")
                    if st.button("Save paper outcome"):
                        db_execute("""
                            INSERT INTO paper_trades(
                                id,signal_id,symbol,direction,entry,stop,target,
                                risk_usd,planned_net_rr,net_rr,outcome,exit_price,pnl_usd,notes
                            ) VALUES (
                                :id,:signal,:symbol,:direction,:entry,:stop,:target,
                                :risk,:rr,:rr,:outcome,:exit,:pnl,:notes
                            )
                        """, {
                            "id": str(uuid.uuid4()),
                            "signal": chosen["id"],
                            "symbol": chosen["symbol"],
                            "direction": chosen["decision"],
                            "entry": chosen["entry"],
                            "stop": chosen["stop"],
                            "target": chosen["target"],
                            "risk": chosen["risk_usd"] or 0,
                            "rr": chosen["planned_net_rr"] or 0,
                            "outcome": outcome,
                            "exit": exit_price or None,
                            "pnl": pnl,
                            "notes": notes,
                        })
                        st.success("Outcome saved.")
                        st.rerun()
                else:
                    st.info("No complete BUY/SELL signal records are available yet.")

            trades = db_execute(
                "SELECT * FROM paper_trades ORDER BY created_at DESC LIMIT 500",
                fetch=True,
            )
            if trades:
                closed = [t for t in trades if t["outcome"] in ("WIN", "LOSS", "BREAKEVEN")]
                wins = sum(t["outcome"] == "WIN" for t in closed)
                a, b, c = st.columns(3)
                a.metric("Closed records", len(closed))
                b.metric("Recorded win rate", f"{wins / len(closed) * 100:.1f}%" if closed else "—")
                c.metric("Recorded simulated P/L", f"${sum(float(t['pnl_usd'] or 0) for t in closed):.2f}")
                st.dataframe(pd.DataFrame(trades), use_container_width=True, hide_index=True)

            st.markdown("### Export a logical backup")
            st.write("Download the records as JSON and store a copy somewhere separate from the hosting service.")
            st.download_button(
                "Download JSON backup",
                data=export_backup(),
                file_name=f"forex_analyst_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}Z.json",
                mime="application/json",
                use_container_width=True,
            )
        except Exception as exc:
            st.error(f"Journal unavailable ({type(exc).__name__}). Check server logs securely.")


# -------------------- Strategy review tab --------------------

with tab_learning:
    st.markdown('<div class="editorial-kicker">THE LAB / CHANGE MUST EARN ITS PLACE</div>', unsafe_allow_html=True)
    st.subheader("Guarded strategy experiments")
    st.write(
        "Record a candidate change, validate it on chronologically later unseen data, "
        "compare it with the unchanged baseline, and review drawdown and transaction costs. "
        "This application never auto-approves or deploys a strategy change."
    )

    if engine is None:
        st.warning("Configure DATABASE_URL to retain experiment records.")
    else:
        name = st.text_input("Experiment name", placeholder="Alternative RSI weighting")
        params = st.text_area(
            "Candidate parameters (JSON)",
            value='{"description":"Document the hypothesis and validation method."}',
        )
        baseline = st.number_input("Baseline out-of-sample metric", value=0.0, step=0.1)
        candidate = st.number_input("Candidate metric on the same measure", value=0.0, step=0.1)
        count = st.number_input("Unseen validation trades", min_value=0, value=0, step=1)
        notes = st.text_area("Validation notes, costs, drawdown and known limitations")

        if st.button("Save experiment for review"):
            try:
                json.loads(params)
                db_execute("""
                    INSERT INTO strategy_experiments(
                        id,name,parameters_json,baseline_metric,candidate_metric,
                        validation_count,status,notes
                    ) VALUES (
                        :id,:name,:params,:baseline,:candidate,:count,'PENDING',:notes
                    )
                """, {
                    "id": str(uuid.uuid4()),
                    "name": name.strip() or "Unnamed experiment",
                    "params": params,
                    "baseline": baseline,
                    "candidate": candidate,
                    "count": int(count),
                    "notes": notes,
                })
                st.success("Experiment saved as PENDING. It has not been approved.")
                st.rerun()
            except json.JSONDecodeError:
                st.error("The parameter description must be valid JSON.")
            except Exception as exc:
                st.error(f"Could not save experiment ({type(exc).__name__}).")

        experiments = db_execute(
            "SELECT * FROM strategy_experiments ORDER BY created_at DESC LIMIT 100",
            fetch=True,
        )
        if experiments:
            st.markdown("### Experiment history")
            st.dataframe(pd.DataFrame(experiments), use_container_width=True, hide_index=True)

st.divider()
st.caption(
    f"FOREX / FIELDNOTES · {APP_VERSION} · Research prototype · "
    "UTC candles · PostgreSQL persistence · Paper trading only · No live order execution"
)

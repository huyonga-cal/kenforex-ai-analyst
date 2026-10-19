
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
from sqlalchemy.exc import SQLAlchemyError


# ============================================================
# CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Forex AI Analyst",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

STARTING_BALANCE = 100.0
MAX_RISK_PCT = 2.0
MIN_NET_RR = 2.0
STRATEGY_VERSION = "baseline-v2"
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

HIGHER_TIMEFRAME_MAP = {
    "1min": "5min",
    "5min": "15min",
    "15min": "1h",
    "30min": "1h",
    "1h": "4h",
    "2h": "4h",
    "4h": "1day",
    "1day": "1week",
}

INTERVAL_SECONDS = {
    "1min": 60,
    "5min": 300,
    "15min": 900,
    "30min": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1day": 86400,
    "1week": 604800,
}

NEWS_FEEDS = {
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
    "European Central Bank": "https://www.ecb.europa.eu/rss/press.html",
    "Bank of England": "https://www.bankofengland.co.uk/rss/news",
    "Bank of Japan": "https://www.boj.or.jp/en/rss/whatsnew.xml",
    "US Treasury": "https://home.treasury.gov/news/press-releases/rss",
}


# ============================================================
# VISUAL DESIGN
# ============================================================

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');

:root {
    --canvas: #F7F8F5;
    --surface: #FFFFFF;
    --navy: #172B43;
    --muted: #728094;
    --green: #39765B;
    --green-soft: #EAF3ED;
    --border: #E5E9E5;
}

.stApp {
    background: var(--canvas);
    color: var(--navy);
    font-family: 'DM Sans', sans-serif;
}

[data-testid="stHeader"] {
    background: rgba(247,248,245,.94);
}

.block-container {
    max-width: 1500px;
    padding-top: 1.7rem;
    padding-bottom: 3rem;
}

h1, h2, h3 {
    color: var(--navy) !important;
    font-family: 'Manrope', sans-serif !important;
    letter-spacing: -.035em;
}

h1 { font-size: 2rem !important; font-weight: 800 !important; }
h2 { font-size: 1.4rem !important; font-weight: 750 !important; }
h3 { font-size: 1.05rem !important; font-weight: 700 !important; }

[data-testid="stSidebar"] {
    background: #FFFFFF;
    border-right: 1px solid var(--border);
}

div[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 17px 19px;
    box-shadow: 0 2px 8px rgba(23,43,67,.025);
}

div[data-testid="stMetricLabel"] {
    color: var(--muted);
    font-size: .83rem;
    font-weight: 600;
}

div[data-testid="stMetricValue"] {
    color: var(--navy);
    font-family: 'Manrope', sans-serif;
    font-weight: 800;
}

.stButton > button, .stDownloadButton > button {
    border-radius: 10px;
    min-height: 42px;
    font-weight: 650;
    border: 1px solid var(--border);
}

.stButton > button[kind="primary"] {
    background: var(--navy);
    color: white;
    border-color: var(--navy);
}

.stButton > button[kind="primary"]:hover {
    background: #284664;
    border-color: #284664;
    color: white;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: var(--border);
    border-radius: 16px;
}

[data-testid="stDataFrame"] {
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
}

[data-testid="stAlert"] {
    border-radius: 12px;
}

hr { border-color: var(--border); }

.hero {
    background: linear-gradient(120deg, #FFFFFF 0%, #F0F5F0 100%);
    border: 1px solid #E2E9E2;
    border-radius: 22px;
    padding: 27px 28px;
    margin-bottom: 20px;
}

.eyebrow {
    color: var(--green);
    font-size: .73rem;
    font-weight: 800;
    letter-spacing: .12em;
    text-transform: uppercase;
}

.hero-title {
    color: var(--navy);
    font-family: 'Manrope', sans-serif;
    font-size: 2rem;
    font-weight: 800;
    letter-spacing: -.045em;
    margin-top: 8px;
}

.hero-subtitle {
    color: var(--muted);
    line-height: 1.6;
    margin-top: 8px;
}

.pill {
    display: inline-block;
    background: var(--green-soft);
    color: #2E684C;
    border-radius: 999px;
    padding: 7px 11px;
    margin-top: 14px;
    font-size: .75rem;
    font-weight: 750;
}

.balance-card {
    background: var(--navy);
    color: white;
    border-radius: 18px;
    padding: 23px;
    margin-bottom: 15px;
}

.balance-label {
    color: #D0DCE7;
    font-size: .85rem;
}

.balance-value {
    color: white;
    font-family: 'Manrope', sans-serif;
    font-size: 2.35rem;
    font-weight: 800;
    letter-spacing: -.045em;
    margin: 8px 0;
}

.balance-note {
    color: #BFD8C8;
    font-size: .82rem;
}

.muted {
    color: var(--muted);
    font-size: .88rem;
    line-height: 1.6;
}

@media(max-width:700px) {
    .block-container { padding: 1rem .8rem 2rem; }
    .hero { padding: 21px 17px; }
    .hero-title { font-size: 1.65rem; }
    .balance-value { font-size: 1.9rem; }
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL", "")

try:
    if not DATABASE_URL and "DATABASE_URL" in st.secrets:
        DATABASE_URL = st.secrets["DATABASE_URL"]
except Exception:
    pass

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://", "postgresql+psycopg://", 1
    )
elif (
    DATABASE_URL.startswith("postgresql://")
    and "+psycopg" not in DATABASE_URL
):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

engine = (
    create_engine(DATABASE_URL, pool_pre_ping=True)
    if DATABASE_URL else None
)


def init_db():
    if engine is None:
        return False

    statements = [
        """
        CREATE TABLE IF NOT EXISTS signals (
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
            strategy_version TEXT NOT NULL DEFAULT 'baseline-v2',
            candles_json TEXT,
            higher_timeframe TEXT,
            higher_trend TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
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
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS strategy_experiments (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            name TEXT NOT NULL,
            parameters_json TEXT NOT NULL,
            baseline_metric DOUBLE PRECISION,
            candidate_metric DOUBLE PRECISION,
            validation_count INTEGER,
            status TEXT NOT NULL DEFAULT 'PENDING',
            notes TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS news_cache (
            url TEXT PRIMARY KEY,
            published_at TEXT,
            source TEXT,
            title TEXT NOT NULL,
            summary TEXT,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ]

    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))

        conn.execute(text(
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS higher_timeframe TEXT"
        ))
        conn.execute(text(
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS higher_trend TEXT"
        ))

        # A signal may have at most one paper-trade record.
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            uq_paper_trades_signal_id
            ON paper_trades(signal_id)
            WHERE signal_id IS NOT NULL
        """))

    return True


def db_execute(sql, params=None, fetch=False):
    if engine is None:
        return [] if fetch else False

    with engine.begin() as conn:
        result = conn.execute(text(sql), params or {})
        if fetch:
            return [dict(row._mapping) for row in result]

    return True


def paper_balance():
    """Balance = starting balance + recorded P&L for completed trades."""
    if engine is None:
        return STARTING_BALANCE

    rows = db_execute("""
        SELECT COALESCE(SUM(pnl_usd), 0) AS total_pnl
        FROM paper_trades
        WHERE outcome IN ('WIN','LOSS','BREAKEVEN')
    """, fetch=True)

    total_pnl = float(rows[0]["total_pnl"] or 0) if rows else 0.0
    return max(0.0, STARTING_BALANCE + total_pnl)


def save_backup():
    payload = {}

    for table in (
        "signals", "paper_trades",
        "strategy_experiments", "news_cache",
    ):
        payload[table] = (
            db_execute(f"SELECT * FROM {table} ORDER BY 1", fetch=True)
            if engine is not None else []
        )

    return json.dumps(payload, default=str, indent=2)


# ============================================================
# NEWS INTELLIGENCE
# ============================================================

def fetch_news(symbol):
    items = []

    for source, url in NEWS_FEEDS.items():
        try:
            parsed = feedparser.parse(
                url,
                request_headers={"User-Agent": "ForexAIAnalyst/2.0"},
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
                        "published": str(
                            entry.get("published", entry.get("updated", ""))
                        ),
                    })
        except Exception:
            continue

    try:
        pair = symbol.replace("/", " ")
        query = quote(f'"{pair}" forex OR currency')
        url = (
            "https://api.gdeltproject.org/api/v2/doc/doc"
            f"?query={query}&mode=ArtList&format=json"
            "&maxrecords=20&sort=DateDesc"
        )

        response = requests.get(url, timeout=12)
        response.raise_for_status()

        for item in response.json().get("articles", []):
            items.append({
                "source": item.get("domain", "GDELT"),
                "title": item.get("title", ""),
                "summary": item.get("seendate", ""),
                "url": item.get("url", ""),
                "published": item.get("seendate", ""),
            })
    except Exception:
        pass

    unique = {}
    for item in items:
        if item["url"] and item["title"]:
            unique[item["url"]] = item

    items = list(unique.values())[:80]

    if engine is not None:
        for item in items:
            try:
                db_execute("""
                    INSERT INTO news_cache
                    (url,published_at,source,title,summary)
                    VALUES
                    (:url,:published,:source,:title,:summary)
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
    """Transparent keyword heuristic, not verified financial sentiment."""
    currencies = [x for x in symbol.split("/") if x]

    positive = {
        "hawkish", "rate hike", "raises rates",
        "strong growth", "beats forecast",
        "tightening", "surplus",
    }
    negative = {
        "dovish", "rate cut", "cuts rates",
        "recession", "misses forecast",
        "easing", "deficit", "unemployment rises",
    }

    relevant = []

    for item in items:
        title = item["title"].lower()

        if (
            any(c.lower() in title for c in currencies)
            or item["source"] in NEWS_FEEDS
        ):
            score = (
                sum(term in title for term in positive)
                - sum(term in title for term in negative)
            )
            relevant.append((item, score))

    total = sum(score for _, score in relevant)
    bias = (
        "Mixed / uncertain" if total == 0
        else "Potentially supportive" if total > 0
        else "Potentially adverse"
    )

    return bias, total, relevant


# ============================================================
# MARKET DATA AND INDICATORS
# ============================================================

@st.cache_data(ttl=60, show_spinner=False)
def fetch_candles(symbol, interval, outputsize, api_key):
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": api_key,
        "format": "JSON",
        "timezone": "UTC",
        "order": "desc",
    }

    response = requests.get(API_URL, params=params, timeout=25)
    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, dict) and payload.get("status") == "error":
        raise ValueError(
            payload.get("message", "Twelve Data returned an error.")
        )

    values = payload.get("values") if isinstance(payload, dict) else None

    if not values:
        raise ValueError(
            "No candles returned. Check API limits, symbol and interval."
        )

    df = pd.DataFrame(values)
    required = ["datetime", "open", "high", "low", "close"]

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError("Missing candle columns: " + ", ".join(missing))

    df["datetime"] = pd.to_datetime(
        df["datetime"], errors="coerce", utc=True
    )

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = (
        df.dropna(subset=required)
        .sort_values("datetime")
        .drop_duplicates(subset=["datetime"], keep="last")
        .reset_index(drop=True)
    )

    # Use closed candles only. All timestamps remain UTC.
    duration = INTERVAL_SECONDS.get(interval)
    if duration:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=duration)
        df = df[df["datetime"] <= cutoff].reset_index(drop=True)

    if len(df) < 55:
        raise ValueError(
            f"Only {len(df)} closed candles are available. "
            "Try a larger candle count or another timeframe."
        )

    return df


def add_indicators(df):
    df = df.copy()

    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1/14, min_periods=14, adjust=False
    ).mean()
    avg_loss = loss.ewm(
        alpha=1/14, min_periods=14, adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi14"] = (100 - 100 / (1 + rs)).fillna(50)

    previous_close = df["close"].shift(1)
    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)

    df["atr14"] = true_range.rolling(14, min_periods=14).mean()
    return df


def higher_timeframe_for(interval):
    return HIGHER_TIMEFRAME_MAP.get(interval, "1week")


def classify_trend(df):
    if df is None or len(df) < 50:
        return "NEUTRAL"

    last = df.iloc[-1]
    close = float(last["close"])
    ema20 = float(last["ema20"])
    ema50 = float(last["ema50"])

    if ema20 > ema50 and close > ema20:
        return "BULLISH"
    if ema20 < ema50 and close < ema20:
        return "BEARISH"

    return "NEUTRAL"


def find_zones(df, lookback=100):
    sample = df.tail(lookback).reset_index(drop=True)

    if len(sample) < 10:
        return [], []

    atr = float(df["atr14"].iloc[-1])

    if not math.isfinite(atr) or atr <= 0:
        atr = float((df["high"] - df["low"]).tail(20).mean())

    if not math.isfinite(atr) or atr <= 0:
        return [], []

    width = atr * 0.35
    supplies, demands = [], []

    # Confirmed pivots only; the newest two candles are not pivot candidates.
    for i in range(2, len(sample) - 2):
        high = float(sample.loc[i, "high"])
        low = float(sample.loc[i, "low"])

        if (
            high >= float(sample.loc[i-1:i+2, "high"].max())
            and high >= float(sample.loc[i-2, "high"])
        ):
            supplies.append({
                "low": high - width,
                "high": high + width,
                "mid": high,
            })

        if (
            low <= float(sample.loc[i-1:i+2, "low"].min())
            and low <= float(sample.loc[i-2, "low"])
        ):
            demands.append({
                "low": low - width,
                "high": low + width,
                "mid": low,
            })

    current = float(df["close"].iloc[-1])

    supplies = sorted(
        [z for z in supplies if z["mid"] >= current - width],
        key=lambda z: abs(z["mid"] - current),
    )[:4]

    demands = sorted(
        [z for z in demands if z["mid"] <= current + width],
        key=lambda z: abs(z["mid"] - current),
    )[:4]

    return supplies, demands


# ============================================================
# TRADE PLAN AND RISK VALIDATION
# ============================================================

def pip_size_for(symbol):
    if symbol == "XAU/USD":
        return 0.01
    if "JPY" in symbol:
        return 0.01
    return 0.0001


def format_price(value, symbol):
    if value is None:
        return "—"
    if "JPY" in symbol:
        return f"{value:.3f}"
    if symbol == "XAU/USD":
        return f"{value:.2f}"
    return f"{value:.5f}"


def create_trade_plan(
    df, symbol, balance, risk_pct, pip_value_per_lot,
    spread_pips, slippage_pips,
):
    last = df.iloc[-1]

    close = float(last["close"])
    ema20 = float(last["ema20"])
    ema50 = float(last["ema50"])
    rsi = float(last["rsi14"])
    atr = float(last["atr14"])

    if not math.isfinite(atr) or atr <= 0:
        atr = float((df["high"] - df["low"]).tail(14).mean())

    supplies, demands = find_zones(df)

    decision = "WAIT"
    reasons = []
    entry = close
    stop = None
    target = None

    bullish = ema20 > ema50 and close > ema20
    bearish = ema20 < ema50 and close < ema20

    near_distance = max(atr * 0.75, close * 0.0001)

    demand = (
        min(demands, key=lambda z: abs(close - z["mid"]))
        if demands else None
    )
    supply = (
        min(supplies, key=lambda z: abs(close - z["mid"]))
        if supplies else None
    )

    near_demand = (
        demand is not None
        and abs(close - demand["mid"]) <= near_distance
    )
    near_supply = (
        supply is not None
        and abs(close - supply["mid"]) <= near_distance
    )

    if bullish:
        reasons.append("EMA trend filter is bullish.")
    elif bearish:
        reasons.append("EMA trend filter is bearish.")
    else:
        reasons.append("EMA trend is mixed.")

    if 50 <= rsi <= 68:
        reasons.append(f"RSI {rsi:.1f} is within the bullish momentum band.")
    elif 32 <= rsi < 50:
        reasons.append(f"RSI {rsi:.1f} is within the bearish momentum band.")
    else:
        reasons.append(f"RSI {rsi:.1f} is outside the selected entry bands.")

    if bullish and 50 <= rsi <= 68 and near_demand:
        decision = "BUY"
        stop = min(demand["low"], close - 0.8 * atr)
        if stop >= entry:
            stop = entry - atr
        reasons.append("Price is near a heuristic demand zone.")

    elif bearish and 32 <= rsi < 50 and near_supply:
        decision = "SELL"
        stop = max(supply["high"], close + 0.8 * atr)
        if stop <= entry:
            stop = entry + atr
        reasons.append("Price is near a heuristic supply zone.")

    else:
        reasons.append(
            "Trend, momentum and zone conditions are not all satisfied."
        )

    result = {
        "decision": decision,
        "reasons": reasons,
        "entry": None,
        "stop": None,
        "target": None,
        "risk_usd": balance * risk_pct / 100,
        "lots": None,
        "units": None,
        "stop_pips": None,
        "target_pips": None,
        "planned_net_rr": None,
        "estimated_risk_usd": None,
        "planned_reward_usd": None,
        "supplies": supplies,
        "demands": demands,
    }

    if decision not in ("BUY", "SELL") or stop is None:
        return result

    # Never perform position sizing using a missing or invalid conversion.
    if (
        not math.isfinite(pip_value_per_lot)
        or pip_value_per_lot <= 0
    ):
        result["decision"] = "NO TRADE"
        result["reasons"].append(
            "A verified positive USD pip value per standard lot is required "
            "before position sizing can be approved."
        )
        return result

    if balance <= 0 or risk_pct <= 0 or risk_pct > MAX_RISK_PCT:
        result["decision"] = "NO TRADE"
        result["reasons"].append("Account balance or risk setting is invalid.")
        return result

    if not math.isfinite(entry) or not math.isfinite(stop):
        result["decision"] = "NO TRADE"
        result["reasons"].append("Entry or stop price is invalid.")
        return result

    pip_size = pip_size_for(symbol)
    stop_distance = abs(entry - stop)
    stop_pips = stop_distance / pip_size
    friction = max(0.0, spread_pips) + max(0.0, slippage_pips)

    if (
        not math.isfinite(stop_pips)
        or stop_pips <= 0
        or not math.isfinite(friction)
    ):
        result["decision"] = "NO TRADE"
        result["reasons"].append("Stop distance or estimated costs are invalid.")
        return result

    risk_budget = balance * min(risk_pct, MAX_RISK_PCT) / 100
    effective_risk_pips = stop_pips + friction
    risk_per_lot = effective_risk_pips * pip_value_per_lot

    if risk_per_lot <= 0:
        result["decision"] = "NO TRADE"
        result["reasons"].append("Risk per lot cannot be calculated.")
        return result

    raw_lots = risk_budget / risk_per_lot

    # Simulated 0.01-lot increments. Never round volume up.
    lots = math.floor((raw_lots + 1e-12) / 0.01) * 0.01
    lots = round(lots, 2)

    if lots < 0.01:
        result["decision"] = "NO TRADE"
        result["reasons"].append(
            f"Minimum 0.01 lot does not fit the ${risk_budget:.2f} risk budget."
        )
        return result

    estimated_risk = effective_risk_pips * pip_value_per_lot * lots

    if estimated_risk > risk_budget + 1e-9:
        result["decision"] = "NO TRADE"
        result["reasons"].append("Position size exceeds the risk budget.")
        return result

    # A gross target must cover 2R plus estimated friction on the exit.
    # The result is still only an estimate, not a guarantee of execution.
    minimum_target_pips = (
        MIN_NET_RR * effective_risk_pips + friction
    )

    original_target_distance = max(
        stop_distance * MIN_NET_RR,
        atr if math.isfinite(atr) and atr > 0 else 0,
    )

    target_distance = max(
        original_target_distance,
        minimum_target_pips * pip_size,
    )

    target = (
        entry + target_distance
        if decision == "BUY"
        else entry - target_distance
    )

    target_pips = target_distance / pip_size
    estimated_reward = (
        max(0.0, target_pips - friction)
        * pip_value_per_lot * lots
    )
    planned_net_rr = (
        estimated_reward / estimated_risk
        if estimated_risk > 0 else 0
    )

    # Strict fail-closed validation. No rounding a failed ratio upward.
    if (
        not math.isfinite(planned_net_rr)
        or planned_net_rr + 1e-9 < MIN_NET_RR
    ):
        result["decision"] = "NO TRADE"
        result["reasons"].append(
            "Rejected: estimated net reward-to-risk is below 1:2."
        )
        return result

    result.update({
        "entry": entry,
        "stop": stop,
        "target": target,
        "lots": lots,
        "units": lots * (100 if symbol == "XAU/USD" else 100000),
        "pip_size": pip_size,
        "pip_value_per_lot": pip_value_per_lot,
        "stop_pips": stop_pips,
        "target_pips": target_pips,
        "friction_pips": friction,
        "estimated_risk_usd": estimated_risk,
        "planned_reward_usd": estimated_reward,
        "planned_net_rr": planned_net_rr,
    })

    result["reasons"].append(
        "Risk sizing and estimated net reward-to-risk checks passed."
    )

    return result


def persist_signal(symbol, interval, plan, news, candles, higher_tf, trend):
    if engine is None:
        return None

    signal_id = str(uuid.uuid4())
    bias, score, relevant = news

    links = [
        {
            "source": item["source"],
            "title": item["title"],
            "url": item["url"],
        }
        for item, _ in relevant[:12]
    ]

    db_execute("""
        INSERT INTO signals (
            id,symbol,interval,decision,entry,stop,target,
            risk_usd,planned_net_rr,news_bias,news_score,
            news_summary,source_links,strategy_version,candles_json,
            higher_timeframe,higher_trend
        )
        VALUES (
            :id,:symbol,:interval,:decision,:entry,:stop,:target,
            :risk,:rr,:bias,:score,:summary,:links,:version,:candles,
            :higher_tf,:trend
        )
    """, {
        "id": signal_id,
        "symbol": symbol,
        "interval": interval,
        "decision": plan["decision"],
        "entry": plan.get("entry"),
        "stop": plan.get("stop"),
        "target": plan.get("target"),
        "risk": plan.get("estimated_risk_usd") or plan["risk_usd"],
        "rr": plan.get("planned_net_rr") or 0,
        "bias": bias,
        "score": score,
        "summary": json.dumps([x[0]["title"] for x in relevant[:12]]),
        "links": json.dumps(links),
        "version": STRATEGY_VERSION,
        "candles": candles.tail(100).to_json(
            orient="records", date_format="iso"
        ),
        "higher_tf": higher_tf,
        "trend": trend,
    })

    return signal_id


# ============================================================
# HEADER AND WORKSPACE SETTINGS
# ============================================================

st.markdown("""
<div class="hero">
    <div class="eyebrow">Your market intelligence workspace</div>
    <div class="hero-title">Forex AI Analyst</div>
    <div class="hero-subtitle">
        Clear market analysis. Disciplined risk controls.
        Evidence-led paper trading.
    </div>
    <span class="pill">● PAPER MODE · LIVE ORDERS DISABLED</span>
</div>
""", unsafe_allow_html=True)

now_utc = datetime.now(timezone.utc)

if now_utc.weekday() == 5 or (
    now_utc.weekday() == 6 and now_utc.hour < 21
) or (
    now_utc.weekday() == 4 and now_utc.hour >= 21
):
    st.warning(
        "Forex market may be closed at this UTC time. "
        "Instrument and broker schedules may differ."
    )
else:
    st.info(
        f"UTC reference time: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}. "
        "Broker and instrument hours may differ."
    )

st.warning(
    "PAPER TRADING ONLY. No broker orders are sent. Signals are heuristic, "
    "not financial advice. A calculated risk limit does not guarantee the "
    "actual loss will remain within that amount."
)

with st.sidebar:
    st.markdown("## Workspace settings")

    symbol = st.selectbox("Instrument", SYMBOLS, index=0)
    interval = st.selectbox("Entry timeframe", INTERVALS, index=2)
    candle_count = st.select_slider(
        "Historical candles",
        options=[100, 200, 300, 500],
        value=200,
    )

    st.divider()
    st.markdown("### Risk controls")

    risk_pct = st.number_input(
        "Risk per trade (%)",
        min_value=0.1,
        max_value=MAX_RISK_PCT,
        value=2.0,
        step=0.1,
    )

    st.caption("Hard maximum: 2% of the calculated paper balance.")

    st.markdown("### Cost assumptions")

    pip_size = pip_size_for(symbol)

    if symbol == "XAU/USD":
        default_pip_value = 1.0
        default_spread = 3.0
    elif symbol.endswith("/USD"):
        default_pip_value = 10.0
        default_spread = 1.0
    else:
        # No silent default for quote currencies that require conversion.
        default_pip_value = 0.0
        default_spread = 1.5

    pip_value_per_lot = st.number_input(
        "Verified pip value (USD / standard lot)",
        min_value=0.0,
        value=default_pip_value,
        step=0.1,
        help=(
            "Confirm this value for your exact broker symbol and account "
            "currency. For non-USD quote currencies, enter a verified "
            "converted value. Zero disables position sizing."
        ),
    )

    spread_pips = st.number_input(
        "Estimated spread (pips)",
        min_value=0.0,
        value=default_spread,
        step=0.1,
    )

    slippage_pips = st.number_input(
        "Slippage allowance (pips)",
        min_value=0.0,
        value=0.2,
        step=0.1,
    )

    st.caption(
        "The Exness Standard profile is a simulation assumption, not a live "
        "broker connection. Confirm lot sizes, contract specifications, "
        "spreads and pip values in your own demo terminal."
    )

# Database initialization and account balance.
if engine is not None:
    try:
        init_db()
        st.sidebar.success("PostgreSQL connected")
        balance = paper_balance()
    except Exception as exc:
        balance = STARTING_BALANCE
        st.sidebar.error(f"Database initialization failed: {exc}")
else:
    balance = STARTING_BALANCE
    st.sidebar.warning(
        "DATABASE_URL is missing. Persistent journal and account history "
        "are unavailable until PostgreSQL is configured."
    )

# Account overview.
st.markdown("## Account overview")

st.markdown(f"""
<div class="balance-card">
    <div class="balance-label">Paper account balance</div>
    <div class="balance-value">${balance:,.2f}</div>
    <div class="balance-note">
        Starting balance: $100.00 · No real funds connected
    </div>
</div>
""", unsafe_allow_html=True)

k1, k2, k3 = st.columns(3)

k1.metric(
    "Maximum risk per trade",
    f"${balance * MAX_RISK_PCT / 100:.2f}",
    "2% hard ceiling",
)

k2.metric(
    "Minimum net reward / risk",
    "1 : 2",
    "After estimated costs",
)

k3.metric(
    "Execution mode",
    "Paper only",
    "No live orders",
)

st.markdown(
    '<div class="muted">Account balance includes recorded completed-trade '
    'P&L only when PostgreSQL is connected. Unrecorded or unrealized P&L '
    'is not included.</div>',
    unsafe_allow_html=True,
)


# ============================================================
# NEWS SECTION
# ============================================================

st.markdown("## News & market context")

if st.button("Refresh official and public news", use_container_width=True):
    with st.spinner("Reading official releases and public headlines..."):
        st.session_state["news_items"] = fetch_news(symbol)

news_items = st.session_state.get("news_items", [])

if news_items:
    news_result = score_news(news_items, symbol)

    st.caption(
        f"Headline keyword heuristic: {news_result[0]} "
        f"(score {news_result[1]}). This is not verified sentiment."
    )

    for item, _ in news_result[2][:8]:
        st.markdown(
            f"- [{item['title']}]({item['url']}) — "
            f"{item['source']} · "
            f"{item['published'] or 'Publication time unavailable'}"
        )
else:
    news_result = ("No current news loaded", 0, [])
    st.info(
        "Refresh news to load official RSS releases and public headlines. "
        "News may be delayed or unavailable."
    )


# ============================================================
# MARKET ANALYSIS
# ============================================================

st.markdown("## Market analysis")

if st.button("Analyze market", type="primary", use_container_width=True):
    try:
        api_key = os.getenv("TWELVE_DATA_API_KEY", "")

        try:
            if not api_key and "TWELVE_DATA_API_KEY" in st.secrets:
                api_key = st.secrets["TWELVE_DATA_API_KEY"]
        except Exception:
            pass

        if not api_key:
            st.error(
                "TWELVE_DATA_API_KEY is missing. Add it in Streamlit "
                "Cloud → App settings → Secrets. Never commit the key "
                "to source control."
            )
            st.stop()

        higher_interval = higher_timeframe_for(interval)

        with st.spinner(
            f"Loading closed {interval} and {higher_interval} candles..."
        ):
            candles = add_indicators(
                fetch_candles(
                    symbol, interval, int(candle_count), api_key
                )
            )

            higher_candles = add_indicators(
                fetch_candles(
                    symbol, higher_interval, int(candle_count), api_key
                )
            )

            higher_trend = classify_trend(higher_candles)

            plan = create_trade_plan(
                candles=candles,
                symbol=symbol,
                balance=balance,
                risk_pct=float(risk_pct),
                pip_value_per_lot=float(pip_value_per_lot),
                spread_pips=float(spread_pips),
                slippage_pips=float(slippage_pips),
            )

            # Higher-timeframe confirmation is a hard directional gate.
            if plan["decision"] in ("BUY", "SELL"):
                required = (
                    "BULLISH" if plan["decision"] == "BUY" else "BEARISH"
                )

                if higher_trend != required:
                    rejected = plan["decision"]
                    plan["decision"] = "NO TRADE"
                    plan["reasons"].append(
                        f"Higher-timeframe confirmation failed: "
                        f"{higher_interval} is {higher_trend}; "
                        f"{rejected} requires {required}."
                    )
                    plan["entry"] = None
                    plan["stop"] = None
                    plan["target"] = None
                    plan["lots"] = None
                    plan["units"] = None

            signal_id = persist_signal(
                symbol,
                interval,
                plan,
                news_result,
                candles,
                higher_interval,
                higher_trend,
            ) if engine is not None else None

            st.session_state["latest_plan"] = plan
            st.session_state["latest_candles"] = candles
            st.session_state["latest_symbol"] = symbol
            st.session_state["latest_interval"] = interval
            st.session_state["latest_higher_interval"] = higher_interval
            st.session_state["latest_higher_trend"] = higher_trend
            st.session_state["latest_signal_id"] = signal_id
            st.session_state["latest_news_result"] = news_result

    except requests.exceptions.Timeout:
        st.error("Market-data request timed out. Try again.")
    except requests.exceptions.HTTPError as exc:
        st.error(f"HTTP error requesting market data: {exc}")
    except requests.exceptions.RequestException as exc:
        st.error(f"Could not connect to Twelve Data: {exc}")
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Analysis failed: {exc}")


# Render the most recent analysis on every Streamlit rerun.
if "latest_plan" in st.session_state:
    plan = st.session_state["latest_plan"]
    candles = st.session_state["latest_candles"]
    analyzed_symbol = st.session_state["latest_symbol"]
    analyzed_interval = st.session_state["latest_interval"]
    higher_interval = st.session_state["latest_higher_interval"]
    higher_trend = st.session_state["latest_higher_trend"]

    st.markdown("### Trend confirmation")

    h1, h2, h3 = st.columns(3)
    h1.metric("Entry timeframe", analyzed_interval)
    h2.metric("Confirmation timeframe", higher_interval)
    h3.metric("Higher-timeframe trend", higher_trend)

    latest = candles.iloc[-1]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latest close", format_price(float(latest["close"]), analyzed_symbol))
    c2.metric("EMA 20", format_price(float(latest["ema20"]), analyzed_symbol))
    c3.metric("EMA 50", format_price(float(latest["ema50"]), analyzed_symbol))
    c4.metric("RSI (14)", f"{float(latest['rsi14']):.1f}")

    st.markdown("### Trade assessment")

    decision = plan["decision"]

    if decision == "BUY":
        st.success("BUY candidate · Paper trading only")
    elif decision == "SELL":
        st.error("SELL candidate · Paper trading only")
    else:
        st.info("WAIT / NO TRADE · No approved entry")

    for reason in plan["reasons"]:
        st.markdown(f"- {reason}")

    if decision in ("BUY", "SELL") and plan.get("entry") is not None:
        a, b, c, d = st.columns(4)

        a.metric("Indicative entry", format_price(plan["entry"], analyzed_symbol))
        b.metric("Stop-loss", format_price(plan["stop"], analyzed_symbol))
        c.metric("Take-profit", format_price(plan["target"], analyzed_symbol))
        d.metric(
            "Estimated net R:R",
            f"1:{plan['planned_net_rr']:.2f}",
        )

        a, b, c = st.columns(3)

        a.metric("Position size", f"{plan['lots']:.2f} lots")
        b.metric("Estimated risk", f"${plan['estimated_risk_usd']:.2f}")
        c.metric("Estimated reward", f"${plan['planned_reward_usd']:.2f}")

        st.caption(
            f"Approximate units: {plan['units']:,.0f}. "
            "The calculation assumes the pip value, spread and slippage "
            "you entered. Gaps, execution differences, swaps, commissions "
            "and conversion-rate changes may cause actual results to differ."
        )

        # Only valid, risk-approved directional candidates can be journaled.
        signal_id = st.session_state.get("latest_signal_id")

        if engine is not None and signal_id:
            already_recorded = db_execute(
                "SELECT id FROM paper_trades WHERE signal_id=:signal",
                {"signal": signal_id},
                fetch=True,
            )

            if already_recorded:
                st.caption("A paper-trade record already exists for this signal.")
            else:
                with st.expander("Record this as a paper trade"):
                    st.caption(
                        "This records a paper-trade entry in PostgreSQL. "
                        "It does not place a broker order."
                    )

                    if st.button(
                        "Create open paper-trade record",
                        key=f"open_{signal_id}",
                    ):
                        try:
                            db_execute("""
                                INSERT INTO paper_trades (
                                    id,signal_id,symbol,direction,entry,
                                    stop,target,risk_usd,planned_net_rr,outcome
                                )
                                VALUES (
                                    :id,:signal,:symbol,:direction,:entry,
                                    :stop,:target,:risk,:rr,'OPEN'
                                )
                                ON CONFLICT DO NOTHING
                            """, {
                                "id": str(uuid.uuid4()),
                                "signal": signal_id,
                                "symbol": analyzed_symbol,
                                "direction": decision,
                                "entry": plan["entry"],
                                "stop": plan["stop"],
                                "target": plan["target"],
                                "risk": plan["estimated_risk_usd"],
                                "rr": plan["planned_net_rr"],
                            })
                            st.success("Open paper-trade record saved.")
                            st.rerun()
                        except SQLAlchemyError as exc:
                            st.error(f"Could not save trade: {exc}")

    # Chart
    st.markdown("### Price action & market structure")

    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=candles["datetime"],
        open=candles["open"],
        high=candles["high"],
        low=candles["low"],
        close=candles["close"],
        name=analyzed_symbol,
        increasing_line_color="#39765B",
        decreasing_line_color="#C16F73",
    ))

    fig.add_trace(go.Scatter(
        x=candles["datetime"],
        y=candles["ema20"],
        mode="lines",
        name="EMA 20",
        line=dict(color="#39765B", width=1.5),
    ))

    fig.add_trace(go.Scatter(
        x=candles["datetime"],
        y=candles["ema50"],
        mode="lines",
        name="EMA 50",
        line=dict(color="#71839A", width=1.5),
    ))

    x_start = candles["datetime"].iloc[0]
    x_end = candles["datetime"].iloc[-1]

    for zone in plan["demands"]:
        fig.add_shape(
            type="rect",
            xref="x", yref="y",
            x0=x_start, x1=x_end,
            y0=zone["low"], y1=zone["high"],
            fillcolor="rgba(57,118,91,0.10)",
            line=dict(width=0),
            layer="below",
        )

    for zone in plan["supplies"]:
        fig.add_shape(
            type="rect",
            xref="x", yref="y",
            x0=x_start, x1=x_end,
            y0=zone["low"], y1=zone["high"],
            fillcolor="rgba(193,111,115,0.10)",
            line=dict(width=0),
            layer="below",
        )

    if decision in ("BUY", "SELL"):
        fig.add_hline(
            y=plan["entry"],
            line_dash="dot",
            annotation_text="Entry",
        )
        fig.add_hline(
            y=plan["stop"],
            line_dash="dash",
            annotation_text="Stop-loss",
        )
        fig.add_hline(
            y=plan["target"],
            line_dash="dash",
            annotation_text="Take-profit",
        )

    fig.update_layout(
        height=560,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="DM Sans, sans-serif", color="#172B43"),
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        ),
    )

    st.plotly_chart(fig, use_container_width=True)

    zone1, zone2 = st.columns(2)

    with zone1:
        st.markdown("**Estimated demand zones**")
        if plan["demands"]:
            st.dataframe(pd.DataFrame([
                {
                    "Zone low": format_price(z["low"], analyzed_symbol),
                    "Zone high": format_price(z["high"], analyzed_symbol),
                }
                for z in plan["demands"]
            ]), use_container_width=True, hide_index=True)
        else:
            st.write("No demand zones detected.")

    with zone2:
        st.markdown("**Estimated supply zones**")
        if plan["supplies"]:
            st.dataframe(pd.DataFrame([
                {
                    "Zone low": format_price(z["low"], analyzed_symbol),
                    "Zone high": format_price(z["high"], analyzed_symbol),
                }
                for z in plan["supplies"]
            ]), use_container_width=True, hide_index=True)
        else:
            st.write("No supply zones detected.")

    with st.expander("View latest candles and indicators"):
        show_cols = [
            "datetime", "open", "high", "low", "close",
            "ema20", "ema50", "rsi14", "atr14",
        ]
        st.dataframe(
            candles[show_cols].tail(30).sort_values(
                "datetime", ascending=False
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.caption(
        "The strategy uses EMA trend, RSI and heuristic supply/demand zones. "
        "It has not been demonstrated to be profitable. The 1:2 rule is a "
        "calculation based on estimated costs, not a guarantee of the realized result."
    )

else:
    st.info(
        "Choose an instrument and timeframe, then click Analyze market. "
        "The application checks a higher timeframe before accepting a candidate."
    )


# ============================================================
# JOURNAL, LEARNING AND BACKUPS
# ============================================================

st.divider()
st.markdown("## Journal & strategy lab")

st.caption(
    "Review recorded paper trades, inspect results and document strategy "
    "experiments. No strategy change is deployed automatically."
)

if engine is not None:
    try:
        open_trades = db_execute("""
            SELECT * FROM paper_trades
            WHERE outcome='OPEN'
            ORDER BY created_at DESC
            LIMIT 200
        """, fetch=True)

        st.markdown("### Open paper trades")

        if open_trades:
            st.dataframe(
                pd.DataFrame(open_trades),
                use_container_width=True,
                hide_index=True,
            )

            open_labels = {
                f"{r['symbol']} | {r['direction']} | {str(r['id'])[:8]}": r
                for r in open_trades
            }

            with st.expander("Close a paper-trade record"):
                chosen_label = st.selectbox(
                    "Open trade",
                    list(open_labels.keys()),
                )
                chosen_trade = open_labels[chosen_label]

                close_outcome = st.selectbox(
                    "Outcome",
                    ["WIN", "LOSS", "BREAKEVEN"],
                )

                exit_price = st.number_input(
                    "Exit price",
                    min_value=0.0,
                    value=0.0,
                    format="%.6f",
                )

                pnl = st.number_input(
                    "Realized simulated P&L (USD)",
                    value=0.0,
                    step=0.1,
                )

                close_notes = st.text_area("Trade review notes")

                if st.button("Save closed-trade result"):
                    valid = (
                        (close_outcome == "WIN" and pnl > 0)
                        or (close_outcome == "LOSS" and pnl < 0)
                        or (close_outcome == "BREAKEVEN" and abs(pnl) < 1e-9)
                    )

                    if not valid:
                        st.error(
                            "Outcome and P&L disagree. WIN requires positive "
                            "P&L, LOSS negative P&L, and BREAKEVEN zero P&L."
                        )
                    elif exit_price <= 0:
                        st.error("Enter a valid exit price.")
                    else:
                        try:
                            db_execute("""
                                UPDATE paper_trades
                                SET outcome=:outcome,
                                    exit_price=:exit,
                                    pnl_usd=:pnl,
                                    notes=:notes
                                WHERE id=:id AND outcome='OPEN'
                            """, {
                                "outcome": close_outcome,
                                "exit": exit_price,
                                "pnl": pnl,
                                "notes": close_notes,
                                "id": chosen_trade["id"],
                            })

                            st.success("Trade result saved.")
                            st.rerun()
                        except SQLAlchemyError as exc:
                            st.error(f"Could not close trade: {exc}")
        else:
            st.info("No open paper-trade records.")

        trades = db_execute("""
            SELECT * FROM paper_trades
            ORDER BY created_at DESC
            LIMIT 500
        """, fetch=True)

        st.markdown("### Performance summary")

        closed = [
            trade for trade in trades
            if trade["outcome"] in ("WIN", "LOSS", "BREAKEVEN")
        ]

        total_pnl = sum(
            float(trade["pnl_usd"] or 0)
            for trade in closed
        )

        wins = sum(
            trade["outcome"] == "WIN"
            for trade in closed
        )

        losses = sum(
            trade["outcome"] == "LOSS"
            for trade in closed
        )

        m1, m2, m3, m4 = st.columns(4)

        m1.metric("Completed trades", len(closed))
        m2.metric(
            "Recorded win rate",
            f"{100 * wins / len(closed):.1f}%" if closed else "—",
        )
        m3.metric("Recorded losses", losses)
        m4.metric("Recorded net P&L", f"${total_pnl:.2f}")

        st.caption(
            "These are manually recorded paper outcomes, not independently "
            "verified broker fills or a validated backtest."
        )

        if trades:
            st.dataframe(
                pd.DataFrame(trades),
                use_container_width=True,
                hide_index=True,
            )

        # Candidate strategy experiments remain pending until reviewed.
        st.markdown("### Strategy experiment review")

        st.write(
            "Compare candidate changes using chronologically later, unseen "
            "data and the same baseline metric. A better single metric does "
            "not establish that a strategy is reliable."
        )

        experiment_name = st.text_input(
            "Experiment name",
            placeholder="e.g. Alternative RSI entry band",
        )

        params_json = st.text_area(
            "Proposed parameters (JSON)",
            value='{"description":"Document a candidate change."}',
        )

        baseline_metric = st.number_input(
            "Baseline out-of-sample metric",
            value=0.0,
            step=0.1,
        )

        candidate_metric = st.number_input(
            "Candidate out-of-sample metric",
            value=0.0,
            step=0.1,
        )

        validation_count = st.number_input(
            "Unseen validation trades",
            min_value=0,
            value=0,
            step=1,
        )

        if st.button("Save experiment for review"):
            try:
                json.loads(params_json)

                db_execute("""
                    INSERT INTO strategy_experiments (
                        id,name,parameters_json,baseline_metric,
                        candidate_metric,validation_count,status,notes
                    )
                    VALUES (
                        :id,:name,:params,:base,:candidate,:count,
                        'PENDING',:notes
                    )
                """, {
                    "id": str(uuid.uuid4()),
                    "name": experiment_name or "Unnamed experiment",
                    "params": params_json,
                    "base": baseline_metric,
                    "candidate": candidate_metric,
                    "count": int(validation_count),
                    "notes": (
                        "Pending review. No strategy parameters changed."
                    ),
                })

                st.success(
                    "Experiment saved as PENDING. No automatic strategy changes."
                )
                st.rerun()

            except (ValueError, SQLAlchemyError) as exc:
                st.error(f"Could not save experiment: {exc}")

        experiments = db_execute("""
            SELECT * FROM strategy_experiments
            ORDER BY created_at DESC
            LIMIT 100
        """, fetch=True)

        if experiments:
            st.dataframe(
                pd.DataFrame(experiments),
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("### Data & backups")

        st.download_button(
            "Download JSON backup",
            data=save_backup(),
            file_name=(
                "forex_ai_backup_"
                + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                + "Z.json"
            ),
            mime="application/json",
            use_container_width=True,
        )

        st.caption(
            "This is a manual export. Configure scheduled database backups "
            "to storage outside the application for disaster recovery."
        )

    except Exception as exc:
        st.error(f"Journal or learning section failed: {exc}")

else:
    st.warning(
        "PostgreSQL is not configured. Trade history, account balance history, "
        "experiments and backups cannot persist between app sessions. Set "
        "DATABASE_URL before relying on these features."
    )

st.divider()
st.caption(
    "Forex AI Analyst · Educational paper-trading prototype · "
    "No live order execution · UTC timestamps"
)

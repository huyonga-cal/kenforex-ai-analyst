
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


# =========================================================
# 1. CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Forex AI Analyst",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

STARTING_BALANCE = 100.00
MAX_RISK_PERCENT = 2.0
MIN_NET_RR = 2.0
STRATEGY_VERSION = "baseline-v3"

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"

SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "NZD/USD", "USD/CAD", "EUR/GBP",
    "EUR/JPY", "GBP/JPY", "XAU/USD",
]

TIMEFRAMES = [
    "1min", "5min", "15min", "30min",
    "1h", "2h", "4h", "1day",
]

HIGHER_TF = {
    "1min": "5min",
    "5min": "15min",
    "15min": "1h",
    "30min": "1h",
    "1h": "4h",
    "2h": "4h",
    "4h": "1day",
    "1day": "1week",
}

TF_SECONDS = {
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


# =========================================================
# 2. UI DESIGN SYSTEM
# =========================================================

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');

:root {
    --bg: #F5F7F5;
    --surface: #FFFFFF;
    --navy: #172B43;
    --navy2: #243E59;
    --green: #38765A;
    --green-bg: #E9F3EC;
    --red: #B9575D;
    --red-bg: #FAEEEE;
    --muted: #788596;
    --border: #E4E9E5;
}

.stApp {
    background: var(--bg);
    color: var(--navy);
    font-family: 'DM Sans', sans-serif;
}

[data-testid="stHeader"] {
    background: rgba(245,247,245,.94);
}

.block-container {
    max-width: 1550px;
    padding-top: 1.35rem;
    padding-bottom: 3rem;
}

h1, h2, h3, h4 {
    font-family: 'Manrope', sans-serif !important;
    color: var(--navy) !important;
    letter-spacing: -.035em;
}

h1 { font-size: 2rem !important; font-weight: 800 !important; }
h2 { font-size: 1.42rem !important; font-weight: 750 !important; }
h3 { font-size: 1.08rem !important; font-weight: 750 !important; }

p, li, label {
    color: var(--navy);
}

[data-testid="stSidebar"] {
    background: #FFFFFF;
    border-right: 1px solid var(--border);
}

[data-testid="stSidebar"] .block-container {
    padding-top: 1.5rem;
}

div[data-testid="stMetric"] {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 15px;
    padding: 15px 17px;
    box-shadow: 0 3px 12px rgba(23,43,67,.025);
}

[data-testid="stMetricLabel"] {
    color: var(--muted);
    font-size: .82rem;
    font-weight: 600;
}

[data-testid="stMetricValue"] {
    font-family: 'Manrope', sans-serif;
    font-weight: 800;
    color: var(--navy);
}

.stButton > button, .stDownloadButton > button {
    border-radius: 10px;
    border: 1px solid var(--border);
    min-height: 42px;
    font-weight: 700;
    transition: all .15s ease;
}

.stButton > button[kind="primary"] {
    background: var(--navy);
    color: #FFFFFF;
    border-color: var(--navy);
}

.stButton > button[kind="primary"]:hover {
    background: var(--navy2);
    border-color: var(--navy2);
    color: #FFFFFF;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    background: #FFFFFF;
    border: 1px solid var(--border);
    border-radius: 16px;
}

[data-testid="stTabs"] button {
    font-weight: 650;
}

[data-testid="stDataFrame"] {
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
}

[data-testid="stAlert"] {
    border-radius: 12px;
}

hr {
    border-color: var(--border);
}

.brand {
    font-family: 'Manrope', sans-serif;
    color: var(--navy);
    font-size: 1.16rem;
    font-weight: 850;
    letter-spacing: -.04em;
}

.brand-sub {
    color: var(--muted);
    font-size: .75rem;
    margin-top: 2px;
}

.hero {
    background: linear-gradient(120deg, #FFFFFF 0%, #EEF4EF 100%);
    border: 1px solid #DFE8E0;
    border-radius: 20px;
    padding: 24px 26px;
    margin-bottom: 18px;
}

.eyebrow {
    color: var(--green);
    text-transform: uppercase;
    font-size: .70rem;
    font-weight: 800;
    letter-spacing: .13em;
}

.hero-title {
    font-family: 'Manrope', sans-serif;
    color: var(--navy);
    font-size: 2rem;
    font-weight: 850;
    letter-spacing: -.055em;
    margin-top: 8px;
    line-height: 1.2;
}

.hero-description {
    color: var(--muted);
    font-size: .92rem;
    line-height: 1.65;
    max-width: 750px;
    margin-top: 8px;
}

.status-pill {
    display: inline-block;
    margin-top: 14px;
    background: var(--green-bg);
    color: #2D6B4A;
    border-radius: 100px;
    padding: 7px 11px;
    font-size: .72rem;
    font-weight: 800;
    letter-spacing: .035em;
}

.section-note {
    color: var(--muted);
    font-size: .84rem;
    line-height: 1.55;
}

.account-panel {
    background: var(--navy);
    color: white;
    padding: 20px 22px;
    border-radius: 17px;
    min-height: 132px;
}

.account-label {
    color: #D0DCE7;
    font-size: .82rem;
}

.account-value {
    color: #FFFFFF;
    font-family: 'Manrope', sans-serif;
    font-size: 2.1rem;
    font-weight: 850;
    letter-spacing: -.05em;
    margin-top: 7px;
}

.account-foot {
    color: #C1DCCB;
    font-size: .79rem;
    margin-top: 3px;
}

.panel-label {
    color: var(--muted);
    font-size: .76rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: .08em;
}

.decision-buy {
    background: var(--green-bg);
    color: #2E684B;
    border: 1px solid #D5E7D9;
    padding: 17px;
    border-radius: 14px;
}

.decision-sell {
    background: var(--red-bg);
    color: #9E3E45;
    border: 1px solid #F0D8DA;
    padding: 17px;
    border-radius: 14px;
}

.decision-wait {
    background: #F0F3F6;
    color: var(--navy);
    border: 1px solid #E1E6EB;
    padding: 17px;
    border-radius: 14px;
}

.decision-title {
    font-family: 'Manrope', sans-serif;
    font-weight: 850;
    font-size: 1.3rem;
}

@media(max-width:700px) {
    .block-container {
        padding: 1rem .75rem 2rem;
    }
    .hero {
        padding: 19px 16px;
    }
    .hero-title {
        font-size: 1.65rem;
    }
    .account-value {
        font-size: 1.8rem;
    }
}
</style>
""", unsafe_allow_html=True)


# =========================================================
# 3. ENVIRONMENT AND DATABASE
# =========================================================

def get_secret(name, default=""):
    value = os.getenv(name, "")
    if value:
        return value

    try:
        return str(st.secrets[name])
    except Exception:
        return default


API_KEY = get_secret("TWELVE_DATA_API_KEY")
DATABASE_URL = get_secret("DATABASE_URL")

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

engine = None
if DATABASE_URL:
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    except Exception:
        engine = None


def db_run(sql, params=None, fetch=False):
    if engine is None:
        return [] if fetch else False

    with engine.begin() as conn:
        result = conn.execute(text(sql), params or {})
        if fetch:
            return [dict(row._mapping) for row in result]
    return True


def init_db():
    if engine is None:
        return

    ddl = [
        """
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            decision TEXT NOT NULL,
            entry DOUBLE PRECISION,
            stop DOUBLE PRECISION,
            target DOUBLE PRECISION,
            risk_usd DOUBLE PRECISION,
            net_rr DOUBLE PRECISION,
            higher_timeframe TEXT,
            higher_trend TEXT,
            strategy_version TEXT,
            candles_json TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id TEXT PRIMARY KEY,
            signal_id TEXT UNIQUE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry DOUBLE PRECISION NOT NULL,
            stop DOUBLE PRECISION NOT NULL,
            target DOUBLE PRECISION NOT NULL,
            risk_usd DOUBLE PRECISION NOT NULL,
            net_rr DOUBLE PRECISION NOT NULL,
            outcome TEXT NOT NULL DEFAULT 'OPEN',
            exit_price DOUBLE PRECISION,
            pnl_usd DOUBLE PRECISION,
            notes TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS strategy_experiments (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            name TEXT NOT NULL,
            parameters_json TEXT NOT NULL,
            baseline_metric DOUBLE PRECISION,
            candidate_metric DOUBLE PRECISION,
            validation_count INTEGER,
            status TEXT DEFAULT 'PENDING',
            notes TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS news_cache (
            url TEXT PRIMARY KEY,
            published_at TEXT,
            source TEXT,
            title TEXT,
            summary TEXT,
            fetched_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
    ]

    with engine.begin() as conn:
        for statement in ddl:
            conn.execute(text(statement))


def current_balance():
    if engine is None:
        return STARTING_BALANCE

    rows = db_run("""
        SELECT COALESCE(SUM(pnl_usd),0) AS pnl
        FROM paper_trades
        WHERE outcome IN ('WIN','LOSS','BREAKEVEN')
    """, fetch=True)

    pnl = float(rows[0]["pnl"] or 0) if rows else 0.0
    return STARTING_BALANCE + pnl


# =========================================================
# 4. MARKET DATA
# =========================================================

@st.cache_data(ttl=45, show_spinner=False)
def get_candles(symbol, timeframe, count, api_key):
    params = {
        "symbol": symbol,
        "interval": timeframe,
        "outputsize": int(count),
        "apikey": api_key,
        "format": "JSON",
        "timezone": "UTC",
        "order": "ASC",
    }

    response = requests.get(
        TWELVE_DATA_URL, params=params, timeout=25
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError("Unexpected market-data response.")

    if payload.get("status") == "error" or payload.get("code"):
        raise ValueError(
            payload.get("message", "Twelve Data returned an error.")
        )

    values = payload.get("values")
    if not values:
        raise ValueError(
            "Twelve Data returned no candles. Check the API key, symbol, "
            "interval and usage limits."
        )

    df = pd.DataFrame(values)

    required = ["datetime", "open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            "Market data is missing required fields: " + ", ".join(missing)
        )

    df["datetime"] = pd.to_datetime(
        df["datetime"], errors="coerce", utc=True
    )

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = (
        df.dropna(subset=required)
        .sort_values("datetime")
        .drop_duplicates(subset=["datetime"], keep="last")
        .reset_index(drop=True)
    )

    # Keep UTC timestamps. A candle is closed only after its interval ends.
    duration = TF_SECONDS.get(timeframe)
    if duration:
        now = pd.Timestamp.now(tz="UTC")
        candle_end = df["datetime"] + pd.to_timedelta(
            duration, unit="s"
        )
        closed = df[candle_end <= now]
        # Fail visibly rather than producing a blank chart when provider
        # timestamps are unexpected.
        if len(closed) >= 55:
            df = closed.reset_index(drop=True)
        elif len(df) >= 55:
            # Retain data for chart inspection but flag the latest candle
            # as potentially incomplete in the UI.
            pass

    if len(df) < 30:
        raise ValueError(
            f"Only {len(df)} usable candles were returned. "
            "Choose a different timeframe or request more history."
        )

    df.attrs["closed_only"] = (
        duration is None
        or len(df) < 55
        or bool(
            (
                df["datetime"]
                + pd.to_timedelta(duration, unit="s")
                <= pd.Timestamp.now(tz="UTC")
            ).all()
        )
    )

    return df


def indicators(df):
    df = df.copy()

    df["ema20"] = df["close"].ewm(
        span=20, adjust=False
    ).mean()
    df["ema50"] = df["close"].ewm(
        span=50, adjust=False
    ).mean()

    change = df["close"].diff()
    gain = change.clip(lower=0)
    loss = -change.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1/14, min_periods=14, adjust=False
    ).mean()
    avg_loss = loss.ewm(
        alpha=1/14, min_periods=14, adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi14"] = (100 - 100 / (1 + rs)).fillna(50)

    previous = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous).abs(),
        (df["low"] - previous).abs(),
    ], axis=1).max(axis=1)

    df["atr14"] = tr.rolling(14, min_periods=14).mean()
    return df


def trend_of(df):
    if len(df) < 50:
        return "NEUTRAL"

    last = df.iloc[-1]
    if last["ema20"] > last["ema50"] and last["close"] > last["ema20"]:
        return "BULLISH"
    if last["ema20"] < last["ema50"] and last["close"] < last["ema20"]:
        return "BEARISH"
    return "NEUTRAL"


# =========================================================
# 5. SUPPLY AND DEMAND ZONES
# =========================================================

def detect_zones(df):
    sample = df.tail(120).reset_index(drop=True)
    if len(sample) < 10:
        return [], []

    atr = float(df["atr14"].iloc[-1])
    if not math.isfinite(atr) or atr <= 0:
        atr = float((df["high"] - df["low"]).tail(20).mean())

    if not math.isfinite(atr) or atr <= 0:
        return [], []

    width = atr * 0.30
    supply, demand = [], []

    # Candidate pivots need two later candles to confirm.
    for i in range(2, len(sample) - 2):
        hi = float(sample.loc[i, "high"])
        lo = float(sample.loc[i, "low"])

        if (
            hi >= float(sample.loc[i-2:i+2, "high"].max())
        ):
            supply.append({
                "low": hi - width,
                "high": hi + width,
                "mid": hi,
            })

        if (
            lo <= float(sample.loc[i-2:i+2, "low"].min())
        ):
            demand.append({
                "low": lo - width,
                "high": lo + width,
                "mid": lo,
            })

    price = float(df["close"].iloc[-1])

    supply = sorted(
        [z for z in supply if z["mid"] >= price - width],
        key=lambda z: abs(z["mid"] - price),
    )[:4]

    demand = sorted(
        [z for z in demand if z["mid"] <= price + width],
        key=lambda z: abs(z["mid"] - price),
    )[:4]

    return supply, demand


def pip_size(symbol):
    if symbol == "XAU/USD":
        return 0.01
    if "JPY" in symbol:
        return 0.01
    return 0.0001


def price_text(value, symbol):
    if value is None:
        return "—"
    if symbol == "XAU/USD":
        return f"{value:.2f}"
    if "JPY" in symbol:
        return f"{value:.3f}"
    return f"{value:.5f}"


# =========================================================
# 6. TRADE PLAN AND RISK CONTROLS
# =========================================================

def build_plan(
    df, symbol, balance, risk_pct, pip_value,
    spread_pips, slippage_pips,
):
    last = df.iloc[-1]

    entry = float(last["close"])
    ema20 = float(last["ema20"])
    ema50 = float(last["ema50"])
    rsi = float(last["rsi14"])
    atr = float(last["atr14"])

    if not math.isfinite(atr) or atr <= 0:
        atr = float((df["high"] - df["low"]).tail(14).mean())

    supplies, demands = detect_zones(df)

    decision = "WAIT"
    stop = None
    target = None
    reasons = []

    bullish = ema20 > ema50 and entry > ema20
    bearish = ema20 < ema50 and entry < ema20

    near_distance = max(
        atr * 0.75 if math.isfinite(atr) else 0,
        entry * 0.0001,
    )

    closest_demand = (
        min(demands, key=lambda z: abs(z["mid"] - entry))
        if demands else None
    )
    closest_supply = (
        min(supplies, key=lambda z: abs(z["mid"] - entry))
        if supplies else None
    )

    near_demand = (
        closest_demand is not None
        and abs(closest_demand["mid"] - entry) <= near_distance
    )
    near_supply = (
        closest_supply is not None
        and abs(closest_supply["mid"] - entry) <= near_distance
    )

    if bullish and 50 <= rsi <= 68 and near_demand:
        decision = "BUY"
        stop = min(closest_demand["low"], entry - 0.8 * atr)
        reasons.append("Bullish EMA trend, RSI confirmation and nearby demand.")
    elif bearish and 32 <= rsi < 50 and near_supply:
        decision = "SELL"
        stop = max(closest_supply["high"], entry + 0.8 * atr)
        reasons.append("Bearish EMA trend, RSI confirmation and nearby supply.")
    else:
        reasons.append(
            "The trend, momentum and zone conditions do not all align."
        )

    result = {
        "decision": decision,
        "entry": None,
        "stop": None,
        "target": None,
        "lots": None,
        "risk_usd": balance * risk_pct / 100,
        "estimated_risk": None,
        "estimated_reward": None,
        "net_rr": None,
        "stop_pips": None,
        "target_pips": None,
        "reasons": reasons,
        "supplies": supplies,
        "demands": demands,
    }

    if decision not in ("BUY", "SELL"):
        return result

    if (
        not math.isfinite(pip_value)
        or pip_value <= 0
        or not math.isfinite(entry)
        or not math.isfinite(stop)
        or balance <= 0
        or not 0 < risk_pct <= MAX_RISK_PERCENT
        or not math.isfinite(atr)
        or atr <= 0
    ):
        result["decision"] = "NO TRADE"
        result["reasons"].append(
            "Invalid risk input, ATR, or verified pip value. Position sizing blocked."
        )
        return result

    size = pip_size(symbol)
    stop_pips = abs(entry - stop) / size
    spread = max(0.0, float(spread_pips))
    slippage = max(0.0, float(slippage_pips))
    friction = spread + slippage

    risk_budget = balance * min(
        risk_pct, MAX_RISK_PERCENT
    ) / 100

    risk_per_lot = (stop_pips + friction) * pip_value
    if stop_pips <= 0 or risk_per_lot <= 0:
        result["decision"] = "NO TRADE"
        result["reasons"].append("Invalid stop distance or risk calculation.")
        return result

    # Never round a position upward to meet the minimum lot.
    lots = math.floor(
        (risk_budget / risk_per_lot + 1e-12) / 0.01
    ) * 0.01
    lots = round(lots, 2)

    if lots < 0.01:
        result["decision"] = "NO TRADE"
        result["reasons"].append(
            "Minimum 0.01 lot exceeds the risk budget. Trade rejected."
        )
        return result

    estimated_risk = risk_per_lot * lots
    if estimated_risk > risk_budget + 1e-8:
        result["decision"] = "NO TRADE"
        result["reasons"].append("Position size exceeds the risk ceiling.")
        return result

    # Include estimated friction in the target-distance calculation.
    target_pips = MIN_NET_RR * (stop_pips + friction) + friction
    target_distance = max(
        target_pips * size,
        abs(entry - stop) * MIN_NET_RR,
    )

    target = (
        entry + target_distance
        if decision == "BUY"
        else entry - target_distance
    )

    target_pips = target_distance / size
    estimated_reward = max(0.0, target_pips - friction) * pip_value * lots
    net_rr = estimated_reward / estimated_risk if estimated_risk else 0.0

    if not math.isfinite(net_rr) or net_rr + 1e-9 < MIN_NET_RR:
        result["decision"] = "NO TRADE"
        result["reasons"].append(
            "Estimated net reward-to-risk is below 1:2. Trade rejected."
        )
        return result

    result.update({
        "entry": entry,
        "stop": stop,
        "target": target,
        "lots": lots,
        "estimated_risk": estimated_risk,
        "estimated_reward": estimated_reward,
        "net_rr": net_rr,
        "stop_pips": stop_pips,
        "target_pips": target_pips,
    })

    result["reasons"].append(
        "Position sizing passed the estimated risk and net R:R checks."
    )
    return result


# =========================================================
# 7. NEWS
# =========================================================

def fetch_news(symbol):
    articles = []

    for source, url in NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)

            for item in feed.entries[:10]:
                title = str(item.get("title", "")).strip()
                link = str(item.get("link", "")).strip()

                if title and link:
                    articles.append({
                        "source": source,
                        "title": title,
                        "link": link,
                        "published": str(
                            item.get("published", item.get("updated", ""))
                        ),
                    })
        except Exception:
            continue

    try:
        query = quote(
            f'"{symbol.replace("/", " ")}" forex currency'
        )
        url = (
            "https://api.gdeltproject.org/api/v2/doc/doc"
            f"?query={query}&mode=ArtList&format=json"
            "&maxrecords=20&sort=DateDesc"
        )

        response = requests.get(url, timeout=12)
        response.raise_for_status()

        for item in response.json().get("articles", []):
            if item.get("title") and item.get("url"):
                articles.append({
                    "source": item.get("domain", "GDELT"),
                    "title": item["title"],
                    "link": item["url"],
                    "published": item.get("seendate", ""),
                })
    except Exception:
        pass

    unique = {}
    for article in articles:
        unique[article["link"]] = article

    return list(unique.values())[:50]


def news_score(articles, symbol):
    positive = [
        "hawkish", "rate hike", "raises rates", "strong growth",
        "beats forecast", "tightening",
    ]
    negative = [
        "dovish", "rate cut", "cuts rates", "recession",
        "misses forecast", "unemployment rises",
    ]

    currencies = symbol.split("/")
    relevant = []
    score = 0

    for article in articles:
        title = article["title"].lower()

        if any(c.lower() in title for c in currencies):
            points = (
                sum(term in title for term in positive)
                - sum(term in title for term in negative)
            )
            score += points
            relevant.append((article, points))

    label = (
        "Mixed / uncertain" if score == 0
        else "Potentially supportive" if score > 0
        else "Potentially adverse"
    )

    return label, score, relevant


# =========================================================
# 8. PERSISTENCE
# =========================================================

def save_signal(symbol, timeframe, plan, df, higher_tf, higher_trend):
    if engine is None:
        return None

    signal_id = str(uuid.uuid4())

    db_run("""
        INSERT INTO signals (
            id,symbol,timeframe,decision,entry,stop,target,
            risk_usd,net_rr,higher_timeframe,higher_trend,
            strategy_version,candles_json
        )
        VALUES (
            :id,:symbol,:tf,:decision,:entry,:stop,:target,
            :risk,:rr,:htf,:trend,:version,:candles
        )
    """, {
        "id": signal_id,
        "symbol": symbol,
        "tf": timeframe,
        "decision": plan["decision"],
        "entry": plan.get("entry"),
        "stop": plan.get("stop"),
        "target": plan.get("target"),
        "risk": plan.get("estimated_risk") or plan["risk_usd"],
        "rr": plan.get("net_rr") or 0,
        "htf": higher_tf,
        "trend": higher_trend,
        "version": STRATEGY_VERSION,
        "candles": df.tail(120).to_json(
            orient="records", date_format="iso"
        ),
    })

    return signal_id


def export_backup():
    backup = {}

    for table in (
        "signals", "paper_trades", "strategy_experiments", "news_cache"
    ):
        try:
            backup[table] = (
                db_run(f"SELECT * FROM {table} ORDER BY created_at DESC", fetch=True)
                if engine is not None else []
            )
        except Exception as exc:
            backup[table] = {"error": str(exc)}

    return json.dumps(backup, indent=2, default=str)


# =========================================================
# 9. HEADER AND SIDEBAR
# =========================================================

st.markdown("""
<div class="hero">
    <div class="eyebrow">Market intelligence workspace</div>
    <div class="hero-title">Forex AI Analyst</div>
    <div class="hero-description">
        A disciplined environment for technical analysis, paper-trade
        evaluation and strategy learning. Clear signals, explicit risk,
        no live execution.
    </div>
    <span class="status-pill">● PAPER MODE · LIVE ORDERS DISABLED</span>
</div>
""", unsafe_allow_html=True)

now = datetime.now(timezone.utc)

st.caption(
    "All application timestamps use UTC. Current reference: "
    + now.strftime("%Y-%m-%d %H:%M:%S UTC")
)

with st.sidebar:
    st.markdown(
        '<div class="brand">FOREX ANALYST</div>'
        '<div class="brand-sub">Research workspace · Paper mode</div>',
        unsafe_allow_html=True,
    )

    st.divider()
    st.markdown("### Market")

    symbol = st.selectbox("Instrument", SYMBOLS)
    timeframe = st.selectbox("Entry timeframe", TIMEFRAMES, index=2)
    candle_count = st.select_slider(
        "Candles to request",
        options=[100, 200, 300, 500],
        value=200,
    )

    st.divider()
    st.markdown("### Risk settings")

    risk_percent = st.number_input(
        "Risk per trade (%)",
        min_value=0.1,
        max_value=MAX_RISK_PERCENT,
        value=2.0,
        step=0.1,
    )

    if symbol == "XAU/USD":
        default_pip_value = 1.0
        default_spread = 3.0
    elif symbol.endswith("/USD"):
        default_pip_value = 10.0
        default_spread = 1.0
    else:
        default_pip_value = 0.0
        default_spread = 1.5

    pip_value = st.number_input(
        "Verified pip value (USD / lot)",
        min_value=0.0,
        value=default_pip_value,
        step=0.1,
        help=(
            "Confirm this with your broker's contract specifications. "
            "Enter zero when the value is unknown; position sizing will be blocked."
        ),
    )

    spread_pips = st.number_input(
        "Estimated spread (pips)",
        min_value=0.0,
        value=default_spread,
        step=0.1,
    )

    slippage_pips = st.number_input(
        "Estimated slippage (pips)",
        min_value=0.0,
        value=0.2,
        step=0.1,
    )

    st.divider()
    st.caption(
        "Risk estimates are hypothetical. Confirm contract size, lot rules, "
        "spread, slippage, commissions and currency conversion with your broker."
    )


# =========================================================
# 10. ACCOUNT OVERVIEW
# =========================================================

db_ready = False
db_error = None

if engine is not None:
    try:
        init_db()
        db_ready = True
    except Exception as exc:
        db_error = str(exc)

balance = current_balance() if db_ready else STARTING_BALANCE

left, right = st.columns([1.15, 2])

with left:
    st.markdown(f"""
    <div class="account-panel">
        <div class="account-label">Paper account balance</div>
        <div class="account-value">${balance:,.2f}</div>
        <div class="account-foot">Starting balance: $100.00</div>
    </div>
    """, unsafe_allow_html=True)

with right:
    m1, m2, m3 = st.columns(3)

    m1.metric(
        "Risk limit",
        f"${balance * MAX_RISK_PERCENT / 100:.2f}",
        "2% maximum",
    )
    m2.metric("Minimum net R:R", "1 : 2")
    m3.metric(
        "Storage",
        "Connected" if db_ready else "Not connected",
    )

if not API_KEY:
    st.error(
        "Twelve Data API key missing. Add TWELVE_DATA_API_KEY to "
        "Streamlit Cloud → Settings → Secrets."
    )

if db_error:
    st.warning(
        "PostgreSQL is unavailable. Market analysis can still run, but "
        f"persistent records may not save. Details: {db_error}"
    )
elif not db_ready:
    st.info(
        "DATABASE_URL is not configured. This session can display market "
        "analysis, but account history and the journal will not persist."
    )

st.warning(
    "Paper trading only. No live orders are sent. This strategy has not "
    "been proven profitable, and estimated risk is not a guaranteed loss limit."
)


# =========================================================
# 11. TABS
# =========================================================

tab_analysis, tab_journal, tab_news, tab_lab = st.tabs([
    "📊  Analysis",
    "📒  Journal",
    "📰  News",
    "🧪  Strategy lab",
])


# =========================================================
# 12. ANALYSIS TAB
# =========================================================

with tab_analysis:
    top_a, top_b = st.columns([2.2, 1])

    with top_a:
        st.markdown("## Market analysis")
        st.markdown(
            '<div class="section-note">Closed-candle technical analysis, '
            'higher-timeframe confirmation and explicit trade-risk checks.</div>',
            unsafe_allow_html=True,
        )

    with top_b:
        analyze_clicked = st.button(
            "Analyze market",
            type="primary",
            use_container_width=True,
        )

    if analyze_clicked:
        if not API_KEY:
            st.error("Add your Twelve Data API key in Streamlit secrets.")
        else:
            try:
                higher_timeframe = HIGHER_TF[timeframe]

                with st.spinner("Fetching and validating market candles..."):
                    raw_df = get_candles(
                        symbol, timeframe, int(candle_count), API_KEY
                    )
                    df = indicators(raw_df)

                    higher_raw = get_candles(
                        symbol, higher_timeframe,
                        int(candle_count), API_KEY,
                    )
                    higher_df = indicators(higher_raw)

                    higher_trend = trend_of(higher_df)

                    plan = build_plan(
                        df=df,
                        symbol=symbol,
                        balance=balance,
                        risk_pct=float(risk_percent),
                        pip_value=float(pip_value),
                        spread_pips=float(spread_pips),
                        slippage_pips=float(slippage_pips),
                    )

                    # Hard higher-timeframe directional confirmation.
                    if plan["decision"] in ("BUY", "SELL"):
                        required_trend = (
                            "BULLISH"
                            if plan["decision"] == "BUY"
                            else "BEARISH"
                        )

                        if higher_trend != required_trend:
                            rejected_direction = plan["decision"]
                            plan["decision"] = "NO TRADE"
                            plan["entry"] = None
                            plan["stop"] = None
                            plan["target"] = None
                            plan["lots"] = None
                            plan["reasons"].append(
                                f"Higher-timeframe gate failed: "
                                f"{higher_timeframe} is {higher_trend}; "
                                f"{rejected_direction} requires {required_trend}."
                            )

                    # CRITICAL: Store chart state before database writes.
                    # Database failures must not stop chart rendering.
                    st.session_state["analysis_result"] = {
                        "df": df,
                        "plan": plan,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "higher_timeframe": higher_timeframe,
                        "higher_trend": higher_trend,
                        "signal_id": None,
                        "analyzed_at": datetime.now(timezone.utc).isoformat(),
                    }

                    if db_ready:
                        try:
                            signal_id = save_signal(
                                symbol,
                                timeframe,
                                plan,
                                df,
                                higher_timeframe,
                                higher_trend,
                            )
                            st.session_state["analysis_result"]["signal_id"] = signal_id
                        except Exception as exc:
                            st.warning(
                                "Candles loaded, but saving the signal failed: "
                                + str(exc)
                            )

            except requests.exceptions.Timeout:
                st.error("The market-data request timed out. Try again.")
            except requests.exceptions.RequestException as exc:
                st.error(f"Could not reach Twelve Data: {exc}")
            except ValueError as exc:
                st.error(f"Market-data validation: {exc}")
            except Exception as exc:
                st.error(f"Analysis failed: {exc}")

    # Always render the most recent successful analysis after Streamlit reruns.
    result = st.session_state.get("analysis_result")

    if result:
        df = result["df"]
        plan = result["plan"]
        current_symbol = result["symbol"]
        current_tf = result["timeframe"]

        st.divider()

        info1, info2, info3, info4 = st.columns(4)

        info1.metric(
            "Instrument",
            current_symbol,
        )
        info2.metric(
            "Last candle close",
            price_text(float(df["close"].iloc[-1]), current_symbol),
        )
        info3.metric(
            "RSI (14)",
            f"{float(df['rsi14'].iloc[-1]):.1f}",
        )
        info4.metric(
            "Higher-timeframe trend",
            result["higher_trend"],
        )

        decision = plan["decision"]

        if decision == "BUY":
            st.markdown("""
            <div class="decision-buy">
                <div class="decision-title">BUY candidate</div>
                <div>Conditions passed the current technical and risk filters.
                Paper trading only.</div>
            </div>
            """, unsafe_allow_html=True)
        elif decision == "SELL":
            st.markdown("""
            <div class="decision-sell">
                <div class="decision-title">SELL candidate</div>
                <div>Conditions passed the current technical and risk filters.
                Paper trading only.</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="decision-wait">
                <div class="decision-title">WAIT / NO TRADE</div>
                <div>No approved directional setup is currently available.
                Do not force an entry.</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("### Trade plan")

        if decision in ("BUY", "SELL") and plan.get("entry") is not None:
            a, b, c, d = st.columns(4)

            a.metric("Entry", price_text(plan["entry"], current_symbol))
            b.metric("Stop-loss", price_text(plan["stop"], current_symbol))
            c.metric("Take-profit", price_text(plan["target"], current_symbol))
            d.metric("Estimated net R:R", f"1:{plan['net_rr']:.2f}")

            a, b, c = st.columns(3)
            a.metric("Position size", f"{plan['lots']:.2f} lots")
            b.metric("Estimated risk", f"${plan['estimated_risk']:.2f}")
            c.metric("Estimated reward", f"${plan['estimated_reward']:.2f}")

        with st.expander("Why did the analyst make this assessment?", expanded=True):
            for reason in plan["reasons"]:
                st.markdown(f"- {reason}")

        st.markdown("### Price chart")

        if len(df) < 2:
            st.error(
                "The data source returned fewer than two candles. "
                "A candlestick chart cannot be rendered."
            )
        else:
            fig = go.Figure()

            fig.add_trace(go.Candlestick(
                x=df["datetime"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name=current_symbol,
                increasing_line_color="#39815F",
                decreasing_line_color="#C05B63",
                increasing_fillcolor="#39815F",
                decreasing_fillcolor="#C05B63",
            ))

            fig.add_trace(go.Scatter(
                x=df["datetime"],
                y=df["ema20"],
                name="EMA 20",
                mode="lines",
                line=dict(color="#2D7956", width=1.6),
            ))

            fig.add_trace(go.Scatter(
                x=df["datetime"],
                y=df["ema50"],
                name="EMA 50",
                mode="lines",
                line=dict(color="#6E839B", width=1.6),
            ))

            x0 = df["datetime"].iloc[0]
            x1 = df["datetime"].iloc[-1]

            for zone in plan["demands"]:
                fig.add_shape(
                    type="rect",
                    x0=x0, x1=x1,
                    y0=zone["low"], y1=zone["high"],
                    fillcolor="rgba(57,129,95,0.10)",
                    line=dict(width=0),
                    layer="below",
                )

            for zone in plan["supplies"]:
                fig.add_shape(
                    type="rect",
                    x0=x0, x1=x1,
                    y0=zone["low"], y1=zone["high"],
                    fillcolor="rgba(192,91,99,0.10)",
                    line=dict(width=0),
                    layer="below",
                )

            if decision in ("BUY", "SELL"):
                fig.add_hline(
                    y=plan["entry"],
                    line_dash="dot",
                    line_color="#172B43",
                    annotation_text="Entry",
                )
                fig.add_hline(
                    y=plan["stop"],
                    line_dash="dash",
                    line_color="#C05B63",
                    annotation_text="Stop",
                )
                fig.add_hline(
                    y=plan["target"],
                    line_dash="dash",
                    line_color="#39815F",
                    annotation_text="Target",
                )

            fig.update_layout(
                height=580,
                margin=dict(l=10, r=10, t=35, b=10),
                paper_bgcolor="#FFFFFF",
                plot_bgcolor="#FFFFFF",
                font=dict(
                    family="DM Sans, sans-serif",
                    color="#172B43",
                ),
                xaxis_rangeslider_visible=False,
                hovermode="x unified",
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="left",
                    x=0,
                ),
                xaxis=dict(
                    showgrid=True,
                    gridcolor="#EEF1EE",
                    title="Time (UTC)",
                ),
                yaxis=dict(
                    showgrid=True,
                    gridcolor="#EEF1EE",
                    title="Price",
                ),
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                key="market_candlestick_chart",
            )

            st.caption(
                f"{len(df)} candles · "
                f"From {df['datetime'].iloc[0]} to {df['datetime'].iloc[-1]} · "
                "Timestamps in UTC."
            )

            if "volume" in df.columns and df["volume"].notna().any():
                with st.expander("View volume"):
                    volume_fig = go.Figure()
                    volume_fig.add_trace(go.Bar(
                        x=df["datetime"],
                        y=df["volume"],
                        name="Volume",
                    ))
                    volume_fig.update_layout(
                        height=220,
                        margin=dict(l=10, r=10, t=20, b=10),
                        paper_bgcolor="#FFFFFF",
                        plot_bgcolor="#FFFFFF",
                        xaxis_title="Time (UTC)",
                        yaxis_title="Volume",
                    )
                    st.plotly_chart(
                        volume_fig,
                        use_container_width=True,
                        key="market_volume_chart",
                    )

            z1, z2 = st.columns(2)

            with z1:
                st.markdown("#### Demand zones")
                if plan["demands"]:
                    st.dataframe(pd.DataFrame([
                        {
                            "Lower": price_text(z["low"], current_symbol),
                            "Upper": price_text(z["high"], current_symbol),
                        }
                        for z in plan["demands"]
                    ]), use_container_width=True, hide_index=True)
                else:
                    st.caption("No demand zones detected.")

            with z2:
                st.markdown("#### Supply zones")
                if plan["supplies"]:
                    st.dataframe(pd.DataFrame([
                        {
                            "Lower": price_text(z["low"], current_symbol),
                            "Upper": price_text(z["high"], current_symbol),
                        }
                        for z in plan["supplies"]
                    ]), use_container_width=True, hide_index=True)
                else:
                    st.caption("No supply zones detected.")

            with st.expander("Inspect candle data"):
                st.dataframe(
                    df[[
                        "datetime", "open", "high", "low", "close",
                        "ema20", "ema50", "rsi14", "atr14",
                    ]].tail(50).sort_values(
                        "datetime", ascending=False
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

            # Open paper trade only when all hard filters have passed.
            signal_id = result.get("signal_id")

            if (
                db_ready
                and signal_id
                and decision in ("BUY", "SELL")
                and plan.get("lots") is not None
            ):
                existing = db_run(
                    "SELECT id FROM paper_trades WHERE signal_id=:sid",
                    {"sid": signal_id},
                    fetch=True,
                )

                if not existing:
                    with st.expander("Create a paper-trade record"):
                        st.caption(
                            "This saves a simulated trade record only. "
                            "It does not connect to a broker or send an order."
                        )

                        if st.button(
                            "Record paper trade",
                            type="primary",
                            key="record_" + signal_id,
                        ):
                            try:
                                db_run("""
                                    INSERT INTO paper_trades (
                                        id,signal_id,symbol,direction,entry,
                                        stop,target,risk_usd,net_rr,outcome
                                    )
                                    VALUES (
                                        :id,:sid,:symbol,:direction,:entry,
                                        :stop,:target,:risk,:rr,'OPEN'
                                    )
                                    ON CONFLICT DO NOTHING
                                """, {
                                    "id": str(uuid.uuid4()),
                                    "sid": signal_id,
                                    "symbol": current_symbol,
                                    "direction": decision,
                                    "entry": plan["entry"],
                                    "stop": plan["stop"],
                                    "target": plan["target"],
                                    "risk": plan["estimated_risk"],
                                    "rr": plan["net_rr"],
                                })
                                st.success("Paper trade recorded.")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Could not save trade: {exc}")

            st.caption(
                "Strategy logic uses EMA trend, RSI and heuristic zones. "
                "It has not been validated as profitable. Costs are estimates, "
                "not guaranteed execution prices."
            )

    else:
        st.info(
            "Select your instrument and timeframe in the sidebar, then click "
            "**Analyze market**. The chart appears here after valid candle data "
            "has been received."
        )


# =========================================================
# 13. JOURNAL TAB
# =========================================================

with tab_journal:
    st.markdown("## Paper-trading journal")
    st.markdown(
        '<div class="section-note">Track completed outcomes and keep the '
        'paper balance tied to recorded results.</div>',
        unsafe_allow_html=True,
    )

    if not db_ready:
        st.warning(
            "Configure DATABASE_URL to enable persistent trades and journal history."
        )
    else:
        try:
            open_trades = db_run("""
                SELECT * FROM paper_trades
                WHERE outcome='OPEN'
                ORDER BY created_at DESC
                LIMIT 300
            """, fetch=True)

            closed_trades = db_run("""
                SELECT * FROM paper_trades
                WHERE outcome IN ('WIN','LOSS','BREAKEVEN')
                ORDER BY created_at DESC
                LIMIT 500
            """, fetch=True)

            all_trades = db_run("""
                SELECT * FROM paper_trades
                ORDER BY created_at DESC
                LIMIT 500
            """, fetch=True)

            total_pnl = sum(
                float(t["pnl_usd"] or 0) for t in closed_trades
            )
            wins = sum(t["outcome"] == "WIN" for t in closed_trades)
            losses = sum(t["outcome"] == "LOSS" for t in closed_trades)

            a, b, c, d = st.columns(4)
            a.metric("Open trades", len(open_trades))
            b.metric("Closed trades", len(closed_trades))
            c.metric(
                "Recorded win rate",
                f"{100*wins/len(closed_trades):.1f}%"
                if closed_trades else "—",
            )
            d.metric("Recorded net P&L", f"${total_pnl:.2f}")

            st.markdown("### Open trades")

            if open_trades:
                st.dataframe(
                    pd.DataFrame(open_trades),
                    use_container_width=True,
                    hide_index=True,
                )

                trade_options = {
                    f"{t['symbol']} · {t['direction']} · {t['id'][:8]}": t
                    for t in open_trades
                }

                with st.expander("Close an open paper trade"):
                    chosen = st.selectbox(
                        "Choose trade",
                        list(trade_options.keys()),
                    )
                    trade = trade_options[chosen]

                    outcome = st.selectbox(
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
                    notes = st.text_area("Review notes")

                    if st.button("Save trade outcome", type="primary"):
                        valid_pnl = (
                            (outcome == "WIN" and pnl > 0)
                            or (outcome == "LOSS" and pnl < 0)
                            or (
                                outcome == "BREAKEVEN"
                                and abs(pnl) < 1e-9
                            )
                        )

                        if exit_price <= 0:
                            st.error("Enter a valid exit price.")
                        elif not valid_pnl:
                            st.error(
                                "Outcome and P&L must agree: WIN positive, "
                                "LOSS negative, BREAKEVEN zero."
                            )
                        else:
                            try:
                                db_run("""
                                    UPDATE paper_trades
                                    SET outcome=:outcome,
                                        exit_price=:exit,
                                        pnl_usd=:pnl,
                                        notes=:notes
                                    WHERE id=:id AND outcome='OPEN'
                                """, {
                                    "outcome": outcome,
                                    "exit": exit_price,
                                    "pnl": pnl,
                                    "notes": notes,
                                    "id": trade["id"],
                                })
                                st.success("Outcome saved.")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Could not save outcome: {exc}")
            else:
                st.info("There are no open paper trades.")

            st.markdown("### Trade history")
            if all_trades:
                st.dataframe(
                    pd.DataFrame(all_trades),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("Your trade history will appear here.")

        except Exception as exc:
            st.error(f"Could not load the journal: {exc}")


# =========================================================
# 14. NEWS TAB
# =========================================================

with tab_news:
    st.markdown("## News & context")
    st.markdown(
        '<div class="section-note">Official releases and public headlines '
        'for context only. News scoring does not approve or execute trades.</div>',
        unsafe_allow_html=True,
    )

    if st.button("Refresh headlines", key="refresh_news"):
        with st.spinner("Fetching public news feeds..."):
            st.session_state["news_articles"] = fetch_news(symbol)

    articles = st.session_state.get("news_articles", [])

    if articles:
        label, score, relevant = news_score(articles, symbol)

        a, b = st.columns(2)
        a.metric("Keyword sentiment heuristic", label)
        b.metric("Keyword score", score)

        st.caption(
            "This is a simple keyword count, not a validated sentiment model. "
            "It may miss context, sarcasm, dates and economic importance."
        )

        for article in articles[:30]:
            st.markdown(
                f"- [{article['title']}]({article['link']})  \n"
                f"  <span style='color:#788596;font-size:.8rem'>"
                f"{article['source']} · "
                f"{article['published'] or 'Publication time unavailable'}"
                f"</span>",
                unsafe_allow_html=True,
            )
    else:
        st.info("Click Refresh headlines to load the available public sources.")


# =========================================================
# 15. STRATEGY LAB
# =========================================================

with tab_lab:
    st.markdown("## Strategy experiment lab")
    st.markdown(
        '<div class="section-note">Record candidate changes and compare them '
        'against a fixed baseline. Nothing is automatically promoted to the '
        'trading logic.</div>',
        unsafe_allow_html=True,
    )

    if not db_ready:
        st.warning(
            "Configure PostgreSQL before saving strategy experiments."
        )
    else:
        with st.form("experiment_form"):
            name = st.text_input(
                "Experiment name",
                placeholder="Alternative RSI entry threshold",
            )

            parameters = st.text_area(
                "Parameters in JSON",
                value='{"description":"Describe the proposed change"}',
            )

            a, b = st.columns(2)
            with a:
                baseline = st.number_input(
                    "Baseline out-of-sample metric",
                    value=0.0,
                    step=0.1,
                )
            with b:
                candidate = st.number_input(
                    "Candidate out-of-sample metric",
                    value=0.0,
                    step=0.1,
                )

            count = st.number_input(
                "Unseen validation trades",
                min_value=0,
                value=0,
                step=1,
            )

            submitted = st.form_submit_button(
                "Save experiment for review",
                type="primary",
            )

        if submitted:
            try:
                json.loads(parameters)

                db_run("""
                    INSERT INTO strategy_experiments (
                        id,name,parameters_json,baseline_metric,
                        candidate_metric,validation_count,status,notes
                    )
                    VALUES (
                        :id,:name,:params,:baseline,:candidate,:count,
                        'PENDING',:notes
                    )
                """, {
                    "id": str(uuid.uuid4()),
                    "name": name.strip() or "Unnamed experiment",
                    "params": parameters,
                    "baseline": baseline,
                    "candidate": candidate,
                    "count": int(count),
                    "notes": "Pending review; strategy unchanged.",
                })

                st.success(
                    "Experiment saved as PENDING. The live strategy was not changed."
                )
                st.rerun()

            except json.JSONDecodeError:
                st.error("Parameters must be valid JSON.")
            except Exception as exc:
                st.error(f"Could not save experiment: {exc}")

        try:
            experiments = db_run("""
                SELECT * FROM strategy_experiments
                ORDER BY created_at DESC
                LIMIT 100
            """, fetch=True)

            if experiments:
                st.markdown("### Experiment history")
                st.dataframe(
                    pd.DataFrame(experiments),
                    use_container_width=True,
                    hide_index=True,
                )
        except Exception as exc:
            st.error(f"Could not load experiments: {exc}")

    st.markdown("### Backup")

    if db_ready:
        st.download_button(
            "Download JSON backup",
            data=export_backup(),
            file_name=(
                "forex_ai_backup_"
                + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                + "Z.json"
            ),
            mime="application/json",
            use_container_width=True,
        )
    else:
        st.caption(
            "Configure PostgreSQL before exporting persisted database records. "
            "This application does not replace scheduled off-site backups."
        )


# =========================================================
# 16. FOOTER
# =========================================================

st.divider()

st.markdown(
    '<div class="section-note">Forex AI Analyst · Paper trading only · '
    'UTC time handling · No live order execution · '
    'Technical heuristics require independent validation.</div>',
    unsafe_allow_html=True,
)

import math
import os
import json
import uuid
import hashlib
import subprocess
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import feedparser
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


st.set_page_config(
    page_title="Forex AI Analyst",
    page_icon="📈",
    layout="wide",
)

# ----------------------------
# Persistent storage and news intelligence
# ----------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "")
try:
    if not DATABASE_URL and "DATABASE_URL" in st.secrets:
        DATABASE_URL = st.secrets["DATABASE_URL"]
except Exception:
    pass
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True) if DATABASE_URL else None
NEWS_FEEDS = {
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
    "European Central Bank": "https://www.ecb.europa.eu/rss/press.html",
    "Bank of England": "https://www.bankofengland.co.uk/rss/news",
    "Bank of Japan": "https://www.boj.or.jp/en/rss/whatsnew.xml",
    "US Treasury": "https://home.treasury.gov/news/press-releases/rss",
}


def init_db():
    if engine is None:
        return False
    ddl = [
        """CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), symbol TEXT NOT NULL,
            interval TEXT NOT NULL, decision TEXT NOT NULL, entry DOUBLE PRECISION, stop DOUBLE PRECISION,
            target DOUBLE PRECISION, risk_usd DOUBLE PRECISION, planned_net_rr DOUBLE PRECISION,
            news_bias TEXT, news_score DOUBLE PRECISION, news_summary TEXT, source_links TEXT,
            strategy_version TEXT NOT NULL DEFAULT 'baseline-v1', candles_json TEXT)""",
        """CREATE TABLE IF NOT EXISTS paper_trades (
            id TEXT PRIMARY KEY, signal_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            symbol TEXT NOT NULL, direction TEXT NOT NULL, entry DOUBLE PRECISION NOT NULL,
            stop DOUBLE PRECISION NOT NULL, target DOUBLE PRECISION NOT NULL, risk_usd DOUBLE PRECISION NOT NULL,
            planned_net_rr DOUBLE PRECISION NOT NULL, outcome TEXT NOT NULL DEFAULT 'OPEN',
            exit_price DOUBLE PRECISION, pnl_usd DOUBLE PRECISION, notes TEXT)""",
        """CREATE TABLE IF NOT EXISTS strategy_experiments (
            id TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), name TEXT NOT NULL,
            parameters_json TEXT NOT NULL, baseline_metric DOUBLE PRECISION, candidate_metric DOUBLE PRECISION,
            validation_count INTEGER, status TEXT NOT NULL DEFAULT 'PENDING', notes TEXT)""",
        """CREATE TABLE IF NOT EXISTS news_cache (
            url TEXT PRIMARY KEY, published_at TEXT, source TEXT, title TEXT NOT NULL,
            summary TEXT, fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"""
    ]
    with engine.begin() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))
    return True


def db_execute(sql, params=None, fetch=False):
    if engine is None:
        return [] if fetch else False
    with engine.begin() as conn:
        result = conn.execute(text(sql), params or {})
        if fetch:
            return [dict(row._mapping) for row in result]
    return True


def fetch_news(symbol, hours=72):
    """Pull official RSS releases plus GDELT public news search; all items retain source URLs."""
    items = []
    for source, url in NEWS_FEEDS.items():
        try:
            parsed = feedparser.parse(url, request_headers={"User-Agent": "ForexAIAnalyst/1.0 contact: admin"})
            for entry in parsed.entries[:12]:
                title = str(entry.get("title", "")).strip()
                link = str(entry.get("link", "")).strip()
                if title and link:
                    items.append({"source": source, "title": title, "summary": str(entry.get("summary", ""))[:1200],
                                  "url": link, "published": str(entry.get("published", entry.get("updated", "")))})
        except Exception:
            continue
    try:
        pair = symbol.replace("/", " ")
        url = "https://api.gdeltproject.org/api/v2/doc/doc?query=" + quote(f'"{pair}" forex OR currency') + "&mode=ArtList&format=json&maxrecords=20&sort=DateDesc"
        response = requests.get(url, timeout=12, headers={"User-Agent": "ForexAIAnalyst/1.0"})
        response.raise_for_status()
        for item in response.json().get("articles", []):
            items.append({"source": item.get("domain", "GDELT public news"), "title": item.get("title", ""),
                          "summary": item.get("seendate", ""), "url": item.get("url", ""), "published": item.get("seendate", "")})
    except Exception:
        pass
    # Deduplicate by URL; do not claim a headline alone proves market direction.
    unique = {}
    for item in items:
        if item["url"] and item["title"]:
            unique[item["url"]] = item
    items = list(unique.values())[:80]
    if engine is not None:
        for item in items:
            try:
                db_execute("""INSERT INTO news_cache(url,published_at,source,title,summary) VALUES(:url,:published,:source,:title,:summary)
                ON CONFLICT(url) DO UPDATE SET title=EXCLUDED.title, summary=EXCLUDED.summary, fetched_at=NOW()""", {
                    "url": item["url"], "published": item["published"], "source": item["source"],
                    "title": item["title"], "summary": item["summary"]})
            except Exception:
                pass
    return items


def score_news(items, symbol):
    """Transparent keyword heuristic, not a trained sentiment model or trade instruction."""
    currencies = [x for x in symbol.split("/") if x]
    relevant = []
    positive = {"hawkish", "rate hike", "raises rates", "strong growth", "beats forecast", "inflation rises", "tightening", "surplus"}
    negative = {"dovish", "rate cut", "cuts rates", "recession", "misses forecast", "inflation falls", "easing", "deficit", "unemployment rises"}
    for item in items:
        title = item["title"].lower()
        if any(c.lower() in title for c in currencies) or item["source"] in NEWS_FEEDS:
            score = sum(1 for term in positive if term in title) - sum(1 for term in negative if term in title)
            relevant.append((item, score))
    total = sum(score for _, score in relevant)
    bias = "Mixed / uncertain" if total == 0 else ("Potentially supportive" if total > 0 else "Potentially adverse")
    return bias, total, relevant


def persist_signal(symbol, interval, plan, news, candles):
    if engine is None:
        return None
    signal_id = str(uuid.uuid4())
    bias, score, relevant = news
    links = [{"source": x["source"], "title": x["title"], "url": x["url"]} for x, _ in relevant[:12]]
    db_execute("""INSERT INTO signals(id,symbol,interval,decision,entry,stop,target,risk_usd,planned_net_rr,
        news_bias,news_score,news_summary,source_links,strategy_version,candles_json)
        VALUES(:id,:symbol,:interval,:decision,:entry,:stop,:target,:risk,:rr,:bias,:score,:summary,:links,:version,:candles)""", {
        "id": signal_id, "symbol": symbol, "interval": interval, "decision": plan.get("decision", "WAIT"),
        "entry": plan.get("entry"), "stop": plan.get("stop"), "target": plan.get("target"),
        "risk": plan.get("estimated_risk_usd", plan.get("risk_usd", 0)), "rr": plan.get("planned_net_rr", 0),
        "bias": bias, "score": score, "summary": json.dumps([x[0]["title"] for x in relevant[:12]]),
        "links": json.dumps(links), "version": "baseline-v1",
        "candles": candles.tail(100).to_json(orient="records", date_format="iso")})
    return signal_id


def save_backup():
    """Logical JSON export of app records; intended for manual download and external backup storage."""
    payload = {}
    for table in ("signals", "paper_trades", "strategy_experiments", "news_cache"):
        payload[table] = db_execute(f"SELECT * FROM {table} ORDER BY 1", fetch=True) if engine is not None else []
    return json.dumps(payload, default=str, indent=2)


# ----------------------------
# App configuration
# ----------------------------
DEFAULT_BALANCE = 100.0
DEFAULT_RISK_PCT = 2.0
MIN_RR = 2.0
API_URL = "https://api.twelvedata.com/time_series"

SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "NZD/USD", "USD/CAD", "EUR/GBP",
    "EUR/JPY", "GBP/JPY", "XAU/USD",
]
INTERVALS = ["1min", "5min", "15min", "30min", "1h", "2h", "4h", "1day"]


# ----------------------------
# Data and indicator functions
# ----------------------------
@st.cache_data(ttl=60, show_spinner=False)
def fetch_candles(symbol: str, interval: str, outputsize: int, api_key: str) -> pd.DataFrame:
    """Fetch candles from Twelve Data. The API key stays server-side in Streamlit Secrets."""
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
        message = payload.get("message", "Unknown Twelve Data error")
        raise ValueError(f"Twelve Data returned an error: {message}")

    values = payload.get("values") if isinstance(payload, dict) else None
    if not values:
        raise ValueError(
            "No candles were returned. This can happen when the market is closed, "
            "the symbol/interval is unavailable on your plan, or the API limit was reached."
        )

    df = pd.DataFrame(values)
    required = ["datetime", "open", "high", "low", "close"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError("The data response is missing: " + ", ".join(missing))

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce", utc=True)
    for column in ["open", "high", "low", "close"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=required).sort_values("datetime").reset_index(drop=True)
    if len(df) < 55:
        raise ValueError(
            f"Only {len(df)} valid candles were returned. Try a higher timeframe or "
            "a larger candle count; at least 55 candles are needed for this analysis."
        )

    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi14"] = 100 - (100 / (1 + rs))
    df["rsi14"] = df["rsi14"].fillna(50)

    previous_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr14"] = true_range.rolling(14, min_periods=14).mean()
    return df


def find_zones(df: pd.DataFrame, lookback: int = 100):
    """Approximate supply/demand zones from local swing highs/lows."""
    sample = df.tail(lookback).reset_index(drop=True)
    if len(sample) < 10:
        return [], []

    atr = float(df["atr14"].iloc[-1])
    if not math.isfinite(atr) or atr <= 0:
        atr = float((df["high"] - df["low"]).tail(20).mean())
    if not math.isfinite(atr) or atr <= 0:
        atr = float(df["close"].iloc[-1]) * 0.001

    width = atr * 0.35
    supplies = []
    demands = []

    # Use confirmed local pivots; these are heuristic zones, not institutional order-flow data.
    for i in range(2, len(sample) - 2):
        high = float(sample.loc[i, "high"])
        low = float(sample.loc[i, "low"])
        if high >= float(sample.loc[i - 1:i + 2, "high"].max()) and high >= float(sample.loc[i - 2, "high"]):
            supplies.append({"low": high - width, "high": high + width, "mid": high})
        if low <= float(sample.loc[i - 1:i + 2, "low"].min()) and low <= float(sample.loc[i - 2, "low"]):
            demands.append({"low": low - width, "high": low + width, "mid": low})

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


def market_status_utc() -> tuple[str, str]:
    """Approximate standard FX market hours; broker and metal hours can differ."""
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # Monday=0, Sunday=6
    hour = now.hour
    if weekday == 5:
        return "Market generally closed", "Saturday UTC; forex is normally closed."
    if weekday == 6 and hour < 21:
        return "Market generally closed", "Sunday UTC; forex commonly reopens around 21:00–22:00 UTC."
    if weekday == 4 and hour >= 21:
        return "Market generally closed", "Friday late UTC; forex commonly closes around 21:00–22:00 UTC."
    return "Market schedule may be open", "Hours vary by broker and instrument; verify with your broker."


def format_price(value: float, symbol: str) -> str:
    if "JPY" in symbol:
        return f"{value:.3f}"
    if symbol == "XAU/USD":
        return f"{value:.2f}"
    return f"{value:.5f}"


def pip_size_for(symbol: str) -> float:
    if symbol == "XAU/USD":
        return 0.01
    if "JPY" in symbol:
        return 0.01
    return 0.0001


def create_trade_plan(df: pd.DataFrame, symbol: str, balance: float, risk_pct: float,
                      pip_value_per_lot: float, min_rr: float = MIN_RR,
                      spread_pips: float = 0.0, slippage_pips: float = 0.0):
    """Conservative heuristic setup: trend + RSI + proximity to a swing zone."""
    last = df.iloc[-1]
    close = float(last["close"])
    ema20 = float(last["ema20"])
    ema50 = float(last["ema50"])
    rsi = float(last["rsi14"])
    atr = float(last["atr14"])
    if not math.isfinite(atr) or atr <= 0:
        atr = float((df["high"] - df["low"]).tail(14).mean())

    supplies, demands = find_zones(df)
    near_distance = max(atr * 0.75, close * 0.0001)
    nearest_demand = min(demands, key=lambda z: abs(close - z["mid"])) if demands else None
    nearest_supply = min(supplies, key=lambda z: abs(close - z["mid"])) if supplies else None

    bullish = ema20 > ema50 and close > ema20
    bearish = ema20 < ema50 and close < ema20
    buy_near_demand = nearest_demand is not None and abs(close - nearest_demand["mid"]) <= near_distance
    sell_near_supply = nearest_supply is not None and abs(close - nearest_supply["mid"]) <= near_distance

    decision = "WAIT"
    reasons = []
    entry = close
    stop = None
    target = None
    setup_zone = None

    if bullish:
        reasons.append("EMA20 is above EMA50 and price is above EMA20 (bullish trend filter).")
    elif bearish:
        reasons.append("EMA20 is below EMA50 and price is below EMA20 (bearish trend filter).")
    else:
        reasons.append("EMA trend is mixed; no directional advantage from this filter.")

    if 50 <= rsi <= 68:
        reasons.append(f"RSI(14) is {rsi:.1f}, within the bullish momentum band.")
    elif 32 <= rsi <= 50:
        reasons.append(f"RSI(14) is {rsi:.1f}, within the bearish/weak momentum band.")
    else:
        reasons.append(f"RSI(14) is {rsi:.1f}; outside the selected entry bands.")

    if bullish and 50 <= rsi <= 68 and buy_near_demand:
        decision = "BUY"
        setup_zone = nearest_demand
        stop = min(nearest_demand["low"], close - 0.8 * atr)
        if stop >= entry:
            stop = entry - atr
        target = entry + max((entry - stop) * min_rr, atr)
        reasons.append("Price is close to a detected demand zone.")
    elif bearish and 32 <= rsi < 50 and sell_near_supply:
        decision = "SELL"
        setup_zone = nearest_supply
        stop = max(nearest_supply["high"], close + 0.8 * atr)
        if stop <= entry:
            stop = entry + atr
        target = entry - max((stop - entry) * min_rr, atr)
        reasons.append("Price is close to a detected supply zone.")
    else:
        reasons.append("The full trend + momentum + nearby-zone conditions are not all met; no entry is suggested.")

    pip_size = pip_size_for(symbol)
    risk_usd = balance * risk_pct / 100.0
    result = {
        "decision": decision,
        "reasons": reasons,
        "entry": entry if decision in ("BUY", "SELL") else None,
        "stop": stop,
        "target": target,
        "risk_usd": risk_usd,
        "rr": min_rr if decision in ("BUY", "SELL") else None,
        "pip_size": pip_size,
        "pip_value_per_lot": pip_value_per_lot,
        "lots": None,
        "units": None,
        "stop_pips": None,
        "target_pips": None,
        "zone": setup_zone,
        "supplies": supplies,
        "demands": demands,
    }

    if decision in ("BUY", "SELL") and stop is not None and target is not None:
        stop_distance = abs(entry - stop)
        target_distance = abs(target - entry)
        stop_pips = stop_distance / pip_size
        target_pips = target_distance / pip_size

        # Include estimated spread + slippage in the risk budget. Commission is zero
        # in the selected Standard-account profile, but all assumptions remain estimates.
        friction_pips = max(0.0, spread_pips) + max(0.0, slippage_pips)
        effective_risk_pips = stop_pips + friction_pips
        risk_per_standard_lot = effective_risk_pips * pip_value_per_lot
        raw_lots = risk_usd / risk_per_standard_lot if risk_per_standard_lot > 0 else 0.0

        # Exness Standard profile: minimum volume 0.01 lot and 0.01-lot steps.
        lots = math.floor((raw_lots + 1e-12) / 0.01) * 0.01
        result["stop_pips"] = stop_pips
        result["target_pips"] = target_pips
        result["friction_pips"] = friction_pips
        result["effective_risk_pips"] = effective_risk_pips
        result["lots"] = lots
        result["units"] = lots * 100 if symbol == "XAU/USD" else lots * 100000
        result["estimated_risk_usd"] = effective_risk_pips * pip_value_per_lot * lots
        result["planned_reward_usd"] = max(0.0, (target_distance / pip_size - friction_pips) * pip_value_per_lot * lots)
        result["planned_net_rr"] = (
            result["planned_reward_usd"] / result["estimated_risk_usd"]
            if result["estimated_risk_usd"] > 0 else 0.0
        )

        # Never suggest a minimum lot if it would exceed the user's configured risk cap.
        if lots < 0.01 or result["estimated_risk_usd"] > risk_usd + 1e-9:
            result["decision"] = "NO TRADE"
            result["reasons"].append(
                f"The minimum 0.01-lot size would not fit the ${risk_usd:.2f} risk budget "
                "after the stop distance and estimated spread/slippage. No trade is suggested."
            )
            result["entry"] = None
            result["stop"] = None
            result["target"] = None
            result["lots"] = None
            result["units"] = None
    return result


# ----------------------------
# User interface
# ----------------------------
st.title("📈 Forex AI Analyst")
st.caption("Rule-based technical analysis • Supply & demand estimates • Exness Standard simulation profile • Paper trading only")

status, status_note = market_status_utc()
if status == "Market generally closed":
    st.warning(f"**{status}** — {status_note} Historical analysis can still work if Twelve Data returns candles.")
else:
    st.info(f"**{status}** — {status_note}")

st.warning(
    "Paper trading only. This tool does not connect to or place orders with a broker. Signals are heuristic, not financial advice. "
    "Supply/demand zones are estimated from price swings and do not prove institutional orders are present."
)
st.caption("Selected baseline: Exness Standard account rules. Your actual onboarding entity, spread, contract settings, minimum volume, and execution conditions may differ. Verify them in your own demo account before relying on sizing estimates.")

with st.sidebar:
    st.header("Analysis settings")
    symbol = st.selectbox("Instrument", SYMBOLS, index=0)
    interval = st.selectbox("Timeframe", INTERVALS, index=2)
    candle_count = st.select_slider("Historical candles", options=[100, 200, 300, 500], value=200)

    st.divider()
    st.subheader("Paper account")
    balance = st.number_input("Account balance (USD)", min_value=1.0, value=DEFAULT_BALANCE, step=10.0)
    risk_pct = st.number_input(
        "Risk per trade (%)", min_value=0.1, max_value=2.0,
        value=DEFAULT_RISK_PCT, step=0.1,
        help="Maximum planned risk is capped at 2% of the paper account.",
    )
    risk_pct = min(float(risk_pct), 2.0)
    st.caption(f"Maximum planned risk: ${balance * risk_pct / 100:.2f}")

    st.subheader("Exness Standard simulation rules")
    st.caption("Typical Exness specifications: FX contract 100,000 units; XAU/USD contract 100 troy ounces; minimum volume 0.01 lot. Confirm the exact symbol specification in your own demo terminal.")
    if symbol == "XAU/USD":
        pip_value_per_lot = 1.0  # 100 oz x $0.01 price movement, quoted in USD
        default_spread_pips = 3.0
    elif "JPY" in symbol:
        # Pip value for JPY crosses depends on the quote currency conversion rate.
        pip_value_per_lot = 6.7
        default_spread_pips = 1.5
    else:
        pip_value_per_lot = 10.0 if symbol.endswith("/USD") else 7.0
        default_spread_pips = 1.0

    st.caption(f"Estimated pip value: ${pip_value_per_lot:.2f} per pip per 1.00 lot (approximate; especially approximate for non-USD quote currencies).")
    spread_pips = st.number_input(
        "Estimated spread (pips)",
        min_value=0.0,
        value=float(default_spread_pips),
        step=0.1,
        help="Editable planning assumption, not a live Exness spread. Check the actual spread in your broker's terminal.",
    )
    slippage_pips = st.number_input(
        "Slippage allowance (pips)",
        min_value=0.0,
        value=0.2,
        step=0.1,
        help="Planning allowance only. Real slippage varies with liquidity, volatility, and execution.",
    )

st.caption("Broker rules profile: Exness Standard (simulation only). Price candles come from Twelve Data, not an Exness account feed; spreads and execution can differ. The API key is read from Streamlit Secrets.")

# Persistent database is required for long-lived records on online hosting.
if engine is not None:
    try:
        init_db()
        st.success("Persistent PostgreSQL connected. Signals, paper outcomes and experiments can be retained across redeploys.")
    except Exception as exc:
        st.error(f"Database initialization failed: {exc}")
else:
    st.warning("DATABASE_URL is not configured. News can still be read, but records will NOT persist between sessions. Configure PostgreSQL before relying on learning history.")

st.subheader("Current news intelligence")
if st.button("Refresh official and public news", use_container_width=True):
    with st.spinner("Reading official releases and public news headlines..."):
        st.session_state["news_items"] = fetch_news(symbol)
news_items = st.session_state.get("news_items", [])
if news_items:
    news_result = score_news(news_items, symbol)
    st.caption(f"Headline heuristic for {symbol}: **{news_result[0]}** (score {news_result[1]}). This is a weak keyword signal, not verified sentiment; it cannot independently authorize a trade.")
    for item, item_score in news_result[2][:10]:
        st.markdown(f"- [{item['title']}]({item['url']}) — {item['source']} · {item['published'] or 'publication time unavailable'}")
else:
    news_result = ("No current news loaded", 0, [])
    st.info("Select **Refresh official and public news** to load central-bank RSS releases and GDELT public headlines. News feeds may be unavailable or delayed.")

if st.button("Analyze market", type="primary", use_container_width=True):
    try:
        api_key = st.secrets.get("TWELVE_DATA_API_KEY", "")
        if not api_key:
            st.error(
                "API key not found. In Streamlit Community Cloud, open your app's Settings → Secrets "
                "and ensure TWELVE_DATA_API_KEY is set there. Do not put the key in app.py or GitHub."
            )
            st.stop()

        with st.spinner(f"Fetching {candle_count} candles for {symbol} ({interval})..."):
            candles = fetch_candles(symbol, interval, int(candle_count), api_key)
            candles = add_indicators(candles)
            plan = create_trade_plan(
                candles, symbol, float(balance), float(risk_pct),
                float(pip_value_per_lot), MIN_RR,
                spread_pips=float(spread_pips),
                slippage_pips=float(slippage_pips),
            )
            # Enforce the minimum after estimated spread/slippage. Any uncertainty means no trade.
            if plan.get("decision") in ("BUY", "SELL") and float(plan.get("planned_net_rr", 0) or 0) < MIN_RR:
                plan["decision"] = "NO TRADE"
                plan["reasons"].append("Rejected: estimated net reward-to-risk after spread/slippage is below 1:2.")
                plan["entry"] = plan["stop"] = plan["target"] = None
            # News is displayed as contextual evidence, not allowed to override hard risk rules.
            signal_id = persist_signal(symbol, interval, plan, news_result, candles) if engine is not None else None
            if signal_id:
                st.session_state["last_signal_id"] = signal_id

        latest = candles.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Latest close", format_price(float(latest["close"]), symbol))
        c2.metric("EMA 20", format_price(float(latest["ema20"]), symbol))
        c3.metric("EMA 50", format_price(float(latest["ema50"]), symbol))
        c4.metric("RSI (14)", f"{float(latest['rsi14']):.1f}")

        st.subheader("Trade analysis")
        decision = plan["decision"]
        if decision == "BUY":
            st.success("BUY setup candidate — paper trading only")
        elif decision == "SELL":
            st.error("SELL setup candidate — paper trading only")
        else:
            st.info("WAIT / NO TRADE — no complete setup right now")

        for reason in plan["reasons"]:
            st.write(f"• {reason}")

        if decision in ("BUY", "SELL") and plan.get("entry") is not None:
            t1, t2, t3, t4 = st.columns(4)
            t1.metric("Entry (indicative)", format_price(plan["entry"], symbol))
            t2.metric("Stop-loss", format_price(plan["stop"], symbol))
            t3.metric("Take-profit", format_price(plan["target"], symbol))
            t4.metric("Planned R:R", f"1:{plan['rr']:.1f}+")

            p1, p2, p3 = st.columns(3)
            p1.metric("Stop distance", f"{plan['stop_pips']:.1f} pips / points")
            p2.metric("Estimated position", f"{plan['lots']:.4f} lots")
            p3.metric("Planned risk", f"${plan['risk_usd']:.2f}")

            st.write(
                f"Estimated target reward at this plan: **${plan.get('planned_reward_usd', 0):.2f}** "
                f"before spreads, commissions, slippage, swaps, and contract differences."
            )
            st.caption(
                f"Approximate units: {plan['units']:,.0f}. Confirm minimum lot size, lot step, pip value, "
                "and contract size with your broker before using these figures even in a demo account."
            )
        else:
            st.write(
                f"Paper account: **${balance:.2f}** · risk setting: **{risk_pct:.1f}%** "
                f"· maximum planned risk per trade: **${plan['risk_usd']:.2f}**."
            )

        st.subheader("Candlestick chart and estimated zones")
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=candles["datetime"],
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name=symbol,
        ))
        fig.add_trace(go.Scatter(
            x=candles["datetime"], y=candles["ema20"],
            mode="lines", name="EMA 20",
        ))
        fig.add_trace(go.Scatter(
            x=candles["datetime"], y=candles["ema50"],
            mode="lines", name="EMA 50",
        ))

        x_start = candles["datetime"].iloc[0]
        x_end = candles["datetime"].iloc[-1]
        for zone in plan["demands"]:
            fig.add_shape(
                type="rect", xref="x", yref="y",
                x0=x_start, x1=x_end, y0=zone["low"], y1=zone["high"],
                fillcolor="rgba(0, 180, 100, 0.10)", line=dict(width=0),
                layer="below",
            )
        for zone in plan["supplies"]:
            fig.add_shape(
                type="rect", xref="x", yref="y",
                x0=x_start, x1=x_end, y0=zone["low"], y1=zone["high"],
                fillcolor="rgba(220, 60, 60, 0.10)", line=dict(width=0),
                layer="below",
            )
        if decision in ("BUY", "SELL"):
            fig.add_hline(y=plan["entry"], line_dash="dot", annotation_text="Entry")
            fig.add_hline(y=plan["stop"], line_dash="dash", annotation_text="Stop-loss")
            fig.add_hline(y=plan["target"], line_dash="dash", annotation_text="Take-profit")

        fig.update_layout(
            height=650,
            xaxis_rangeslider_visible=False,
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        st.plotly_chart(fig, use_container_width=True)

        zone_col1, zone_col2 = st.columns(2)
        with zone_col1:
            st.markdown("**Estimated demand zones**")
            if plan["demands"]:
                st.dataframe(pd.DataFrame([
                    {"Zone low": format_price(z["low"], symbol),
                     "Zone high": format_price(z["high"], symbol)}
                    for z in plan["demands"]
                ]), use_container_width=True, hide_index=True)
            else:
                st.write("No demand zones detected in this candle sample.")
        with zone_col2:
            st.markdown("**Estimated supply zones**")
            if plan["supplies"]:
                st.dataframe(pd.DataFrame([
                    {"Zone low": format_price(z["low"], symbol),
                     "Zone high": format_price(z["high"], symbol)}
                    for z in plan["supplies"]
                ]), use_container_width=True, hide_index=True)
            else:
                st.write("No supply zones detected in this candle sample.")

        with st.expander("View latest candles and indicators"):
            show_cols = ["datetime", "open", "high", "low", "close", "ema20", "ema50", "rsi14", "atr14"]
            st.dataframe(candles[show_cols].tail(30).sort_values("datetime", ascending=False),
                         use_container_width=True, hide_index=True)

        st.caption(
            "Method note: zones use recent local swing highs/lows with an ATR-based width. "
            "A BUY/SELL candidate requires trend alignment, RSI confirmation, and price near a zone. "
            "This simple model is not backtested or validated and may produce false signals. "
            "A 1:2 planned reward/risk is a target calculation, not a promise of outcome."
        )

    except requests.exceptions.Timeout:
        st.error("Twelve Data took too long to respond. Please try again.")
    except requests.exceptions.HTTPError as exc:
        st.error(f"HTTP error while requesting market data: {exc}")
    except requests.exceptions.RequestException as exc:
        st.error(f"Could not connect to Twelve Data: {exc}")
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Unexpected app error: {exc}")

else:
    st.info("Choose an instrument and timeframe, then click **Analyze market** to load candles and generate a rule-based paper-trading analysis.")

st.divider()
st.caption("Forex AI Analyst • Educational paper-trading prototype • No real-money order execution")


# ----------------------------
# Learning, outcome review and backups
# ----------------------------
st.divider()
st.header("Paper-trade journal and guarded learning")
st.caption("Only manually recorded paper outcomes are used. The app never sends orders to a broker. Do not treat a headline or one losing trade as proof a strategy should change.")
if engine is not None:
    try:
        open_trades = db_execute("SELECT * FROM paper_trades WHERE outcome='OPEN' ORDER BY created_at DESC LIMIT 100", fetch=True)
        if open_trades:
            st.subheader("Open paper records")
            st.dataframe(pd.DataFrame(open_trades), use_container_width=True, hide_index=True)
        with st.expander("Record a paper trade outcome"):
            signal_rows = db_execute("SELECT id,symbol,decision,entry,stop,target,risk_usd,planned_net_rr,created_at FROM signals WHERE decision IN ('BUY','SELL') ORDER BY created_at DESC LIMIT 100", fetch=True)
            if signal_rows:
                labels = {f"{r['created_at']} | {r['symbol']} | {r['decision']} | {r['id'][:8]}": r for r in signal_rows}
                chosen_label = st.selectbox("Signal", list(labels.keys()))
                chosen = labels[chosen_label]
                outcome = st.selectbox("Outcome", ["WIN", "LOSS", "BREAKEVEN", "CANCELLED"])
                exit_price = st.number_input("Exit price (optional; enter 0 if unknown)", min_value=0.0, value=0.0, format="%.6f")
                pnl = st.number_input("Realized simulated P/L in USD", value=0.0, step=0.1)
                notes = st.text_area("What happened? Include spread/news/market condition if relevant")
                if st.button("Save outcome"):
                    trade_id = str(uuid.uuid4())
                    db_execute("""INSERT INTO paper_trades(id,signal_id,symbol,direction,entry,stop,target,risk_usd,planned_net_rr,outcome,exit_price,pnl_usd,notes)
                    VALUES(:id,:signal,:symbol,:direction,:entry,:stop,:target,:risk,:rr,:outcome,:exit,:pnl,:notes)""", {
                        "id":trade_id,"signal":chosen["id"],"symbol":chosen["symbol"],"direction":chosen["decision"],
                        "entry":chosen["entry"],"stop":chosen["stop"],"target":chosen["target"],"risk":chosen["risk_usd"] or 0,
                        "rr":chosen["planned_net_rr"] or 0,"outcome":outcome,"exit":exit_price or None,"pnl":pnl,"notes":notes})
                    st.success("Outcome saved to PostgreSQL.")
            else:
                st.info("No BUY/SELL signal records found yet. Analyze a market with PostgreSQL configured first.")
        trades = db_execute("SELECT * FROM paper_trades ORDER BY created_at DESC LIMIT 500", fetch=True)
        if trades:
            closed = [t for t in trades if t["outcome"] in ("WIN","LOSS","BREAKEVEN")]
            st.subheader("Outcome summary")
            a,b,c = st.columns(3)
            a.metric("Closed paper records", len(closed))
            a_wins = sum(1 for t in closed if t["outcome"] == "WIN")
            b.metric("Recorded win rate", f"{100*a_wins/len(closed):.1f}%" if closed else "—")
            c.metric("Recorded simulated P/L", f"${sum(float(t['pnl_usd'] or 0) for t in closed):.2f}")
            st.dataframe(pd.DataFrame(trades), use_container_width=True, hide_index=True)
        st.subheader("Strategy experiment review")
        st.write("Candidate changes must be tested on chronologically later, unseen data and compared with the unchanged baseline. This app does not auto-deploy parameter changes.")
        experiment_name = st.text_input("Experiment name", placeholder="e.g. RSI entry band alternative")
        params_json = st.text_area("Proposed parameter changes (JSON)", value='{"description":"Document a candidate change; do not deploy automatically."}')
        baseline_metric = st.number_input("Baseline out-of-sample metric (e.g. net expectancy in R)", value=0.0, step=0.1)
        candidate_metric = st.number_input("Candidate out-of-sample metric using same metric", value=0.0, step=0.1)
        validation_count = st.number_input("Number of unseen validation trades", min_value=0, value=0, step=1)
        if st.button("Save experiment for review"):
            try:
                json.loads(params_json)
                status = "PENDING"
                notes = "Not approved. Metric alone is insufficient; inspect drawdown, costs, sample size and regime robustness."
                db_execute("INSERT INTO strategy_experiments(id,name,parameters_json,baseline_metric,candidate_metric,validation_count,status,notes) VALUES(:id,:name,:params,:base,:candidate,:n,:status,:notes)", {
                    "id":str(uuid.uuid4()),"name":experiment_name or "Unnamed experiment","params":params_json,
                    "base":baseline_metric,"candidate":candidate_metric,"n":int(validation_count),"status":status,"notes":notes})
                st.success("Experiment saved as PENDING. No strategy parameters were changed.")
            except (ValueError, SQLAlchemyError) as exc:
                st.error(f"Could not save experiment. Check JSON and database connection. Details: {exc}")
        experiments = db_execute("SELECT * FROM strategy_experiments ORDER BY created_at DESC LIMIT 100", fetch=True)
        if experiments:
            st.dataframe(pd.DataFrame(experiments), use_container_width=True, hide_index=True)
        st.subheader("Download backup")
        st.download_button("Download JSON backup", data=save_backup(), file_name=f"forex_ai_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}Z.json", mime="application/json")
        st.caption("This is a manual logical export. Also configure scheduled PostgreSQL backups or a scheduled pg_dump to storage outside the app; an app download is not an automated off-site backup.")
    except Exception as exc:
        st.error(f"Learning/journal section could not load: {exc}")
else:
    st.info("Configure DATABASE_URL to enable persistent trade outcomes, experiments, and backups. No local SQLite fallback is used because ephemeral online filesystems can lose data.")

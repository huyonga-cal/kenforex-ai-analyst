import math
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st


st.set_page_config(
    page_title="Forex AI Analyst",
    page_icon="📈",
    layout="wide",
)

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

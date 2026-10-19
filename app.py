
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

# --------------------------------------------------
# Configuration
# --------------------------------------------------
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


# --------------------------------------------------
# Market data
# --------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def fetch_candles(
    symbol: str,
    interval: str,
    outputsize: int,
    api_key: str,
) -> pd.DataFrame:

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
            f"Twelve Data returned an error: "
            f"{payload.get('message', 'Unknown error')}"
        )

    values = payload.get("values") if isinstance(payload, dict) else None

    if not values:
        raise ValueError(
            "No candles were returned. The market may be closed, "
            "the symbol or interval may be unavailable, or the API limit "
            "may have been reached."
        )

    df = pd.DataFrame(values)

    required = ["datetime", "open", "high", "low", "close"]
    missing = [column for column in required if column not in df.columns]

    if missing:
        raise ValueError(
            "Market data is missing: " + ", ".join(missing)
        )

    df["datetime"] = pd.to_datetime(
        df["datetime"], errors="coerce", utc=True
    )

    for column in ["open", "high", "low", "close"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = (
        df.dropna(subset=required)
        .sort_values("datetime")
        .reset_index(drop=True)
    )

    if len(df) < 55:
        raise ValueError(
            f"Only {len(df)} valid candles were returned. "
            "At least 55 candles are required. Try a higher timeframe "
            "or a larger candle count."
        )

    # Reject impossible OHLC candles.
    invalid = (
        (df["high"] < df["low"])
        | (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df["low"] > df["open"])
        | (df["low"] > df["close"])
    )

    df = df.loc[~invalid].reset_index(drop=True)

    if len(df) < 55:
        raise ValueError("Too few valid candles remain after data checks.")

    return df


# --------------------------------------------------
# Technical indicators
# --------------------------------------------------
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["ema20"] = df["close"].ewm(
        span=20, adjust=False
    ).mean()

    df["ema50"] = df["close"].ewm(
        span=50, adjust=False
    ).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()

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

    df["atr14"] = true_range.rolling(
        14, min_periods=14
    ).mean()

    return df


# --------------------------------------------------
# Approximate supply and demand zones
# --------------------------------------------------
def find_zones(df: pd.DataFrame, lookback: int = 100):
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

    # Heuristic swing-pivot detection, not institutional order-flow data.
    for i in range(2, len(sample) - 2):
        high = float(sample.loc[i, "high"])
        low = float(sample.loc[i, "low"])

        nearby_highs = sample.loc[i - 2:i + 2, "high"]
        nearby_lows = sample.loc[i - 2:i + 2, "low"]

        if high >= float(nearby_highs.max()):
            supplies.append({
                "low": high - width,
                "high": high + width,
                "mid": high,
            })

        if low <= float(nearby_lows.min()):
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


# --------------------------------------------------
# Market status
# --------------------------------------------------
def market_status_utc():
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    hour = now.hour

    if weekday == 5:
        return (
            "Market generally closed",
            "Saturday UTC; forex is normally closed.",
        )

    if weekday == 6 and hour < 21:
        return (
            "Market generally closed",
            "Sunday UTC; forex commonly reopens around 21:00–22:00 UTC.",
        )

    if weekday == 4 and hour >= 21:
        return (
            "Market generally closed",
            "Friday late UTC; forex commonly closes around 21:00–22:00 UTC.",
        )

    return (
        "Market schedule may be open",
        "Hours vary by broker and instrument. Check current availability.",
    )


# --------------------------------------------------
# Price formatting and pip settings
# --------------------------------------------------
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


# --------------------------------------------------
# Trade planning and strict risk checks
# --------------------------------------------------
def create_trade_plan(
    df: pd.DataFrame,
    symbol: str,
    balance: float,
    risk_pct: float,
    pip_value_per_lot: float,
    min_rr: float = MIN_RR,
    spread_pips: float = 0.0,
    slippage_pips: float = 0.0,
):
    last = df.iloc[-1]

    close = float(last["close"])
    ema20 = float(last["ema20"])
    ema50 = float(last["ema50"])
    rsi = float(last["rsi14"])
    atr = float(last["atr14"])

    if not math.isfinite(atr) or atr <= 0:
        atr = float((df["high"] - df["low"]).tail(14).mean())

    if not math.isfinite(atr) or atr <= 0:
        atr = close * 0.001

    supplies, demands = find_zones(df)

    near_distance = max(atr * 0.75, close * 0.0001)

    nearest_demand = (
        min(demands, key=lambda z: abs(close - z["mid"]))
        if demands else None
    )

    nearest_supply = (
        min(supplies, key=lambda z: abs(close - z["mid"]))
        if supplies else None
    )

    bullish = ema20 > ema50 and close > ema20
    bearish = ema20 < ema50 and close < ema20

    buy_near_demand = (
        nearest_demand is not None
        and abs(close - nearest_demand["mid"]) <= near_distance
    )

    sell_near_supply = (
        nearest_supply is not None
        and abs(close - nearest_supply["mid"]) <= near_distance
    )

    decision = "WAIT"
    reasons = []
    entry = close
    stop = None
    target = None
    setup_zone = None

    pip_size = pip_size_for(symbol)
    friction_pips = (
        max(0.0, spread_pips) + max(0.0, slippage_pips)
    )

    risk_usd = balance * risk_pct / 100.0

    if bullish:
        reasons.append(
            "EMA20 is above EMA50 and price is above EMA20."
        )
    elif bearish:
        reasons.append(
            "EMA20 is below EMA50 and price is below EMA20."
        )
    else:
        reasons.append("EMA trend is mixed.")

    if 50 <= rsi <= 68:
        reasons.append(
            f"RSI(14) is {rsi:.1f}, within the bullish momentum band."
        )
    elif 32 <= rsi < 50:
        reasons.append(
            f"RSI(14) is {rsi:.1f}, within the bearish momentum band."
        )
    else:
        reasons.append(
            f"RSI(14) is {rsi:.1f}, outside the selected entry bands."
        )

    # BUY candidate.
    if bullish and 50 <= rsi <= 68 and buy_near_demand:
        decision = "BUY"
        setup_zone = nearest_demand

        stop = min(
            nearest_demand["low"],
            close - 0.8 * atr,
        )

        if stop >= entry:
            stop = entry - atr

        stop_pips = abs(entry - stop) / pip_size

        # Target includes the estimated cost on both sides of the ratio.
        required_target_pips = (
            min_rr * (stop_pips + friction_pips)
            + friction_pips
        )

        target = entry + max(
            required_target_pips * pip_size,
            atr,
        )

        reasons.append("Price is close to an estimated demand zone.")

    # SELL candidate.
    elif bearish and 32 <= rsi < 50 and sell_near_supply:
        decision = "SELL"
        setup_zone = nearest_supply

        stop = max(
            nearest_supply["high"],
            close + 0.8 * atr,
        )

        if stop <= entry:
            stop = entry + atr

        stop_pips = abs(stop - entry) / pip_size

        required_target_pips = (
            min_rr * (stop_pips + friction_pips)
            + friction_pips
        )

        target = entry - max(
            required_target_pips * pip_size,
            atr,
        )

        reasons.append("Price is close to an estimated supply zone.")

    else:
        reasons.append(
            "The complete trend, momentum and nearby-zone conditions "
            "are not all met. No entry is suggested."
        )

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
        "friction_pips": friction_pips,
        "estimated_risk_usd": None,
        "planned_reward_usd": None,
        "planned_net_rr": None,
        "zone": setup_zone,
        "supplies": supplies,
        "demands": demands,
    }

    if decision in ("BUY", "SELL") and stop is not None and target is not None:
        stop_distance = abs(entry - stop)
        target_distance = abs(target - entry)

        stop_pips = stop_distance / pip_size
        target_pips = target_distance / pip_size

        effective_risk_pips = stop_pips + friction_pips
        risk_per_lot = effective_risk_pips * pip_value_per_lot

        if (
            not math.isfinite(risk_per_lot)
            or risk_per_lot <= 0
            or not math.isfinite(pip_value_per_lot)
            or pip_value_per_lot <= 0
        ):
            result["decision"] = "NO TRADE"
            result["reasons"].append(
                "Position sizing could not be calculated safely."
            )

        else:
            raw_lots = risk_usd / risk_per_lot

            # Simulation profile: 0.01 lot minimum and 0.01-lot steps.
            lots = math.floor((raw_lots + 1e-12) / 0.01) * 0.01
            lots = round(lots, 2)

            estimated_risk = (
                effective_risk_pips * pip_value_per_lot * lots
            )

            # Estimated target reward after the same cost allowance.
            reward_pips_after_costs = max(
                0.0, target_pips - friction_pips
            )

            planned_reward = (
                reward_pips_after_costs * pip_value_per_lot * lots
            )

            planned_net_rr = (
                planned_reward / estimated_risk
                if estimated_risk > 0 else 0.0
            )

            result.update({
                "stop_pips": stop_pips,
                "target_pips": target_pips,
                "effective_risk_pips": effective_risk_pips,
                "lots": lots,
                "units": (
                    lots * 100
                    if symbol == "XAU/USD"
                    else lots * 100000
                ),
                "estimated_risk_usd": estimated_risk,
                "planned_reward_usd": planned_reward,
                "planned_net_rr": planned_net_rr,
            })

            # Fail closed: reject unsafe or insufficient setups.
            if lots < 0.01:
                result["decision"] = "NO TRADE"
                result["reasons"].append(
                    "The calculated position is below the minimum "
                    "0.01 lot and cannot be rounded up safely."
                )

            elif estimated_risk > risk_usd + 1e-9:
                result["decision"] = "NO TRADE"
                result["reasons"].append(
                    f"Estimated risk of ${estimated_risk:.2f} exceeds "
                    f"the configured ${risk_usd:.2f} risk budget."
                )

            elif planned_net_rr + 1e-9 < min_rr:
                result["decision"] = "NO TRADE"
                result["reasons"].append(
                    f"Estimated net reward-to-risk of 1:{planned_net_rr:.2f} "
                    f"is below the required 1:{min_rr:.1f}."
                )

    # Do not expose executable-looking levels for rejected setups.
    if result["decision"] == "NO TRADE":
        result["entry"] = None
        result["stop"] = None
        result["target"] = None
        result["lots"] = None
        result["units"] = None

    return result


# --------------------------------------------------
# User interface
# --------------------------------------------------
st.title("📈 Forex AI Analyst")

st.caption(
    "Rule-based technical analysis • Estimated supply/demand zones • "
    "Exness Standard simulation profile • Paper trading only"
)

status, status_note = market_status_utc()

if status == "Market generally closed":
    st.warning(
        f"**{status}** — {status_note} "
        "Historical analysis may still work if data is available."
    )
else:
    st.info(f"**{status}** — {status_note}")

st.warning(
    "Paper trading only. This application does not connect to a broker "
    "or place orders. Signals are heuristic, not financial advice. "
    "Supply/demand zones are estimates based on historical price swings."
)

st.caption(
    "The broker profile is a simulation baseline, not a verified live "
    "account configuration. Confirm your broker's actual contract sizes, "
    "minimum volume, spreads, pip values and execution conditions."
)


# --------------------------------------------------
# Sidebar settings
# --------------------------------------------------
with st.sidebar:
    st.header("Analysis settings")

    symbol = st.selectbox("Instrument", SYMBOLS, index=0)
    interval = st.selectbox("Timeframe", INTERVALS, index=2)

    candle_count = st.select_slider(
        "Historical candles",
        options=[100, 200, 300, 500],
        value=200,
    )

    st.divider()
    st.subheader("Paper account")

    balance = st.number_input(
        "Account balance (USD)",
        min_value=1.0,
        value=DEFAULT_BALANCE,
        step=10.0,
    )

    risk_pct = st.number_input(
        "Risk per trade (%)",
        min_value=0.1,
        max_value=2.0,
        value=DEFAULT_RISK_PCT,
        step=0.1,
        help="Maximum configured risk is capped at 2% of the account.",
    )

    risk_pct = min(float(risk_pct), 2.0)

    st.caption(
        f"Maximum planned risk: "
        f"${balance * risk_pct / 100.0:.2f}"
    )

    st.subheader("Simulation cost assumptions")

    st.caption(
        "These are editable estimates, not live broker quotes."
    )

    if symbol == "XAU/USD":
        pip_value_per_lot = 1.0
        default_spread_pips = 3.0

    elif "JPY" in symbol:
        pip_value_per_lot = 6.7
        default_spread_pips = 1.5

    else:
        pip_value_per_lot = (
            10.0 if symbol.endswith("/USD") else 7.0
        )
        default_spread_pips = 1.0

    st.caption(
        f"Estimated pip value: ${pip_value_per_lot:.2f} per pip "
        "per standard lot. Some instruments require conversion "
        "using current exchange rates."
    )

    spread_pips = st.number_input(
        "Estimated spread (pips)",
        min_value=0.0,
        value=float(default_spread_pips),
        step=0.1,
    )

    slippage_pips = st.number_input(
        "Slippage allowance (pips)",
        min_value=0.0,
        value=0.2,
        step=0.1,
    )

    st.caption(
        "The data feed is Twelve Data, not your broker's execution feed. "
        "The selected costs may differ from actual trading conditions."
    )


# --------------------------------------------------
# Analyze button
# --------------------------------------------------
if st.button(
    "Analyze market",
    type="primary",
    use_container_width=True,
):

    try:
        api_key = st.secrets.get("TWELVE_DATA_API_KEY", "")

        if not api_key:
            st.error(
                "API key not found. Open your Streamlit Cloud app's "
                "Settings → Secrets and ensure TWELVE_DATA_API_KEY "
                "is configured. Never put the key in GitHub or app.py."
            )
            st.stop()

        with st.spinner(
            f"Fetching {candle_count} candles for {symbol} ({interval})..."
        ):
            candles = fetch_candles(
                symbol,
                interval,
                int(candle_count),
                api_key,
            )

            candles = add_indicators(candles)

            plan = create_trade_plan(
                candles,
                symbol,
                float(balance),
                float(risk_pct),
                float(pip_value_per_lot),
                min_rr=MIN_RR,
                spread_pips=float(spread_pips),
                slippage_pips=float(slippage_pips),
            )

        latest = candles.iloc[-1]

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "Latest close",
            format_price(float(latest["close"]), symbol),
        )

        c2.metric(
            "EMA 20",
            format_price(float(latest["ema20"]), symbol),
        )

        c3.metric(
            "EMA 50",
            format_price(float(latest["ema50"]), symbol),
        )

        c4.metric(
            "RSI (14)",
            f"{float(latest['rsi14']):.1f}",
        )

        st.subheader("Trade analysis")

        decision = plan["decision"]

        if decision == "BUY":
            st.success("BUY setup candidate — paper trading only")

        elif decision == "SELL":
            st.error("SELL setup candidate — paper trading only")

        elif decision == "NO TRADE":
            st.error("NO TRADE — a risk or reward rule rejected the setup")

        else:
            st.info("WAIT — no complete technical setup right now")

        for reason in plan["reasons"]:
            st.write(f"• {reason}")

        # Display proposed levels only for accepted candidates.
        if decision in ("BUY", "SELL") and plan["entry"] is not None:

            t1, t2, t3, t4 = st.columns(4)

            t1.metric(
                "Indicative entry",
                format_price(plan["entry"], symbol),
            )

            t2.metric(
                "Stop-loss",
                format_price(plan["stop"], symbol),
            )

            t3.metric(
                "Take-profit",
                format_price(plan["target"], symbol),
            )

            net_rr = plan["planned_net_rr"]

            t4.metric(
                "Estimated net R:R",
                f"1:{net_rr:.2f}",
            )

            p1, p2, p3 = st.columns(3)

            p1.metric(
                "Stop distance",
                f"{plan['stop_pips']:.1f} pips / points",
            )

            p2.metric(
                "Estimated position",
                f"{plan['lots']:.2f} lots",
            )

            p3.metric(
                "Estimated risk",
                f"${plan['estimated_risk_usd']:.2f}",
            )

            st.write(
                f"Estimated reward after the configured cost allowance: "
                f"**${plan['planned_reward_usd']:.2f}**."
            )

            st.caption(
                f"Approximate units: {plan['units']:,.0f}. "
                "Actual pip value, contract size, spread, slippage, "
                "commission, swaps and execution can differ."
            )

        else:
            st.write(
                f"Paper account: **${balance:.2f}** · "
                f"risk setting: **{risk_pct:.1f}%** · "
                f"maximum planned risk: "
                f"**${plan['risk_usd']:.2f}**."
            )

            if plan["planned_net_rr"] is not None:
                st.write(
                    f"Rejected setup's estimated net R:R: "
                    f"**1:{plan['planned_net_rr']:.2f}**."
                )

        # --------------------------------------------------
        # Candlestick chart
        # --------------------------------------------------
        st.subheader("Candlestick chart and estimated zones")

        fig = go.Figure()

        fig.add_trace(
            go.Candlestick(
                x=candles["datetime"],
                open=candles["open"],
                high=candles["high"],
                low=candles["low"],
                close=candles["close"],
                name=symbol,
            )
        )

        fig.add_trace(
            go.Scatter(
                x=candles["datetime"],
                y=candles["ema20"],
                mode="lines",
                name="EMA 20",
            )
        )

        fig.add_trace(
            go.Scatter(
                x=candles["datetime"],
                y=candles["ema50"],
                mode="lines",
                name="EMA 50",
            )
        )

        x_start = candles["datetime"].iloc[0]
        x_end = candles["datetime"].iloc[-1]

        for zone in plan["demands"]:
            fig.add_shape(
                type="rect",
                xref="x",
                yref="y",
                x0=x_start,
                x1=x_end,
                y0=zone["low"],
                y1=zone["high"],
                fillcolor="rgba(0, 180, 100, 0.10)",
                line=dict(width=0),
                layer="below",
            )

        for zone in plan["supplies"]:
            fig.add_shape(
                type="rect",
                xref="x",
                yref="y",
                x0=x_start,
                x1=x_end,
                y0=zone["low"],
                y1=zone["high"],
                fillcolor="rgba(220, 60, 60, 0.10)",
                line=dict(width=0),
                layer="below",
            )

        if decision in ("BUY", "SELL") and plan["entry"] is not None:
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
            height=650,
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

        # --------------------------------------------------
        # Zone tables
        # --------------------------------------------------
        zone_col1, zone_col2 = st.columns(2)

        with zone_col1:
            st.markdown("**Estimated demand zones**")

            if plan["demands"]:
                st.dataframe(
                    pd.DataFrame([
                        {
                            "Zone low": format_price(z["low"], symbol),
                            "Zone high": format_price(z["high"], symbol),
                        }
                        for z in plan["demands"]
                    ]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.write("No demand zones detected in this sample.")

        with zone_col2:
            st.markdown("**Estimated supply zones**")

            if plan["supplies"]:
                st.dataframe(
                    pd.DataFrame([
                        {
                            "Zone low": format_price(z["low"], symbol),
                            "Zone high": format_price(z["high"], symbol),
                        }
                        for z in plan["supplies"]
                    ]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.write("No supply zones detected in this sample.")

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
            "Method: EMA trend, RSI momentum and approximate swing zones. "
            "The model has not been validated or backtested. The calculated "
            "reward-to-risk is an estimate under the selected cost assumptions, "
            "not a guarantee of fills or profits."
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
    st.info(
        "Choose an instrument and timeframe, then click "
        "**Analyze market** to load candles and generate a "
        "rule-based paper-trading analysis."
    )


st.divider()

st.caption(
    "Forex AI Analyst • Educational paper-trading prototype • "
    "No real-money order execution"
)

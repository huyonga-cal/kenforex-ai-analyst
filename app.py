
import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go

st.set_page_config(
    page_title="Forex AI Analyst",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Forex AI Analyst")
st.caption("Live market data • Candlestick charts • Technical indicators")

# Read the API key from Streamlit Secrets.
try:
    API_KEY = st.secrets["TWELVE_DATA_API_KEY"]
except Exception:
    API_KEY = ""

MARKETS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF",
    "AUD/USD", "NZD/USD", "USD/CAD", "EUR/GBP",
    "EUR/JPY", "GBP/JPY", "XAU/USD",
]

INTERVALS = {
    "1 minute": "1min",
    "5 minutes": "5min",
    "15 minutes": "15min",
    "30 minutes": "30min",
    "1 hour": "1h",
    "2 hours": "2h",
    "4 hours": "4h",
    "1 day": "1day",
}


@st.cache_data(ttl=60, show_spinner=False)
def fetch_candles(symbol, interval, count):
    response = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": symbol,
            "interval": interval,
            "outputsize": count,
            "apikey": API_KEY,
            "format": "JSON",
            "timezone": "UTC",
        },
        timeout=25,
    )
    response.raise_for_status()
    result = response.json()

    if result.get("status") == "error" or "values" not in result:
        message = result.get(
            "message",
            "No market candles were returned.",
        )
        raise ValueError(message)

    df = pd.DataFrame(result["values"])
    df["datetime"] = pd.to_datetime(
        df["datetime"], errors="coerce", utc=True
    )

    for column in ["open", "high", "low", "close"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(
        subset=["datetime", "open", "high", "low", "close"]
    )
    df = df.sort_values("datetime").reset_index(drop=True)

    if df.empty:
        raise ValueError("The API returned no usable candles.")

    return df


def add_indicators(df):
    df = df.copy()
    df["EMA 20"] = df["close"].ewm(
        span=20, adjust=False
    ).mean()
    df["EMA 50"] = df["close"].ewm(
        span=50, adjust=False
    ).mean()

    change = df["close"].diff()
    gain = change.clip(lower=0)
    loss = -change.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / 14, min_periods=14, adjust=False
    ).mean()

    relative_strength = avg_gain / avg_loss.replace(0, float("nan"))
    df["RSI 14"] = 100 - (100 / (1 + relative_strength))
    return df


if not API_KEY:
    st.error(
        "The API key is missing. Open App settings → Secrets "
        "and add TWELVE_DATA_API_KEY."
    )
    st.stop()

with st.sidebar:
    st.header("Analysis settings")
    symbol = st.selectbox("Market", MARKETS)
    interval_label = st.selectbox(
        "Timeframe", list(INTERVALS.keys()), index=2
    )
    count = st.selectbox(
        "Historical candles", [30, 100, 200, 300, 500], index=2
    )

    analyze = st.button("🔍 Analyze market", type="primary")

st.info(
    "Market data is requested when you click Analyze market. "
    "Results are cached for up to 60 seconds."
)

if analyze:
    try:
        with st.spinner(f"Fetching {symbol} market data..."):
            candles = fetch_candles(
                symbol, INTERVALS[interval_label], count
            )
            candles = add_indicators(candles)

        latest = candles.iloc[-1]
        previous = candles.iloc[-2] if len(candles) > 1 else latest

        price_change = latest["close"] - previous["close"]

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Latest close",
            f"{latest['close']:,.5f}",
            f"{price_change:+.5f}",
        )
        c2.metric(
            "EMA 20",
            f"{latest['EMA 20']:,.5f}",
        )
        c3.metric(
            "RSI 14",
            f"{latest['RSI 14']:.2f}"
            if pd.notna(latest["RSI 14"])
            else "Not enough data",
        )

        chart = go.Figure()
        chart.add_trace(
            go.Candlestick(
                x=candles["datetime"],
                open=candles["open"],
                high=candles["high"],
                low=candles["low"],
                close=candles["close"],
                name=symbol,
            )
        )
        chart.add_trace(
            go.Scatter(
                x=candles["datetime"],
                y=candles["EMA 20"],
                name="EMA 20",
            )
        )
        chart.add_trace(
            go.Scatter(
                x=candles["datetime"],
                y=candles["EMA 50"],
                name="EMA 50",
            )
        )
        chart.update_layout(
            title=f"{symbol} · {interval_label}",
            height=600,
            xaxis_rangeslider_visible=False,
            margin=dict(l=10, r=10, t=50, b=10),
        )
        st.plotly_chart(chart, use_container_width=True)

        st.subheader("Recent market candles")
        st.dataframe(
            candles[
                ["datetime", "open", "high", "low", "close",
                 "EMA 20", "EMA 50", "RSI 14"]
            ].tail(10).sort_values(
                "datetime", ascending=False
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            "Times are displayed in UTC. Data availability and "
            "refresh frequency depend on your Twelve Data plan."
        )

    except requests.RequestException:
        st.error(
            "Could not connect to Twelve Data. Check the connection "
            "and try again."
        )
    except ValueError as error:
        st.error(f"Market data error: {error}")
    except Exception as error:
        st.error(f"Unexpected error: {type(error).__name__}: {error}")

else:
    st.subheader("Ready to analyze")
    st.write(
        "Choose a market and timeframe from the sidebar, "
        "then click Analyze market to load its candles."
    )

st.divider()
st.caption(
    "Educational market analysis only. This version does not "
    "generate validated trade signals or place real trades."
)


import streamlit as st

st.set_page_config(
    page_title="Forex AI Analyst",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Forex AI Analyst")
st.subheader("Your personal market analysis workspace")

st.success("Your application is running!")

st.markdown("""
Welcome to your Forex AI Analyst.

From here, we will build:
- Forex and XAU/USD market analysis
- Multiple timeframe selection
- Supply and demand zones
- BUY, SELL, WAIT and NO TRADE signals
- Entry, stop-loss and take-profit planning
- Paper trading and a persistent trade journal
""")

market = st.selectbox(
    "Choose a market",
    ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"],
)

timeframe = st.selectbox(
    "Choose a timeframe",
    ["1 minute", "5 minutes", "15 minutes", "1 hour", "4 hours", "1 day"],
)

st.write(f"Selected market: **{market}**")
st.write(f"Selected timeframe: **{timeframe}**")

st.info("Next, we will connect Twelve Data and build the analysis feature.")


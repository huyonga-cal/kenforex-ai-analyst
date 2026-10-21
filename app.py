
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
APP_VERSION = "knowledge-v3"
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


# -------------------- Structured knowledge library ----------
# These are documented hypotheses and analysis rules, not claims of predictive certainty.
KNOWLEDGE_ITEMS = [
    {"id":"macro_rates_relative","domain":"Fundamentals & macro","title":"Relative interest-rate expectations","description":"Exchange rates respond to the relative path of expected monetary policy, not only the latest policy rate.","determinants":"Rate differentials; forward guidance; inflation persistence; growth and labour data; market pricing before the event.","required_data":"Central-bank statements, policy rates, reputable yield data, dated economic releases and expectations where available.","rules":"Compare both currencies in the pair. Distinguish a change in expectations from information already priced in.","failure_conditions":"Do not infer a rate-path change from a headline alone; data may be stale, incomplete or already priced in.","validation_method":"Timestamp event snapshots and evaluate subsequent pair returns against a baseline with transaction costs."},
    {"id":"inflation_surprise","domain":"Fundamentals & macro","title":"Inflation releases and surprise","description":"Inflation matters through its effect on expected policy and real yields; the direction is context-dependent.","determinants":"Actual versus consensus; core versus headline; revisions; prior central-bank guidance; labour and growth context.","required_data":"Official release, timestamp, actual/consensus/prior values and source provenance.","rules":"Only label a surprise when comparable consensus data are available. Otherwise report the release without claiming a beat or miss.","failure_conditions":"A higher inflation print is not automatically bullish for a currency if growth, credibility or policy expectations dominate.","validation_method":"Test event-window reactions separately by event type and regime; avoid look-ahead bias."},
    {"id":"employment_growth","domain":"Fundamentals & macro","title":"Employment and growth releases","description":"Jobs, wages, GDP and activity data can shift expectations for growth and monetary policy.","determinants":"Surprise magnitude; revisions; wage/inflation components; unemployment; prevailing policy narrative.","required_data":"Official statistical release and consensus only when a trusted source provides it.","rules":"Explain which component changed and why it could matter; do not reduce complex releases to a single positive/negative keyword.","failure_conditions":"Conflicting components, revisions, or low-quality consensus can make a one-direction interpretation unreliable.","validation_method":"Measure event-window returns and volatility; report sample size and confidence intervals."},
    {"id":"central_bank_communication","domain":"Fundamentals & macro","title":"Central-bank communication","description":"Statements, minutes, speeches and press conferences may alter the expected policy path.","determinants":"Policy decision versus expectations; wording changes; voting split; guidance; credibility and prior positioning.","required_data":"Official central-bank source, publication time and the relevant previous statement for comparison.","rules":"Separate the decision, forward guidance and uncertainty. Cite source and timestamp in the analysis.","failure_conditions":"A keyword such as hawkish/dovish can miss context, sarcasm, caveats or market expectations.","validation_method":"Compare a transparent event classification with subsequent moves across multiple meetings."},
    {"id":"trend_structure","domain":"Technical & price action","title":"Trend and swing structure","description":"Sequences of swing highs/lows and price location help describe directional structure.","determinants":"Confirmed swing points; close versus prior structure; timeframe; trend persistence; range boundaries.","required_data":"Sufficient closed candles with consistent timestamps and price fields.","rules":"Distinguish a confirmed break from an intrabar wick. Keep timeframe and lookback explicit.","failure_conditions":"Swing labels are lookback-dependent and can change in real time; ranges create false breaks.","validation_method":"Define the swing algorithm before testing and evaluate out-of-sample with costs."},
    {"id":"ema_context","domain":"Technical & price action","title":"Moving-average context","description":"Moving averages smooth price and can summarise trend alignment, but lag price.","determinants":"EMA slope and ordering; price relative to averages; timeframe; recent volatility.","required_data":"Closed candles and a fixed EMA calculation method.","rules":"Treat EMA20/EMA50 as contextual evidence, not a standalone entry trigger or certainty score.","failure_conditions":"Whipsaws in ranges; lag after sharp reversals; sensitivity to timeframe and parameter choice.","validation_method":"Compare to simple baselines and test parameters on unseen chronological periods."},
    {"id":"rsi_momentum","domain":"Technical & price action","title":"RSI momentum and extension","description":"RSI describes recent momentum; extreme readings can persist in strong trends.","determinants":"RSI level and slope; price structure; trend regime; divergence quality; timeframe.","required_data":"Consistent close series and defined RSI period.","rules":"Interpret RSI in context. Do not assume overbought means an immediate sell or oversold means an immediate buy.","failure_conditions":"Strong trends can stay extreme; divergences may occur early or repeatedly.","validation_method":"Test RSI conditions within separately identified trend/range regimes."},
    {"id":"support_resistance","domain":"Technical & price action","title":"Support, resistance and zones","description":"Prior reaction areas can provide context for invalidation and target feasibility.","determinants":"Number and recency of reactions; zone width; approach momentum; timeframe; nearby opposing zones.","required_data":"OHLC candles and a documented, reproducible zone algorithm.","rules":"Label zones as estimates from price history, not proof of institutional orders. Check target space before approving a setup.","failure_conditions":"Zones are subjective, can be breached, and can be overfit to the chart.","validation_method":"Freeze zone rules and measure outcomes by distance, volatility and regime."},
    {"id":"breakout_quality","domain":"Technical & price action","title":"Breakout quality and false breaks","description":"A breakout may indicate expansion but can also be a liquidity sweep or failed move.","determinants":"Closed-bar confirmation; range width; volume/tick-volume limitations; retest; volatility; event timing.","required_data":"Closed OHLC candles and clear range boundaries; volume only if source quality is known.","rules":"Describe confirmation and invalidation explicitly. Do not treat a wick alone as confirmed acceptance beyond a level.","failure_conditions":"Low-liquidity hours, spread spikes, scheduled news and range-bound conditions.","validation_method":"Compare breakout definitions with a baseline and include spread/slippage assumptions."},
    {"id":"multi_timeframe","domain":"Technical & price action","title":"Multi-timeframe context","description":"Higher timeframes can contextualise a lower-timeframe setup without mechanically vetoing it.","determinants":"Trend agreement; nearby higher-timeframe levels; timeframe nesting; data freshness.","required_data":"Closed candles for entry and higher timeframes, with the same timezone discipline.","rules":"Report each timeframe separately and explain disagreement. Do not count correlated timeframes as independent proof.","failure_conditions":"Higher timeframe lag, overlapping data and false confidence from double-counting similar signals.","validation_method":"Compare aligned and non-aligned cases on separate chronological samples."},
    {"id":"atr_volatility","domain":"Regime & sessions","title":"Volatility and ATR","description":"ATR estimates recent range and helps contextualise stops and unusual conditions.","determinants":"ATR relative to price; ATR percentile; recent expansion/contraction; instrument and timeframe.","required_data":"Closed candles and consistent ATR calculation.","rules":"Use volatility to contextualise stop distance and market conditions, not to predict direction.","failure_conditions":"ATR lags sudden news shocks and does not guarantee future range or stop execution.","validation_method":"Bucket results by prior volatility regime without using future data to classify the bucket."},
    {"id":"market_regime","domain":"Regime & sessions","title":"Trend, range and transition regimes","description":"Strategies can behave differently in persistent trends, ranges and transitions.","determinants":"Swing progression; directional efficiency; volatility; breakout persistence; mean-reversion behaviour.","required_data":"Historical OHLC series and pre-defined regime classifier.","rules":"Identify regime using only information available at decision time; allow uncertain classifications.","failure_conditions":"Regime changes are gradual and labels can be unstable around transitions.","validation_method":"Report performance by regime and test classifier stability out of sample."},
    {"id":"session_liquidity","domain":"Regime & sessions","title":"Trading sessions and liquidity conditions","description":"Session timing can influence spreads, activity and volatility, but patterns vary by instrument and date.","determinants":"London/New York overlap; holidays; daylight-saving changes; instrument; current spread and event calendar.","required_data":"UTC timestamps, session calendar and ideally actual spread observations.","rules":"Preserve the existing UTC handling; convert only for display where explicitly needed. Do not assume every session is liquid.","failure_conditions":"Holiday sessions, DST transitions, rollover and broker-specific trading hours.","validation_method":"Measure spread and outcome distributions by session using timestamp-correct historical data."},
    {"id":"news_relevance","domain":"News & sentiment","title":"Headline relevance and source quality","description":"News context is useful only when the story is relevant to the currencies and reliably sourced.","determinants":"Publisher credibility; publication time; named currency/central bank; event type; duplicate stories.","required_data":"Headline, URL, publisher, publication timestamp and available summary.","rules":"Deduplicate URLs, show source and timestamp, distinguish official releases from secondary reporting.","failure_conditions":"Headline-only classification can miss negation, context, stale articles and duplicate syndication.","validation_method":"Audit sampled classifications against the linked article and track false-relevance rate."},
    {"id":"news_surprise","domain":"News & sentiment","title":"News surprise versus expectations","description":"Markets often respond to the difference between released information and what was expected.","determinants":"Consensus quality; actual/prior/revised data; policy narrative; pre-release positioning.","required_data":"A reliable consensus source and official release; otherwise mark surprise unavailable.","rules":"Never invent consensus or infer a surprise from a headline sentiment score.","failure_conditions":"Consensus may be unavailable, inconsistent or not representative of market pricing.","validation_method":"Store source snapshots at release time and evaluate without revised/look-ahead data."},
    {"id":"event_risk","domain":"News & sentiment","title":"Scheduled event and gap risk","description":"Major releases can widen spreads, increase slippage and invalidate ordinary stop assumptions.","determinants":"Event importance; instrument exposure; time to release; current volatility; broker conditions.","required_data":"Reliable dated event calendar and current market data.","rules":"When a trusted calendar is unavailable, disclose that event-risk coverage is incomplete rather than implying the calendar is clear.","failure_conditions":"Unexpected announcements, calendar changes and source delays.","validation_method":"Compare paper outcomes around known events with ordinary periods, including cost stress tests."},
    {"id":"correlation_exposure","domain":"Cross-market relationships","title":"Currency and position concentration","description":"Several different pairs can express nearly the same underlying currency exposure.","determinants":"Shared base/quote currencies; current correlations; open trade direction; volatility and position size.","required_data":"Open paper trades and aligned historical returns; correlation windows documented.","rules":"Flag overlapping currency exposure; do not treat pair names as independent diversification.","failure_conditions":"Correlations vary over time and historical correlation is not a guarantee.","validation_method":"Stress portfolio drawdown during correlation spikes and common-currency moves."},
    {"id":"gold_context","domain":"Cross-market relationships","title":"Gold and macro context","description":"Gold can respond to real yields, dollar moves, risk demand and liquidity; relationships are conditional.","determinants":"Real-yield changes; USD; risk events; central-bank demand; positioning and liquidity.","required_data":"Gold prices and reliable macro series if used; avoid assuming unavailable inputs.","rules":"Present these as possible explanatory factors unless the relevant data are actually connected.","failure_conditions":"Gold may rise or fall with the dollar depending on the dominant driver and horizon.","validation_method":"Test conditional relationships by regime and report unstable periods."},
    {"id":"position_sizing","domain":"Risk & trade mechanics","title":"Position sizing from stop distance","description":"Position size should be derived from the permitted dollar risk and instrument-specific loss per unit.","determinants":"Equity/balance; risk cap; stop distance; pip/point value; contract size; conversion rate.","required_data":"Correct contract specifications, quote conversion and explicit account currency.","rules":"Round size down; reject the trade if the minimum size exceeds the risk cap. Display assumptions and uncertainty.","failure_conditions":"Approximate pip values, changing conversion rates, gaps and execution slippage.","validation_method":"Unit-test calculations across pairs, JPY crosses and XAU/USD against independently checked examples."},
    {"id":"net_rr_costs","domain":"Risk & trade mechanics","title":"Net reward-to-risk after friction","description":"Spread and slippage assumptions reduce reward and increase effective risk; gross ratios can overstate a setup.","determinants":"Entry/stop/target distances; spread; commissions; slippage; swap if holding overnight.","required_data":"Instrument pip size/value and explicit transaction-cost assumptions.","rules":"Enforce a minimum estimated net R:R of 1:2 and reject invalid trade geometry. Clearly label estimated costs.","failure_conditions":"Costs can exceed assumptions, targets may not fill, and gaps can exceed stops.","validation_method":"Stress test cost assumptions and compare planned versus simulated realised outcomes."},
    {"id":"portfolio_drawdown","domain":"Risk & trade mechanics","title":"Drawdown and cumulative exposure","description":"A sequence of individually small risks can still produce meaningful cumulative drawdown.","determinants":"Concurrent trades; correlated exposure; loss streaks; equity changes; open risk.","required_data":"Persisted trade ledger with realised P/L and open-risk estimates.","rules":"Calculate realised balance from initial capital plus recorded P/L; never silently reset history. Keep risk cap hard-limited to 2%.","failure_conditions":"Incomplete records, inconsistent P/L sign conventions or missing open-risk estimates.","validation_method":"Reconcile ledger totals and simulate drawdown sequences and correlated losses."},
    {"id":"expectancy","domain":"Quant research & learning","title":"Expectancy and sample size","description":"Win rate alone is insufficient; average win, average loss, costs and sample uncertainty matter.","determinants":"Win/loss sizes; transaction costs; number of trades; regime mix; outliers.","required_data":"Complete trade outcomes with consistent realised P/L and cost treatment.","rules":"Report expectancy alongside sample count and drawdown; avoid strong conclusions from tiny samples.","failure_conditions":"Selection bias, survivorship bias, incomplete records and changing strategy rules.","validation_method":"Use confidence intervals, bootstrap or robust repeated samples where appropriate."},
    {"id":"backtest_integrity","domain":"Quant research & learning","title":"Chronological validation and leakage prevention","description":"Strategy assessment must avoid using future information in feature generation, tuning or validation.","determinants":"Time ordering; feature timestamps; train/validation separation; revisions; execution assumptions.","required_data":"Versioned historical dataset, code/parameter versions and reproducible fills/cost model.","rules":"Keep a final untouched test period; tune only on earlier data; record all assumptions and sample counts.","failure_conditions":"Look-ahead bias, repeated peeking at test data, optimistic fills and overfitting.","validation_method":"Walk-forward or chronological holdout testing and comparison against the unchanged baseline."},
    {"id":"strategy_change_gate","domain":"Quant research & learning","title":"Strategy-change approval gate","description":"A candidate change should earn approval through reproducible evidence, not a single winning streak.","determinants":"Out-of-sample expectancy; drawdown; trade count; cost sensitivity; stability across regimes.","required_data":"Baseline and candidate metrics measured on the same unseen sample and same costs.","rules":"Persist candidate hypotheses; keep status PENDING until reviewed; do not auto-deploy or raise risk limits.","failure_conditions":"Small samples, metric cherry-picking, unstable gains and incompatible risk profiles.","validation_method":"Require documented method, sufficient sample, out-of-sample results and human approval."},
    {"id":"confidence_calibration","domain":"Quant research & learning","title":"Confidence is not win probability","description":"A heuristic score expresses weighted evidence, not a calibrated probability of success.","determinants":"Score construction; correlated factors; historical calibration; regime and sample stability.","required_data":"Transparent factor contributions and, for probability claims, a sufficiently large labelled dataset.","rules":"Display the evidence score and its interpretation; never translate it into a win probability without calibration.","failure_conditions":"Double-counting correlated indicators and treating score magnitude as statistical certainty.","validation_method":"If probability estimates are introduced, test calibration, Brier score and out-of-sample reliability."},
    {"id":"data_quality","domain":"Data quality & operations","title":"Freshness, completeness and candle integrity","description":"Analysis quality depends on correct, sufficiently complete, consistently timestamped inputs.","determinants":"Missing bars; duplicate timestamps; forming candles; provider outages; symbol mapping.","required_data":"Provider response metadata, OHLC validation and explicit candle timestamps.","rules":"Exclude the newest possibly forming candle as currently implemented; fail safely on malformed or insufficient data.","failure_conditions":"Stale API responses, rate limits, symbol differences and gaps around weekends/holidays.","validation_method":"Add deterministic tests for missing bars, duplicate timestamps, invalid OHLC and stale inputs."},
    {"id":"execution_slippage","domain":"Risk & trade mechanics","title":"Execution and slippage assumptions","description":"Paper fills are simplified and cannot perfectly reproduce live broker execution.","determinants":"Spread, liquidity, volatility, order type, market gaps and broker-specific contract rules.","required_data":"Explicit simulation assumptions; broker specs only when independently confirmed.","rules":"Label fills and pip values as estimates. This app must never submit live orders.","failure_conditions":"No paper model can guarantee live fills, stop execution or exact costs.","validation_method":"Run sensitivity scenarios and compare assumptions with available demo-account observations."},
    {"id":"risk_of_ruin","domain":"Risk & trade mechanics","title":"Loss streak and risk-of-ruin awareness","description":"Even strategies with positive observed expectancy can experience long losing streaks.","determinants":"Risk per trade; expectancy uncertainty; win/loss distribution; correlated positions; drawdown limit.","required_data":"Reliable historical outcomes and risk sizing records.","rules":"Keep risk limits fixed and make drawdown visible; do not increase risk after losses to recover them.","failure_conditions":"Historical distribution may not persist and small samples understate tail risk.","validation_method":"Monte Carlo resampling with caveats, stress scenarios and out-of-sample validation."},
    {"id":"human_review","domain":"Governance & discipline","title":"Human approval and audit trail","description":"The analyst should explain its reasoning and let the user decide whether to open a paper trade.","determinants":"Evidence quality; risk checks; data freshness; user confirmation; logged signal version.","required_data":"Persisted signal, risk calculations, notes and approval event.","rules":"No automatic execution; require explicit approval for each paper trade and preserve the record of what was reviewed.","failure_conditions":"UI confirmation must not be mistaken for broker validation or guaranteed performance.","validation_method":"Audit that each opened paper trade links to a signal and passes hard risk checks."},
    {"id":"conflicting_evidence","domain":"Reasoning & uncertainty","title":"Conflicting evidence and abstention","description":"When evidence conflicts or data is missing, an honest WAIT can be better than forcing a directional call.","determinants":"Opposing indicators; timeframe disagreement; stale news; uncertain structure; cost feasibility.","required_data":"Factor-level evidence, conflicts, higher-timeframe context and data-quality status.","rules":"Show supporting and opposing evidence separately. Missing information lowers certainty and must not be filled with invented facts.","failure_conditions":"Rigid thresholds and correlated signals can create false confidence.","validation_method":"Track WAIT frequency and compare outcomes only with well-defined counterfactuals."},
    {"id":"documentation_provenance","domain":"Governance & discipline","title":"Source provenance and reproducibility","description":"Every external claim should be traceable to a source, timestamp and version of the analysis.","determinants":"Source URL; publication/fetch times; provider; strategy version; data and code changes.","required_data":"Stored source links, UTC timestamps, strategy version and immutable trade/signal IDs.","rules":"Preserve citations and analysis snapshots where feasible; distinguish source publication time from fetch time.","failure_conditions":"Feeds can update or disappear; a URL alone may not preserve the original article content.","validation_method":"Re-run analyses from stored inputs when possible and audit source links and version records."},
]


# -------------------- Visual system -------------------------

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@400;500;600&display=swap');

:root {
  --paper: #0A0E14;
  --surface: #111823;
  --ink: #E8EDF4;
  --muted: #98A4B5;
  --line: #273244;
  --copper: #D7AE62;
  --green: #48C99A;
  --red: #FF7777;
}
html, body, [class*="css"] {
  font-family: 'DM Sans', sans-serif;
}
.stApp {
  background: radial-gradient(ellipse at 18% 0%, #172130 0%, #0A0E14 52%);
  color: var(--ink);
}
[data-testid="stHeader"] {
  background: rgba(10,14,20,.94);
}
[data-testid="stSidebar"] {
  background: #0D131D;
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
  border-radius: 10px;
  padding: 16px 18px;
  box-shadow: 0 10px 30px rgba(0,0,0,.12);
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
  border-radius: 10px;
}
[data-testid="stExpander"] {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
}
.stButton > button, .stDownloadButton > button {
  border-radius: 8px;
  border: 1px solid #D7AE62;
  background: linear-gradient(135deg, #D7AE62, #A97B37);
  color: #10141B;
  font-weight: 600;
  min-height: 2.65rem;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: #F1D18A;
  background: #F1D18A;
  color: #10141B;
}
[data-testid="stDataFrame"] {
  border: 1px solid var(--line);
}
[data-baseweb="select"] > div,
[data-baseweb="input"] > div,
[data-baseweb="textarea"] > div {
  background: #111823;
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
  background: linear-gradient(135deg, #151F2D, #0E141D);
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  padding: 3rem 2rem;
  border-radius: 16px;
}
[data-testid="stTabs"] button { color: #AAB5C4; }
[data-testid="stTabs"] button[aria-selected="true"] { color: #E7C57D; border-bottom-color: #D7AE62; }
[data-testid="stAlert"] { border-radius: 10px; }
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
.knowledge-card { background: #111823; border: 1px solid #273244; border-radius: 12px; padding: 1rem; margin: .4rem 0; }
.knowledge-domain { color: #D7AE62; font-family: 'DM Mono', monospace; font-size: .7rem; text-transform: uppercase; letter-spacing: .12em; }
.hero-stat { background: #111823; border: 1px solid #273244; border-radius: 12px; padding: 1rem; }
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
        """CREATE TABLE IF NOT EXISTS knowledge_records (
            id TEXT PRIMARY KEY,
            domain TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            determinants TEXT NOT NULL,
            required_data TEXT NOT NULL,
            rules TEXT NOT NULL,
            failure_conditions TEXT NOT NULL,
            validation_method TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DOCUMENTED',
            user_notes TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
        # Seed the knowledge catalogue without overwriting user notes/statuses.
        for item in KNOWLEDGE_ITEMS:
            conn.execute(text("""
                INSERT INTO knowledge_records(
                    id,domain,title,description,determinants,required_data,rules,
                    failure_conditions,validation_method,status,user_notes
                ) VALUES (
                    :id,:domain,:title,:description,:determinants,:required_data,:rules,
                    :failure_conditions,:validation_method,'DOCUMENTED',''
                ) ON CONFLICT(id) DO NOTHING
            """), item)
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

    directionally_valid = (
        (decision == "BUY" and stop < entry < target)
        or (decision == "SELL" and target < entry < stop)
    )
    if risk_distance <= 0 or pip <= 0 or not all(
        math.isfinite(v) for v in (entry, stop, target)
    ) or not directionally_valid:
        plan["decision"] = "NO TRADE"
        plan["reasons"].append(
            "A directionally valid entry, stop and target could not be constructed."
        )
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
st.caption("Market intelligence · Evidence-weighted analysis · Knowledge library · Paper trading only")
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

tab_analysis, tab_setups, tab_news, tab_journal, tab_learning, tab_knowledge = st.tabs([
    "Market terminal", "Execution setups", "News & context", "Paper journal", "Strategy review", "Knowledge base"
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

        st.markdown("### Analyst reasoning & knowledge links")
        st.caption("The knowledge library explains how each factor is interpreted. Scores are heuristic evidence weights, not calibrated win probabilities.")
        reasoning_cols = st.columns(2)
        with reasoning_cols[0]:
            st.markdown("**Supporting evidence**")
            if plan["evidence"]:
                for item in plan["evidence"]:
                    st.markdown(f"- **{item['Factor']}** ({item['Score']:+.2f}) — {item['Interpretation']}")
            else:
                st.write("No strong supporting factors identified.")
        with reasoning_cols[1]:
            st.markdown("**Conflicts and cautions**")
            if plan["conflicts"]:
                for item in plan["conflicts"]:
                    st.markdown(f"- **{item['Factor']}** ({item['Score']:+.2f}) — {item['Interpretation']}")
            else:
                st.write("No explicit technical conflict recorded; this is not proof of low risk.")
        with st.expander("How the knowledge engine interprets this market", expanded=False):
            st.markdown("""
            - **Trend:** EMA alignment is contextual evidence and may lag.
            - **Momentum:** RSI is interpreted by regime; extreme values are not automatic reversal signals.
            - **Structure and location:** swing structure and estimated zones are hypotheses derived from historical prices, not proof of institutional activity.
            - **Volatility:** ATR helps contextualise distance and conditions; it does not predict direction.
            - **Higher timeframes:** disagreement is disclosed rather than used as an automatic veto.
            - **News:** headline keyword scores are weak context and cannot independently authorise a trade.
            - **Risk:** the hard risk budget and estimated net 1:2 minimum remain separate from directional analysis.
            """)

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

            approval_ok = (
                plan.get("decision") in ("BUY", "SELL")
                and plan.get("entry") is not None
                and plan.get("stop") is not None
                and plan.get("target") is not None
                and float(plan.get("estimated_risk_usd") or 0) <= float(plan.get("risk_usd") or 0) + 1e-9
                and float(plan.get("planned_net_rr") or 0) >= MIN_RR
                and float(plan.get("lots") or 0) >= 0.01
            )
            if engine is None:
                st.warning("Paper-trade approval is disabled until persistent database storage is configured.")
            elif not approval_ok:
                st.warning("This candidate does not pass every hard risk check and cannot be opened.")
            else:
                st.warning("Manual confirmation only. This records a simulated trade; it does not contact a broker.")
                confirm_trade = st.checkbox(
                    f"I approve opening this {plan['decision']} paper trade for {saved['symbol']}.",
                    key=f"approve_{saved.get('signal_id') or saved['created_at']}",
                )
                if st.button(
                    "Open paper trade",
                    type="primary",
                    use_container_width=True,
                    disabled=not confirm_trade,
                    key=f"open_paper_{saved.get('signal_id') or saved['created_at']}",
                ):
                    try:
                        db_execute("""
                            INSERT INTO paper_trades(
                                id,signal_id,symbol,direction,entry,stop,target,
                                risk_usd,planned_net_rr,outcome,notes
                            ) VALUES (
                                :id,:signal,:symbol,:direction,:entry,:stop,:target,
                                :risk,:rr,'OPEN',:notes
                            )
                        """, {
                            "id": str(uuid.uuid4()),
                            "signal": saved.get("signal_id"),
                            "symbol": saved["symbol"],
                            "direction": plan["decision"],
                            "entry": float(plan["entry"]),
                            "stop": float(plan["stop"]),
                            "target": float(plan["target"]),
                            "risk": float(plan["estimated_risk_usd"]),
                            "rr": float(plan["planned_net_rr"]),
                            "notes": "Manually approved paper trade. No broker order was sent.",
                        })
                        st.success("Paper trade recorded as OPEN. No live order was sent.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not open paper trade ({type(exc).__name__}).")

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


# -------------------- Execution setups tab -------------------

with tab_setups:
    st.markdown('<div class="editorial-kicker">THE SETUP / YOUR DECISION</div>', unsafe_allow_html=True)
    st.subheader("Execution workspace")
    st.caption("You choose the direction and whether to proceed. The analyst calculates the plan and flags risk. This records paper trades only; it never sends broker orders.")

    current = st.session_state.get("last_analysis")
    if not current:
        st.info("Run Analyse market first. The execution workspace will then use that analysis as its starting reference.")
    else:
        plan = current["plan"]
        symbol_now = current["symbol"]
        candles_now = current.get("candles")
        analysis_id = str(current.get("signal_id") or current.get("created_at") or symbol_now).replace(" ", "_")
        st.markdown(f"### {symbol_now} · {current['interval']} · latest assessment: **{plan.get('decision', 'WAIT')}**")
        st.write("The analyst's direction is advisory, not an instruction. You may inspect a BUY or SELL scenario even if the assessment is WAIT, but the interface will label that as a human-selected scenario rather than an analyst-qualified signal.")

        # Build neutral starter values when the analyst has no directional setup.
        reference_entry = float(plan.get("entry") or (float(candles_now['close'].iloc[-1]) if candles_now is not None and len(candles_now) else 0.0))
        atr_now = float(plan.get("atr") or 0.0)
        proposed_direction = plan.get("decision") if plan.get("decision") in ("BUY", "SELL") else "BUY"
        starter_stop_distance = max(atr_now, abs(reference_entry) * 0.001) if reference_entry > 0 else 0.0
        if proposed_direction == "BUY":
            starter_stop = float(plan.get("stop") or (reference_entry - 1.5 * starter_stop_distance))
            starter_target = float(plan.get("target") or (reference_entry + 2.0 * abs(reference_entry - starter_stop)))
        else:
            starter_stop = float(plan.get("stop") or (reference_entry + 1.5 * starter_stop_distance))
            starter_target = float(plan.get("target") or (reference_entry - 2.0 * abs(starter_stop - reference_entry)))

        with st.form(f"execution_form_{analysis_id}"):
            st.markdown("#### Define the scenario")
            direction = st.radio("Your proposed direction", ["BUY", "SELL"], index=0 if proposed_direction == "BUY" else 1, horizontal=True)
            e1, e2, e3 = st.columns(3)
            entry = e1.number_input("Entry price", min_value=0.00000001, value=max(0.00000001, reference_entry), format="%.8f", key=f"exec_entry_{analysis_id}")
            stop_default = starter_stop if direction == proposed_direction else (reference_entry - 1.5 * starter_stop_distance if direction == "BUY" else reference_entry + 1.5 * starter_stop_distance)
            risk_distance_default = abs(entry - stop_default)
            target_default = starter_target if direction == proposed_direction else (entry + 2 * risk_distance_default if direction == "BUY" else entry - 2 * risk_distance_default)
            stop = e2.number_input("Stop-loss", min_value=0.00000001, value=max(0.00000001, float(stop_default)), format="%.8f", key=f"exec_stop_{analysis_id}")
            target = e3.number_input("Take-profit", min_value=0.00000001, value=max(0.00000001, float(target_default)), format="%.8f", key=f"exec_target_{analysis_id}")
            friction_pips = st.number_input("Estimated total spread + slippage (pips)", min_value=0.0, value=float(plan.get("friction_pips") or 1.2), step=0.1, key=f"exec_friction_{analysis_id}")
            st.caption("You can edit entry, stop, target and cost assumptions. Lot size is calculated from the risk cap and rounded down to 0.01 lots. Pip value is an approximation, not a broker-verified quote.")
            calculate = st.form_submit_button("Calculate risk & review flags", type="primary", use_container_width=True)

        if calculate:
            st.session_state[f"execution_calc_{analysis_id}"] = {
                "direction": direction, "entry": float(entry), "stop": float(stop),
                "target": float(target), "friction_pips": float(friction_pips),
            }

        scenario = st.session_state.get(f"execution_calc_{analysis_id}")
        if scenario:
            direction = scenario["direction"]
            entry = float(scenario["entry"])
            stop = float(scenario["stop"])
            target = float(scenario["target"])
            friction_pips = float(scenario["friction_pips"])
            pip = pip_size_for(symbol_now)
            risk_distance = (entry - stop) if direction == "BUY" else (stop - entry)
            reward_distance = (target - entry) if direction == "BUY" else (entry - target)
            geometry_ok = risk_distance > 0 and reward_distance > 0 and all(math.isfinite(v) and v > 0 for v in (entry, stop, target))
            stop_pips = risk_distance / pip if geometry_ok else 0.0
            target_pips = reward_distance / pip if geometry_ok else 0.0
            effective_risk_pips = stop_pips + friction_pips if geometry_ok else 0.0
            balance_now = float(balance)
            risk_budget = balance_now * min(float(risk_pct), 2.0) / 100.0
            pip_value = float(plan.get("pip_value_per_lot") or 0.0)
            raw_lots = risk_budget / (effective_risk_pips * pip_value) if effective_risk_pips > 0 and pip_value > 0 else 0.0
            lots = math.floor((raw_lots + 1e-12) / 0.01) * 0.01
            estimated_risk = effective_risk_pips * pip_value * lots
            net_reward_pips = max(0.0, target_pips - friction_pips) if geometry_ok else 0.0
            estimated_reward = net_reward_pips * pip_value * lots
            net_rr = estimated_reward / estimated_risk if estimated_risk > 0 else 0.0
            direction_matches = plan.get("decision") == direction
            risk_ok = estimated_risk <= risk_budget + 1e-9 and lots >= 0.01
            rr_ok = net_rr >= MIN_RR
            geometry_direction_ok = geometry_ok and ((direction == "BUY" and stop < entry < target) or (direction == "SELL" and target < entry < stop))
            human_scenario = not direction_matches or plan.get("decision") not in ("BUY", "SELL")

            st.markdown("---")
            st.markdown("#### Calculated execution card")
            if not geometry_direction_ok:
                st.error("RED FLAG · Price geometry is invalid for the selected direction. Correct entry, stop-loss and take-profit before considering this scenario.")
            elif not risk_ok:
                st.error("RED FLAG · The risk budget or minimum lot-size check failed. Do not approve this calculated size.")
            elif not rr_ok:
                st.error(f"RED FLAG · Estimated net reward-to-risk is 1:{net_rr:.2f}; the required minimum is 1:2 after the entered friction estimate.")
            elif human_scenario:
                st.warning("AMBER FLAG · The numbers pass the basic mathematical checks, but this is your manually selected scenario, not a direction qualified by the analyst. Review the evidence and current price before deciding.")
            elif plan.get("conflicts"):
                st.warning("AMBER FLAG · Risk maths passes, but the analysis contains counterevidence. Read the conflicting factors before deciding.")
            else:
                st.success("No hard mathematical red flag detected under the current assumptions. This is not a prediction of success or a guarantee of execution.")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Stop distance", f"{stop_pips:.1f} pips" if geometry_ok else "Invalid")
            c2.metric("Target distance", f"{target_pips:.1f} pips" if geometry_ok else "Invalid")
            c3.metric("Calculated size", f"{lots:.2f} lots")
            c4.metric("Estimated net R:R", f"1:{net_rr:.2f}")
            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Risk budget", f"${risk_budget:.2f}")
            c6.metric("Estimated loss at SL", f"${estimated_risk:.2f}")
            c7.metric("Estimated gain at TP", f"${estimated_reward:.2f}")
            c8.metric("Cost assumption", f"{friction_pips:.1f} pips")
            st.caption(f"Pip value used: approximately ${pip_value:.2f}/pip/standard lot. Balance: ${balance_now:.2f}. Max risk setting: {min(float(risk_pct), 2.0):.2f}%. Estimated values exclude any costs not represented by the friction assumption and may differ from broker contract specifications.")

            check_rows = [
                {"Check": "Entry / SL / TP geometry", "Status": "PASS" if geometry_direction_ok else "RED FLAG", "Detail": "Stop and target are on the correct sides of entry." if geometry_direction_ok else "Selected direction requires a valid stop and target on opposite sides of entry."},
                {"Check": "Maximum risk budget", "Status": "PASS" if risk_ok else "RED FLAG", "Detail": f"Estimated loss ${estimated_risk:.2f} against budget ${risk_budget:.2f}; size rounded down to 0.01 lots."},
                {"Check": "Minimum net R:R", "Status": "PASS" if rr_ok else "RED FLAG", "Detail": f"Estimated net ratio 1:{net_rr:.2f}; required at least 1:2."},
                {"Check": "Analyst alignment", "Status": "PASS" if not human_scenario else "AMBER", "Detail": "Matches the analyst's current direction." if not human_scenario else "Human-selected direction or analyst WAIT; this is not an analyst-qualified direction."},
                {"Check": "Market / broker conditions", "Status": "UNVERIFIED", "Detail": "Spread, pip value, contract size, margin, event risk and future fills are not broker-verified."},
            ]
            st.dataframe(pd.DataFrame(check_rows), use_container_width=True, hide_index=True)
            hard_pass = geometry_direction_ok and risk_ok and rr_ok and lots >= 0.01
            if engine is None:
                st.warning("Paper-trade recording is disabled until DATABASE_URL / persistent database storage is configured.")
            elif not hard_pass:
                st.warning("Paper approval is disabled while any hard mathematical check fails. You can edit the scenario and recalculate.")
            else:
                st.markdown("#### Your decision")
                st.write("Review the chart, news, conflicting evidence and the assumptions above. The app is not choosing for you.")
                approved = st.checkbox("I reviewed this scenario and approve recording it as a paper trade (no live order).", key=f"human_approve_{analysis_id}")
                if st.button("Confirm & record paper trade", type="primary", use_container_width=True, disabled=not approved, key=f"record_exec_{analysis_id}"):
                    try:
                        db_execute("""
                            INSERT INTO paper_trades(
                                id,signal_id,symbol,direction,entry,stop,target,
                                risk_usd,planned_net_rr,outcome,notes
                            ) VALUES (
                                :id,:signal,:symbol,:direction,:entry,:stop,:target,
                                :risk,:rr,'OPEN',:notes
                            )
                        """, {
                            "id": str(uuid.uuid4()),
                            "signal": current.get("signal_id"),
                            "symbol": symbol_now,
                            "direction": direction,
                            "entry": entry,
                            "stop": stop,
                            "target": target,
                            "risk": estimated_risk,
                            "rr": net_rr,
                            "notes": f"Human-approved paper scenario. Analysis decision={plan.get('decision')}; human_scenario={human_scenario}; estimated stop={stop_pips:.2f} pips; target={target_pips:.2f} pips; size={lots:.2f} lots; costs={friction_pips:.2f} pips. No broker order sent.",
                        })
                        st.success("Paper trade recorded. No live order was sent.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not record paper trade ({type(exc).__name__}). Check database connectivity and logs.")
        else:
            st.info("Set or review the proposed direction and levels above, then select **Calculate risk & review flags**. The analyst's BUY/SELL/WAIT assessment never removes your ability to inspect a scenario.")

    st.markdown("---")
    st.markdown("### Recent saved execution candidates")
    if engine is None:
        st.warning("Configure DATABASE_URL to see saved setups across sessions. The current-session assessment above can still be reviewed.")
    else:
        try:
            saved_setups = db_execute("""
                SELECT id,created_at,symbol,interval,decision,entry,stop,target,risk_usd,planned_net_rr
                FROM signals
                WHERE decision IN ('BUY','SELL')
                  AND entry IS NOT NULL AND stop IS NOT NULL AND target IS NOT NULL
                ORDER BY created_at DESC LIMIT 50
            """, fetch=True)
            if saved_setups:
                setups_df = pd.DataFrame(saved_setups)
                setups_df["status"] = "Candidate — requires review"
                st.dataframe(setups_df, use_container_width=True, hide_index=True)
                st.caption("Saved candidates are historical analysis records, not open trades. Re-analyse before making a decision; historical prices can be stale.")
            else:
                st.info("No BUY/SELL candidates have been saved yet. Run an analysis; candidates are saved when database persistence is available.")
        except Exception as exc:
            st.error(f"Could not load saved setups ({type(exc).__name__}). Check database connectivity and logs.")


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

            with st.expander("Record or update a paper-trade outcome"):
                open_records = db_execute(
                    "SELECT * FROM paper_trades WHERE outcome='OPEN' ORDER BY created_at DESC LIMIT 200",
                    fetch=True,
                )
                if open_records:
                    labels = {
                        f"{r['created_at']} | {r['symbol']} | {r['direction']} | {r['id'][:8]}": r
                        for r in open_records
                    }
                    chosen_label = st.selectbox("Open paper trade", list(labels.keys()))
                    chosen = labels[chosen_label]
                    outcome = st.selectbox(
                        "Outcome", ["WIN", "LOSS", "BREAKEVEN", "CANCELLED"],
                        key="paper_outcome_choice",
                    )
                    exit_price = st.number_input(
                        "Exit price (0 if unknown)", min_value=0.0, value=0.0,
                        format="%.6f", key="paper_exit_price",
                    )
                    pnl = st.number_input(
                        "Simulated realized P/L (USD)", value=0.0, step=0.1,
                        key="paper_realized_pnl",
                    )
                    notes = st.text_area(
                        "Notes on execution, market context and costs",
                        key="paper_outcome_notes",
                    )
                    if st.button("Save paper outcome", key="save_paper_outcome"):
                        try:
                            db_execute("""
                                UPDATE paper_trades
                                SET outcome=:outcome, exit_price=:exit, pnl_usd=:pnl,
                                    notes=COALESCE(notes, '') || :extra_notes
                                WHERE id=:id AND outcome='OPEN'
                            """, {
                                "id": chosen["id"],
                                "outcome": outcome,
                                "exit": exit_price or None,
                                "pnl": float(pnl),
                                "extra_notes": ("\\nOutcome notes: " + notes) if notes.strip() else "",
                            })
                            st.success("Paper-trade outcome saved.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not save outcome ({type(exc).__name__}).")
                else:
                    st.info("There are no OPEN paper trades. Approve a valid candidate in Market analysis first.")

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

# -------------------- Knowledge base tab --------------------

with tab_knowledge:
    st.markdown('<div class="editorial-kicker">THE LIBRARY / KNOWLEDGE MUST BE TRACEABLE</div>', unsafe_allow_html=True)
    st.subheader("Forex knowledge & determinants")
    st.write("A structured, inspectable catalogue of the factors the analyst should consider, the data they require, their failure modes and how their usefulness should be validated. Documented knowledge is not automatically implemented or proven profitable.")

    knowledge_df = pd.DataFrame(KNOWLEDGE_ITEMS)
    domain_options = ["All domains"] + sorted(knowledge_df["domain"].unique().tolist())
    kcol1, kcol2, kcol3 = st.columns([1.25, 1.7, 1])
    with kcol1:
        selected_domain = st.selectbox("Knowledge domain", domain_options, key="knowledge_domain_filter")
    with kcol2:
        knowledge_query = st.text_input("Search knowledge", placeholder="e.g. central bank, RSI, slippage…", key="knowledge_search")
    with kcol3:
        status_options = ["All statuses", "DOCUMENTED", "IMPLEMENTED", "TESTED", "VALIDATED", "NEEDS REVIEW"]
        selected_status = st.selectbox("Maturity", status_options, key="knowledge_status_filter")

    if engine is not None:
        try:
            saved_records = db_execute("SELECT id,status,user_notes,updated_at FROM knowledge_records", fetch=True)
            saved_by_id = {r["id"]: r for r in saved_records}
        except Exception as exc:
            saved_by_id = {}
            st.warning(f"Persisted knowledge status could not be loaded ({type(exc).__name__}). Showing the built-in catalogue.")
    else:
        saved_by_id = {}
        st.info("Knowledge catalogue is available locally. Configure PostgreSQL to persist maturity statuses and notes across sessions.")

    enriched = []
    for item in KNOWLEDGE_ITEMS:
        record = dict(item)
        saved_record = saved_by_id.get(item["id"], {})
        record["status"] = saved_record.get("status", "DOCUMENTED")
        record["user_notes"] = saved_record.get("user_notes", "")
        enriched.append(record)
    filtered = []
    for item in enriched:
        if selected_domain != "All domains" and item["domain"] != selected_domain:
            continue
        if selected_status != "All statuses" and item["status"] != selected_status:
            continue
        haystack = " ".join(str(item.get(k, "")) for k in ("title","domain","description","determinants","required_data","rules" )).lower()
        if knowledge_query.strip().lower() not in haystack:
            continue
        filtered.append(item)

    total = len(enriched)
    validated = sum(item["status"] == "VALIDATED" for item in enriched)
    implemented = sum(item["status"] in ("IMPLEMENTED", "TESTED", "VALIDATED") for item in enriched)
    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Knowledge items", total)
    sm2.metric("Domains", knowledge_df["domain"].nunique())
    sm3.metric("Implemented or beyond", implemented)
    sm4.metric("Validated", validated)
    st.caption("Maturity is a project governance label, not a claim that a strategy is profitable. The built-in items start as DOCUMENTED.")

    st.download_button(
        "Export knowledge catalogue (JSON)",
        data=json.dumps(enriched, indent=2, ensure_ascii=False),
        file_name="forex_knowledge_catalogue.json",
        mime="application/json",
        use_container_width=False,
    )
    st.markdown(f"### {len(filtered)} knowledge items")
    for item in filtered:
        with st.expander(f"{item['title']}  ·  {item['domain']}  ·  {item['status']}", expanded=False):
            st.markdown(f"**What it means**\n\n{item['description']}")
            st.markdown(f"**Determinants**\n\n{item['determinants']}")
            st.markdown(f"**Required data**\n\n{item['required_data']}")
            st.markdown(f"**Interpretation rules**\n\n{item['rules']}")
            st.markdown(f"**Failure conditions / limitations**\n\n{item['failure_conditions']}")
            st.markdown(f"**Validation method**\n\n{item['validation_method']}")
            with st.form(f"knowledge_form_{item['id']}"):
                new_status = st.selectbox(
                    "Implementation maturity",
                    ["DOCUMENTED", "IMPLEMENTED", "TESTED", "VALIDATED", "NEEDS REVIEW"],
                    index=["DOCUMENTED", "IMPLEMENTED", "TESTED", "VALIDATED", "NEEDS REVIEW"].index(item["status"]),
                    key=f"knowledge_status_{item['id']}",
                    help="Use VALIDATED only after reproducible testing supports the specific implementation."
                )
                new_notes = st.text_area("Project notes / implementation evidence", value=item["user_notes"], key=f"knowledge_notes_{item['id']}")
                submitted = st.form_submit_button("Save knowledge record")
                if submitted:
                    if engine is None:
                        st.error("PostgreSQL is required to save maturity status and notes persistently.")
                    else:
                        try:
                            db_execute("""
                                INSERT INTO knowledge_records(
                                    id,domain,title,description,determinants,required_data,rules,
                                    failure_conditions,validation_method,status,user_notes,updated_at
                                ) VALUES (
                                    :id,:domain,:title,:description,:determinants,:required_data,:rules,
                                    :failure_conditions,:validation_method,:status,:user_notes,NOW()
                                ) ON CONFLICT(id) DO UPDATE SET
                                    status=EXCLUDED.status,
                                    user_notes=EXCLUDED.user_notes,
                                    updated_at=NOW()
                            """, {**item, "status": new_status, "user_notes": new_notes})
                            st.success("Knowledge record saved.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not save knowledge record ({type(exc).__name__}).")

    st.markdown("### Knowledge-engine roadmap")
    st.markdown("""
    1. **Documented** — concept, determinants, required inputs and limitations are recorded.
    2. **Implemented** — reproducible code consumes the required data and exposes its contribution.
    3. **Tested** — deterministic unit/integration tests cover normal, boundary and missing-data cases.
    4. **Validated** — chronological out-of-sample evaluation supports the stated use, with costs and sample size disclosed.
    5. **Needs review** — evidence, source quality or implementation has become questionable.

    The app does not automatically promote records through these stages. Human review is required, and the hard paper-risk controls cannot be changed by a knowledge record.
    """)

st.divider()
st.caption(
    f"FOREX / FIELDNOTES · {APP_VERSION} · Research prototype · "
    "UTC candles · PostgreSQL persistence · Paper trading only · No live order execution"
)

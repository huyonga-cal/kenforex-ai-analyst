"""Background paper-position monitor. No broker execution is implemented.
Run as a separate persistent worker with DATABASE_URL and TWELVE_DATA_API_KEY set.
Only USD-quoted major FX pairs are valued automatically; unsupported symbols are skipped.
"""
import os
import time
from datetime import datetime, timezone
import requests
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
POLL_SECONDS = max(20, int(os.getenv("PAPER_ENGINE_POLL_SECONDS", "60")))
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
if not DATABASE_URL or not API_KEY:
    raise SystemExit("Set DATABASE_URL and TWELVE_DATA_API_KEY in the worker environment.")
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300, connect_args={"connect_timeout": 10})


def latest_candle(symbol):
    r = requests.get("https://api.twelvedata.com/time_series", params={
        "symbol": symbol, "interval": "1min", "outputsize": 2,
        "apikey": API_KEY, "format": "JSON", "timezone": "UTC", "order": "desc",
    }, timeout=20)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "error" or not data.get("values"):
        raise RuntimeError(data.get("message", "No candles returned"))
    c = data["values"][0]
    return {k: float(c[k]) for k in ("open", "high", "low", "close")} | {"datetime": c["datetime"]}


def parse_utc(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def run_once():
    with engine.connect() as conn:
        trades = conn.execute(text("SELECT * FROM paper_trades WHERE outcome='OPEN' ORDER BY created_at ASC")).mappings().all()
    for trade in trades:
        symbol = str(trade["symbol"])
        # Avoid silently mispricing JPY crosses, gold and non-USD quote currencies.
        if not symbol.endswith("/USD") or "XAU" in symbol or "XAG" in symbol:
            continue
        try:
            c = latest_candle(symbol)
            candle_time = parse_utc(c["datetime"])
            opened = parse_utc(trade["created_at"])
            # Do not trigger SL/TP using a candle that began before this trade opened.
            candle_is_after_entry = candle_time >= opened.replace(second=0, microsecond=0)
            side = trade["direction"]
            entry, stop, target = float(trade["entry"]), float(trade["stop"]), float(trade["target"])
            lots = float(trade.get("lots") or 0.01)
            friction = float(trade.get("friction_pips") or 1.2)
            exit_reason, exit_price = None, None
            if candle_is_after_entry:
                stop_hit = c["low"] <= stop if side == "BUY" else c["high"] >= stop
                target_hit = c["high"] >= target if side == "BUY" else c["low"] <= target
                # Conservative ambiguity policy: if both are touched within one candle, assume stop first.
                if stop_hit:
                    exit_reason, exit_price = "STOPPED", stop
                elif target_hit:
                    exit_reason, exit_price = "TARGET_HIT", target
            mark = c["close"]
            pip = 0.0001
            gross_mark = ((mark-entry) if side == "BUY" else (entry-mark)) * 100000 * lots
            estimated_cost = friction * 10 * lots
            unrealized = gross_mark - estimated_cost
            with engine.begin() as conn:
                locked = conn.execute(text("SELECT outcome FROM paper_trades WHERE id=:id FOR UPDATE"), {"id": trade["id"]}).first()
                if not locked or locked[0] != "OPEN":
                    continue
                if exit_reason:
                    gross = ((exit_price-entry) if side == "BUY" else (entry-exit_price)) * 100000 * lots
                    pnl = gross - estimated_cost
                    conn.execute(text("""UPDATE paper_trades SET outcome=:outcome,exit_price=:exit,pnl_usd=:pnl,
                        mark_price=:mark,unrealized_pnl_usd=0,last_price_at=NOW(),closed_at=NOW(),
                        notes=COALESCE(notes,'') || :note WHERE id=:id AND outcome='OPEN'"""), {
                        "outcome": exit_reason, "exit": exit_price, "pnl": pnl, "mark": mark,
                        "note": f"\nBackground paper engine closed at {exit_price} ({exit_reason}); estimated costs applied; no live order. Intrabar ambiguity uses stop-first policy.", "id": trade["id"]})
                else:
                    conn.execute(text("UPDATE paper_trades SET mark_price=:mark,unrealized_pnl_usd=:pnl,last_price_at=NOW() WHERE id=:id AND outcome='OPEN'"), {"mark": mark, "pnl": unrealized, "id": trade["id"]})
            print(f"{datetime.now(timezone.utc).isoformat()} {symbol} trade={trade['id']} mark={mark} exit={exit_reason or '-'}")
        except Exception as exc:
            print(f"WARN trade={trade['id']} symbol={symbol}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    print(f"Paper engine started; poll={POLL_SECONDS}s; UTC timestamps preserved; live trading disabled.")
    while True:
        run_once()
        time.sleep(POLL_SECONDS)

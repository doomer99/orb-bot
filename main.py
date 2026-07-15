# ============================================================
# main.py — 5-Minute NY Open ORB Bot
# ALL secrets in Railway Variables — never in this file
# ============================================================

import os, threading, time, requests
from datetime import datetime, date
import pandas as pd
import pytz
import yfinance as yf

ET = pytz.timezone("America/New_York")

# ── Shared state ──────────────────────────────────────────────
state = {
    "phase": "waiting", "high5": None, "low5": None,
    "range_size": None, "direction": None, "entry_idx": None,
    "stop": None, "target": None, "entry_time": None,
    "result": None, "pnl_pts": 0.0, "last_update": None,
    "log": [], "today": None,
    "p1_enabled": True,  "p1_qty": 1,
    "p2_enabled": False, "p2_qty": 1,
    "p1_status": "—", "p2_status": "—",
    "equity": 0.0, "cash": 0.0, "day_pnl": 0.0,
}

def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S")
    line = f"{ts}  {msg}"
    state["log"].append(line)
    state["log"] = state["log"][-40:]
    print(line)

# ── Settings from Railway Variables ──────────────────────────

SIM_MODE      = os.environ.get("SIM_MODE",      "true").lower() == "true"
STOP_POINTS   = float(os.environ.get("STOP_POINTS",   "8.0"))
TARGET_POINTS = float(os.environ.get("TARGET_POINTS", "20.0"))

# Tradier SANDBOX — paper orders + balance display
TRADIER_SANDBOX = os.environ.get("TRADIER_SANDBOX", "true").lower() == "true"
TRADIER_TOKEN   = os.environ.get("TRADIER_TOKEN",   "")
TRADIER_ACCOUNT = os.environ.get("TRADIER_ACCOUNT", "")
TRADIER_BASE    = ("https://sandbox.tradier.com/v1"
                   if TRADIER_SANDBOX
                   else "https://api.tradier.com/v1")

# Tradier LIVE — real-time market data only
TRADIER_LIVE_TOKEN = os.environ.get("TRADIER_LIVE_TOKEN", "")
TRADIER_LIVE_BASE  = "https://api.tradier.com/v1"

# Pipeline 1 — Topstep via TradersPost
P1_ENABLED  = os.environ.get("P1_ENABLED",     "true").lower() == "true"
P1_URL      = os.environ.get("P1_WEBHOOK_URL", "")
P1_PASSWORD = os.environ.get("P1_PASSWORD",    "")
P1_TICKER   = os.environ.get("P1_TICKER",      "MES1!")
P1_QTY      = int(os.environ.get("P1_QUANTITY","1"))

# Pipeline 2 — Tradier 0DTE options
P2_ENABLED  = os.environ.get("P2_ENABLED",     "false").lower() == "true"
P2_URL      = os.environ.get("P2_WEBHOOK_URL", "")
P2_PASSWORD = os.environ.get("P2_PASSWORD",    "")
P2_TICKER   = os.environ.get("P2_TICKER",      "SPY")
P2_QTY      = int(os.environ.get("P2_QUANTITY","1"))

# Pipeline 3 — future prop firm
P3_ENABLED  = os.environ.get("P3_ENABLED",     "false").lower() == "true"
P3_URL      = os.environ.get("P3_WEBHOOK_URL", "")
P3_PASSWORD = os.environ.get("P3_PASSWORD",    "")
P3_TICKER   = os.environ.get("P3_TICKER",      "MES1!")
P3_QTY      = int(os.environ.get("P3_QUANTITY","1"))

# Risk limits
DAILY_LOSS_LIMIT  = float(os.environ.get("DAILY_LOSS_LIMIT",  "1000"))
DAILY_LOSS_BUFFER = float(os.environ.get("DAILY_LOSS_BUFFER", "200"))

day_pnl = 0.0

# ── Market data ───────────────────────────────────────────────

def get_spy_1min():
    """Real-time SPY 1-min bars from live Tradier. Falls back to Yahoo."""
    if TRADIER_LIVE_TOKEN:
        try:
            r = requests.get(
                f"{TRADIER_LIVE_BASE}/markets/timesales",
                headers={
                    "Authorization": f"Bearer {TRADIER_LIVE_TOKEN}",
                    "Accept": "application/json"
                },
                params={
                    "symbol":         "SPY",
                    "interval":       "1min",
                    "start":          datetime.now(ET).strftime(
                                          "%Y-%m-%d 09:00"),
                    "session_filter": "open"
                },
                timeout=5
            )
            data = r.json().get("series", {}).get("data", [])
            if not data:
                return None
            if isinstance(data, dict):
                data = [data]
            records, times = [], []
            for bar in data:
                records.append({
                    "Open":   float(bar.get("open",   0)),
                    "High":   float(bar.get("high",   0)),
                    "Low":    float(bar.get("low",    0)),
                    "Close":  float(bar.get("close",  0)),
                    "Volume": float(bar.get("volume", 0)),
                })
                times.append(bar["time"])
            df = pd.DataFrame(records)
            df.index = pd.to_datetime(
                times, format="%Y-%m-%d %H:%M:%S"
            ).tz_localize("America/New_York")
            return df
        except Exception as e:
            log(f"Tradier data error: {e} — trying Yahoo")

    try:
        spy = yf.download("SPY", period="1d", interval="1m",
                          progress=False, auto_adjust=True)
        if hasattr(spy.columns, "levels"):
            spy.columns = spy.columns.get_level_values(0)
        spy.index = spy.index.tz_convert(ET)
        return spy
    except Exception as e:
        log(f"Yahoo error: {e}")
        return None

def get_current_price():
    """Real-time SPY price."""
    if TRADIER_LIVE_TOKEN:
        try:
            r = requests.get(
                f"{TRADIER_LIVE_BASE}/markets/quotes",
                headers={
                    "Authorization": f"Bearer {TRADIER_LIVE_TOKEN}",
                    "Accept": "application/json"
                },
                params={"symbols": "SPY"},
                timeout=5
            )
            quote = r.json()["quotes"]["quote"]
            return float(quote.get("last", 0))
        except Exception as e:
            log(f"Quote error: {e}")

    try:
        spy = yf.download("SPY", period="1d", interval="1m",
                          progress=False, auto_adjust=True)
        if hasattr(spy.columns, "levels"):
            spy.columns = spy.columns.get_level_values(0)
        return float(spy["Close"].iloc[-1])
    except:
        return None

def get_5min_range(spy_1m):
    if spy_1m is None or len(spy_1m) == 0:
        return None, None
    bars = spy_1m.between_time("09:30", "09:34")
    if len(bars) < 3:
        return None, None
    return float(bars["High"].max()), float(bars["Low"].min())

# ── Tradier balance ───────────────────────────────────────────

def get_tradier_balance():
    if not TRADIER_TOKEN or not TRADIER_ACCOUNT:
        log("Balance: no token or account set")
        return None
    try:
        r = requests.get(
            f"{TRADIER_BASE}/accounts/{TRADIER_ACCOUNT}/balances",
            headers={
                "Authorization": f"Bearer {TRADIER_TOKEN}",
                "Accept": "application/json"
            },
            timeout=5
        )
        data   = r.json().get("balances", {})
        equity = float(data.get("total_equity", 0))
        cash   = float(
            data.get("cash", {}).get("cash_available", 0) or
            data.get("cash_available", 0) or 0)
        pnl    = float(
            data.get("pnl", {}).get("day", 0) or
            data.get("day_pnl", 0) or 0)
        log(f"Balance: ${equity:,.0f}  "
            f"Day P&L: ${pnl:+,.0f}")
        return {"equity": equity, "cash": cash, "day_pnl": pnl}
    except Exception as e:
        log(f"Balance error: {e}")
        return None

def refresh_balance():
    while True:
        bal = get_tradier_balance()
        if bal:
            state["equity"]  = bal["equity"]
            state["cash"]    = bal["cash"]
            state["day_pnl"] = bal["day_pnl"]
        time.sleep(60)

# ── Risk guard ────────────────────────────────────────────────

def risk_ok():
    loss      = -min(0.0, day_pnl)
    remaining = DAILY_LOSS_LIMIT - loss
    if remaining < DAILY_LOSS_BUFFER:
        log(f"⚠️ Daily loss guard: ${remaining:.0f} left")
        return False
    return True

# ── Option symbol builder ─────────────────────────────────────

def build_option_symbol(direction, spy_price):
    """
    Build today's 0DTE ATM option symbol.
    Example: SPY260715C00560000
    SPY + YYMMDD + C/P + 8-digit strike (3 decimal places)
    $560.00 strike = 00560000
    """
    today      = date.today().strftime("%y%m%d")
    strike     = round(spy_price)  # ATM = nearest $1 strike
    opt        = "C" if direction == "UP" else "P"
    strike_str = f"{int(strike * 1000):08d}"
    symbol     = f"SPY{today}{opt}{strike_str}"
    log(f"Option symbol: {symbol}")
    return symbol

# ── Tradier option orders ─────────────────────────────────────

def place_tradier_option(direction, qty):
    """Place 0DTE ATM SPY option — buy to open."""
    if not TRADIER_TOKEN or not TRADIER_ACCOUNT:
        log("❌ Tradier credentials not set")
        return False
    try:
        spy_price = get_current_price()
        if not spy_price:
            log("❌ No SPY price for option symbol")
            return False
        symbol = build_option_symbol(direction, spy_price)
        r = requests.post(
            f"{TRADIER_BASE}/accounts/"
            f"{TRADIER_ACCOUNT}/orders",
            headers={
                "Authorization": f"Bearer {TRADIER_TOKEN}",
                "Accept":        "application/json",
                "Content-Type":
                    "application/x-www-form-urlencoded",
            },
            data={
                "class":         "option",
                "symbol":        "SPY",
                "option_symbol": symbol,
                "side":          "buy_to_open",
                "quantity":      qty,
                "type":          "market",
                "duration":      "day",
            },
            timeout=10
        )
        ok = r.status_code == 200
        log(f"{'✅' if ok else '❌'} "
            f"{symbol}: {r.status_code} "
            f"{r.text[:80]}")
        return ok
    except Exception as e:
        log(f"❌ Option order error: {e}")
        return False

def close_tradier_option(direction, qty):
    """Close 0DTE ATM SPY option — sell to close."""
    if not TRADIER_TOKEN or not TRADIER_ACCOUNT:
        return False
    try:
        spy_price = get_current_price() or 560
        symbol    = build_option_symbol(direction, spy_price)
        r = requests.post(
            f"{TRADIER_BASE}/accounts/"
            f"{TRADIER_ACCOUNT}/orders",
            headers={
                "Authorization": f"Bearer {TRADIER_TOKEN}",
                "Accept":        "application/json",
                "Content-Type":
                    "application/x-www-form-urlencoded",
            },
            data={
                "class":         "option",
                "symbol":        "SPY",
                "option_symbol": symbol,
                "side":          "sell_to_close",
                "quantity":      qty,
                "type":          "market",
                "duration":      "day",
            },
            timeout=10
        )
        ok = r.status_code == 200
        log(f"{'✅' if ok else '❌'} "
            f"Close {symbol}: {r.status_code}")
        return ok
    except Exception as e:
        log(f"❌ Close error: {e}")
        return False

# ── Webhook ───────────────────────────────────────────────────

def send_webhook(url, password, extra, label):
    if not url:
        log(f"⚠️ {label}: no webhook URL set")
        return False
    try:
        r = requests.post(
            url,
            json={"password": password, **extra},
            timeout=10)
        ok = r.status_code == 200
        log(f"{'✅' if ok else '❌'} {label}: {r.status_code}")
        return ok
    except Exception as e:
        log(f"❌ {label}: {e}")
        return False

# ── Place order — all pipelines ───────────────────────────────

def place_order(direction):
    qty1 = state.get("p1_qty", P1_QTY)
    qty2 = state.get("p2_qty", P2_QTY)

    if SIM_MODE:
        log(f"[SIM] Signal: {direction}")
        log(f"[SIM] P1 Topstep: "
            f"{'ON' if state.get('p1_enabled', P1_ENABLED) else 'OFF'}"
            f" {qty1}x MES")
        log(f"[SIM] P2 Tradier options: "
            f"{'ON' if state.get('p2_enabled', P2_ENABLED) else 'OFF'}"
            f" {qty2}x SPY 0DTE")
        state["p1_status"] = (
            "SIM ✓" if state.get("p1_enabled", P1_ENABLED)
            else "OFF")
        state["p2_status"] = (
            "SIM ✓" if state.get("p2_enabled", P2_ENABLED)
            else "OFF")
        return True

    results = []

    # Pipeline 1 — Topstep via TradersPost
    if state.get("p1_enabled", P1_ENABLED):
        ok = send_webhook(P1_URL, P1_PASSWORD, {
            "ticker":   P1_TICKER,
            "action":   "buy" if direction == "UP" else "sell",
            "quantity": qty1,
        }, f"P1 Topstep {qty1}x {P1_TICKER}")
        state["p1_status"] = "✅ FILLED" if ok else "❌ FAILED"
        results.append(ok)
    else:
        state["p1_status"] = "OFF"

    # Pipeline 2 — Tradier 0DTE options
    if state.get("p2_enabled", P2_ENABLED):
        if P2_URL:
            opt = "call" if direction == "UP" else "put"
            ok  = send_webhook(P2_URL, P2_PASSWORD, {
                "ticker":      P2_TICKER,
                "action":      "buy",
                "option_type": opt,
                "quantity":    qty2,
                "expiry":      "0DTE",
                "strike":      "ATM",
            }, f"P2 {qty2}x SPY {opt.upper()}")
        else:
            ok = place_tradier_option(direction, qty2)
        state["p2_status"] = "✅ FILLED" if ok else "❌ FAILED"
        results.append(ok)
    else:
        state["p2_status"] = "OFF"

    # Pipeline 3 — future prop firm
    if P3_ENABLED:
        ok = send_webhook(P3_URL, P3_PASSWORD, {
            "ticker":   P3_TICKER,
            "action":   "buy" if direction == "UP" else "sell",
            "quantity": P3_QTY,
        }, f"P3 {P3_QTY}x {P3_TICKER}")
        results.append(ok)

    return any(results) if results else False

# ── Close order — all pipelines ───────────────────────────────

def close_order(direction):
    qty1 = state.get("p1_qty", P1_QTY)
    qty2 = state.get("p2_qty", P2_QTY)

    if SIM_MODE:
        log("[SIM] Close signal sent")
        return True

    # Close Pipeline 1
    if state.get("p1_enabled", P1_ENABLED):
        send_webhook(P1_URL, P1_PASSWORD, {
            "ticker":        P1_TICKER,
            "action":        "sell" if direction == "UP" else "buy",
            "quantity":      qty1,
            "closePosition": True,
        }, "P1 Topstep CLOSE")

    # Close Pipeline 2
    if state.get("p2_enabled", P2_ENABLED):
        if P2_URL:
            send_webhook(P2_URL, P2_PASSWORD, {
                "ticker":        P2_TICKER,
                "action":        "close",
                "closePosition": True,
            }, "P2 CLOSE")
        else:
            close_tradier_option(direction, qty2)

    # Close Pipeline 3
    if P3_ENABLED:
        send_webhook(P3_URL, P3_PASSWORD, {
            "ticker":        P3_TICKER,
            "action":        "sell" if direction == "UP" else "buy",
            "quantity":      P3_QTY,
            "closePosition": True,
        }, "P3 CLOSE")

# ── Main bot loop ─────────────────────────────────────────────

def run_bot():
    global day_pnl
    mode = "SANDBOX" if TRADIER_SANDBOX else "LIVE"
    data = ("LIVE Tradier" if TRADIER_LIVE_TOKEN
            else "Yahoo (delayed)")
    log(f"ORB Bot started — SIM={SIM_MODE} "
        f"Orders={mode} Data={data}")
    log(f"P1 Topstep: {'ON' if P1_ENABLED else 'OFF'}")
    log(f"P2 Tradier options: {'ON' if P2_ENABLED else 'OFF'}")
    log(f"P3 Future: {'ON' if P3_ENABLED else 'OFF'}")

    while True:
        now = datetime.now(ET)

        # Midnight reset
        if now.hour == 0 and now.minute == 0:
            day_pnl = 0.0
            state.update({
                "phase": "waiting", "high5": None,
                "low5": None, "direction": None,
                "result": None, "pnl_pts": 0.0,
                "entry_idx": None, "today": None,
                "p1_status": "—", "p2_status": "—",
            })
            log("New day — reset")
            time.sleep(61)
            continue

        # Skip weekends
        if now.weekday() >= 5:
            state["phase"] = "waiting"
            time.sleep(300)
            continue

        today_str = now.date().isoformat()

        # Already done today
        if (state["today"] == today_str and
                state["phase"] == "done"):
            time.sleep(60)
            continue

        # Before market
        if now.hour < 9 or (now.hour == 9 and
                             now.minute < 30):
            state["phase"] = "waiting"
            time.sleep(30)
            continue

        # 9:30-9:34 build range
        if now.hour == 9 and now.minute < 35:
            state["phase"] = "building"
            spy_1m = get_spy_1min()
            h, l   = get_5min_range(spy_1m)
            if h and l:
                state["high5"]      = round(h, 2)
                state["low5"]       = round(l, 2)
                state["range_size"] = round(h - l, 2)
            state["last_update"] = now.strftime("%H:%M:%S")
            time.sleep(10)
            continue

        # 9:35 — range locked, start watching
        if (now.hour == 9 and now.minute >= 35 and
                state["today"] != today_str and
                state["phase"] != "active"):
            state["today"] = today_str
            state["phase"] = "watching"
            log(f"Range locked: "
                f"H={state['high5']} "
                f"L={state['low5']} "
                f"Size={state['range_size']}")

        # Watch for breakout
        if state["phase"] == "watching" and state["high5"]:
            if not risk_ok():
                state["phase"] = "done"
                continue

            spy_1m = get_spy_1min()
            if spy_1m is None:
                time.sleep(15)
                continue

            post      = spy_1m.between_time("09:35", "12:00")
            direction = None
            for ts, bar in post.iterrows():
                if float(bar["High"]) > state["high5"]:
                    direction = "UP"
                    break
                if float(bar["Low"]) < state["low5"]:
                    direction = "DOWN"
                    break

            if direction:
                price     = (get_current_price() or
                             state["high5"])
                entry_idx = price * 10.0
                stop      = (entry_idx - STOP_POINTS
                             if direction == "UP"
                             else entry_idx + STOP_POINTS)
                target    = (entry_idx + TARGET_POINTS
                             if direction == "UP"
                             else entry_idx - TARGET_POINTS)
                log(f"Breakout {direction} "
                    f"entry≈{entry_idx:.0f} "
                    f"stop={stop:.0f} "
                    f"target={target:.0f}")
                ok = place_order(direction)
                if ok or SIM_MODE:
                    state.update({
                        "phase":      "active",
                        "direction":  direction,
                        "entry_idx":  entry_idx,
                        "stop":       stop,
                        "target":     target,
                        "entry_time": now.strftime("%H:%M:%S"),
                        "result":     "OPEN",
                        "pnl_pts":    0.0,
                    })

        # Monitor active trade
        if state["phase"] == "active":
            current = get_current_price()
            if current:
                idx = current * 10.0
                pnl = (idx - state["entry_idx"]
                       if state["direction"] == "UP"
                       else state["entry_idx"] - idx)
                state["pnl_pts"] = round(pnl, 1)

            try:
                entry_dt = datetime.strptime(
                    f"{now.date()} {state['entry_time']}",
                    "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=ET)
                elapsed = ((now - entry_dt).total_seconds()
                           / 60.0)
            except:
                elapsed = 0

            exit_reason = None
            if current:
                idx = current * 10.0
                if state["direction"] == "UP":
                    if idx <= state["stop"]:
                        exit_reason = "STOP"
                    if idx >= state["target"]:
                        exit_reason = "TARGET"
                else:
                    if idx >= state["stop"]:
                        exit_reason = "STOP"
                    if idx <= state["target"]:
                        exit_reason = "TARGET"
            if elapsed >= 30:
                exit_reason = "TIMED EXIT"
            if now.hour >= 12:
                exit_reason = "HARD CLOSE"

            if exit_reason:
                close_order(state["direction"])
                pnl_d   = (state["pnl_pts"] * 5.0 *
                           state.get("p1_qty", P1_QTY))
                day_pnl += pnl_d
                result   = ("WIN" if state["pnl_pts"] > 0
                            else "LOSS")
                state.update({
                    "phase":  "done",
                    "result": result,
                })
                log(f"CLOSED: {exit_reason} | "
                    f"{state['pnl_pts']:+.1f}pts | "
                    f"${pnl_d:+.0f}")

        state["last_update"] = now.strftime("%H:%M:%S")
        time.sleep(15)

# ── Start background threads ──────────────────────────────────
threading.Thread(target=run_bot,
                 daemon=True).start()
threading.Thread(target=refresh_balance,
                 daemon=True).start()

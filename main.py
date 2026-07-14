# ============================================================
# main.py — 5-Minute ORB Bot
# ALL secrets go in Railway Variables — NEVER in this file
# ============================================================

import os, threading, time, requests
from datetime import datetime
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
    "p1_enabled": True, "p1_qty": 1,
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

# ── ALL SETTINGS FROM RAILWAY VARIABLES ──────────────────────
# Never put real values here — add them in Railway Variables tab

SIM_MODE      = os.environ.get("SIM_MODE",      "true").lower() == "true"
STOP_POINTS   = float(os.environ.get("STOP_POINTS",   "8.0"))
TARGET_POINTS = float(os.environ.get("TARGET_POINTS", "20.0"))

# ── Tradier (options account + balance) ──────────────────────
# Set TRADIER_SANDBOX=true  for paper ($100k sandbox)
# Set TRADIER_SANDBOX=false for live real money
# Switch by changing ONE variable in Railway — nothing else
TRADIER_SANDBOX  = os.environ.get("TRADIER_SANDBOX", "true").lower() == "true"
TRADIER_TOKEN    = os.environ.get("TRADIER_TOKEN",   "")   # sandbox or live token
TRADIER_ACCOUNT  = os.environ.get("TRADIER_ACCOUNT", "")   # sandbox or live account
TRADIER_BASE     = ("https://sandbox.tradier.com/v1"
                    if TRADIER_SANDBOX
                    else "https://api.tradier.com/v1")

# ── Pipeline 1: Topstep via TradersPost (MES futures) ────────
# Get webhook URL from traderspost.io after connecting Topstep
P1_ENABLED  = os.environ.get("P1_ENABLED",      "true").lower() == "true"
P1_URL      = os.environ.get("P1_WEBHOOK_URL",  "")  # from TradersPost
P1_PASSWORD = os.environ.get("P1_PASSWORD",     "")  # from TradersPost
P1_TICKER   = os.environ.get("P1_TICKER",       "MES1!")
P1_QTY      = int(os.environ.get("P1_QUANTITY", "1"))

# ── Pipeline 2: TradeYour / Tradier options ───────────────────
# Uses same Tradier account as balance pull
# Set P2_ENABLED=true when ready to trade options
P2_ENABLED  = os.environ.get("P2_ENABLED",      "false").lower() == "true"
P2_URL      = os.environ.get("P2_WEBHOOK_URL",  "")  # TradeYour webhook if used
P2_PASSWORD = os.environ.get("P2_PASSWORD",     "")
P2_TICKER   = os.environ.get("P2_TICKER",       "SPY")
P2_QTY      = int(os.environ.get("P2_QUANTITY", "1"))

# ── Pipeline 3: placeholder for any future prop firm ─────────
# Add P3_WEBHOOK_URL etc to Railway when you add another firm
P3_ENABLED  = os.environ.get("P3_ENABLED",      "false").lower() == "true"
P3_URL      = os.environ.get("P3_WEBHOOK_URL",  "")
P3_PASSWORD = os.environ.get("P3_PASSWORD",     "")
P3_TICKER   = os.environ.get("P3_TICKER",       "MES1!")
P3_QTY      = int(os.environ.get("P3_QUANTITY", "1"))

# ── Prop firm risk limits ─────────────────────────────────────
DAILY_LOSS_LIMIT  = float(os.environ.get("DAILY_LOSS_LIMIT",  "1000"))
DAILY_LOSS_BUFFER = float(os.environ.get("DAILY_LOSS_BUFFER", "200"))

day_pnl = 0.0

# ── Tradier balance pull ──────────────────────────────────────

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
        log(f"Tradier raw: {r.text[:200]}")
        raw = r.json()
        data = raw.get("balances", {})

        # Try multiple possible field names
        equity = (
            data.get("total_equity") or
            data.get("equity") or
            data.get("net_value") or
            data.get("total_value") or 0
        )
        cash = (
            data.get("cash", {}).get("cash_available") or
            data.get("cash_available") or
            data.get("cash", {}).get("total_cash") or
            data.get("total_cash") or 0
        )
        day_pnl = (
            data.get("pnl", {}).get("day") or
            data.get("day_pnl") or
            data.get("pnl", {}).get("current_requirement") or 0
        )

        return {
            "equity":  float(equity),
            "cash":    float(cash),
            "day_pnl": float(day_pnl),
        }
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
            log(f"Balance: ${bal['equity']:,.0f}  "
                f"Day P&L: ${bal['day_pnl']:+,.0f}")
        time.sleep(60)

# ── Risk guard ────────────────────────────────────────────────

def risk_ok():
    loss = -min(0.0, day_pnl)
    remaining = DAILY_LOSS_LIMIT - loss
    if remaining < DAILY_LOSS_BUFFER:
        log(f"⚠️ Daily loss guard: ${remaining:.0f} left — skip")
        return False
    return True

# ── Webhook helper ────────────────────────────────────────────

def send_webhook(url, password, extra, label):
    if not url:
        log(f"⚠️ {label}: no webhook URL set in Railway Variables")
        return False
    try:
        r = requests.post(url,
                          json={"password": password, **extra},
                          timeout=10)
        ok = r.status_code == 200
        log(f"{'✅' if ok else '❌'} {label}: {r.status_code}")
        return ok
    except Exception as e:
        log(f"❌ {label}: {e}")
        return False

# ── Order execution ───────────────────────────────────────────

def place_order(direction):
    qty1 = state.get("p1_qty", P1_QTY)
    qty2 = state.get("p2_qty", P2_QTY)

    if SIM_MODE:
        log(f"[SIM] {direction} signal")
        log(f"[SIM] P1 Topstep: {'ON' if state.get('p1_enabled', P1_ENABLED) else 'OFF'} {qty1}x MES")
        log(f"[SIM] P2 TradeYour: {'ON' if state.get('p2_enabled', P2_ENABLED) else 'OFF'} {qty2}x SPY options")
        log(f"[SIM] P3: {'ON' if P3_ENABLED else 'OFF'}")
        state["p1_status"] = "SIM ✓" if state.get("p1_enabled", P1_ENABLED) else "OFF"
        state["p2_status"] = "SIM ✓" if state.get("p2_enabled", P2_ENABLED) else "OFF"
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

    # Pipeline 2 — TradeYour / Tradier options
    if state.get("p2_enabled", P2_ENABLED):
        opt = "call" if direction == "UP" else "put"
        if P2_URL:
            # Use TradeYour webhook if configured
            ok = send_webhook(P2_URL, P2_PASSWORD, {
                "ticker": P2_TICKER,
                "action": "buy",
                "option_type": opt,
                "quantity": qty2,
                "expiry": "0DTE",
                "strike": "ATM",
            }, f"P2 TradeYour {qty2}x SPY {opt.upper()}")
        else:
            # Direct Tradier API option order
            ok = place_tradier_option(direction, qty2)
        state["p2_status"] = "✅ FILLED" if ok else "❌ FAILED"
        results.append(ok)
    else:
        state["p2_status"] = "OFF"

    # Pipeline 3 — Future prop firm placeholder
    if P3_ENABLED:
        ok = send_webhook(P3_URL, P3_PASSWORD, {
            "ticker":   P3_TICKER,
            "action":   "buy" if direction == "UP" else "sell",
            "quantity": P3_QTY,
        }, f"P3 {P3_QTY}x {P3_TICKER}")
        results.append(ok)

    return any(results) if results else False

def place_tradier_option(direction, qty):
    """Direct Tradier API option order (when no TradeYour webhook)."""
    if not TRADIER_TOKEN or not TRADIER_ACCOUNT:
        log("❌ Tradier credentials not set")
        return False
    try:
        from datetime import date
        expiry  = date.today().strftime("%Y-%m-%d")
        opt     = "call" if direction == "UP" else "put"
        # Get ATM strike from current SPY price
        price   = get_current_price()
        strike  = round(price) if price else 580
        r = requests.post(
            f"{TRADIER_BASE}/accounts/{TRADIER_ACCOUNT}/orders",
            headers={
                "Authorization": f"Bearer {TRADIER_TOKEN}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "class":          "option",
                "symbol":         "SPY",
                "option_symbol":  f"SPY{expiry.replace('-','')}",
                "side":           "buy_to_open",
                "quantity":       qty,
                "type":           "market",
                "duration":       "day",
            },
            timeout=10
        )
        ok = r.status_code == 200
        log(f"{'✅' if ok else '❌'} Tradier option order: {r.status_code}")
        return ok
    except Exception as e:
        log(f"❌ Tradier option error: {e}")
        return False

def close_order(direction):
    if SIM_MODE:
        log("[SIM] Close signal sent to all active pipelines")
        return True

    qty1 = state.get("p1_qty", P1_QTY)
    qty2 = state.get("p2_qty", P2_QTY)

    if state.get("p1_enabled", P1_ENABLED):
        send_webhook(P1_URL, P1_PASSWORD, {
            "ticker":        P1_TICKER,
            "action":        "sell" if direction == "UP" else "buy",
            "quantity":      qty1,
            "closePosition": True,
        }, "P1 Topstep CLOSE")

    if state.get("p2_enabled", P2_ENABLED):
        if P2_URL:
            send_webhook(P2_URL, P2_PASSWORD, {
                "ticker":        P2_TICKER,
                "action":        "close",
                "closePosition": True,
            }, "P2 TradeYour CLOSE")
        else:
            # Close via Tradier directly
            try:
                opt = "call" if direction == "UP" else "put"
                requests.post(
                    f"{TRADIER_BASE}/accounts/"
                    f"{TRADIER_ACCOUNT}/orders",
                    headers={
                        "Authorization": f"Bearer {TRADIER_TOKEN}",
                        "Accept": "application/json",
                        "Content-Type":
                            "application/x-www-form-urlencoded",
                    },
                    data={
                        "class":    "option",
                        "symbol":   "SPY",
                        "side":     "sell_to_close",
                        "quantity": qty2,
                        "type":     "market",
                        "duration": "day",
                    },
                    timeout=10
                )
                log("✅ Tradier option closed")
            except Exception as e:
                log(f"❌ Tradier close error: {e}")

    if P3_ENABLED:
        send_webhook(P3_URL, P3_PASSWORD, {
            "ticker":        P3_TICKER,
            "action":        "sell" if direction == "UP" else "buy",
            "quantity":      P3_QTY,
            "closePosition": True,
        }, "P3 CLOSE")

# ── Market data ───────────────────────────────────────────────

def get_spy_1min():
    try:
        spy = yf.download("SPY", period="1d", interval="1m",
                          progress=False, auto_adjust=True)
        if hasattr(spy.columns, "levels"):
            spy.columns = spy.columns.get_level_values(0)
        spy.index = spy.index.tz_convert(ET)
        return spy
    except Exception as e:
        log(f"Data error: {e}")
        return None

def get_5min_range(spy_1m):
    if spy_1m is None or len(spy_1m) == 0:
        return None, None
    bars = spy_1m.between_time("09:30", "09:34")
    if len(bars) < 3:
        return None, None
    return float(bars["High"].max()), float(bars["Low"].min())

def get_current_price():
    try:
        spy = yf.download("SPY", period="1d", interval="1m",
                          progress=False, auto_adjust=True)
        if hasattr(spy.columns, "levels"):
            spy.columns = spy.columns.get_level_values(0)
        return float(spy["Close"].iloc[-1])
    except:
        return None

# ── Main bot loop ─────────────────────────────────────────────

def run_bot():
    global day_pnl
    mode = "SANDBOX" if TRADIER_SANDBOX else "LIVE"
    log(f"ORB Bot started — SIM={SIM_MODE} Tradier={mode}")
    log(f"P1 Topstep: {'ON' if P1_ENABLED else 'OFF'}")
    log(f"P2 TradeYour: {'ON' if P2_ENABLED else 'OFF'}")
    log(f"P3 Future: {'ON' if P3_ENABLED else 'OFF'}")

    while True:
        now = datetime.now(ET)

        if now.hour == 0 and now.minute == 0:
            day_pnl = 0.0
            state.update({
                "phase": "waiting", "high5": None, "low5": None,
                "direction": None, "result": None, "pnl_pts": 0.0,
                "entry_idx": None, "today": None,
                "p1_status": "—", "p2_status": "—",
            })
            log("New day — reset")
            time.sleep(61)
            continue

        if now.weekday() >= 5:
            state["phase"] = "waiting"
            time.sleep(300)
            continue

        today_str = now.date().isoformat()

        if state["today"] == today_str and state["phase"] == "done":
            time.sleep(60)
            continue

        if now.hour < 9 or (now.hour == 9 and now.minute < 30):
            state["phase"] = "waiting"
            time.sleep(30)
            continue

        if now.hour == 9 and now.minute < 35:
            state["phase"] = "building"
            spy_1m = get_spy_1min()
            h, l = get_5min_range(spy_1m)
            if h and l:
                state["high5"]      = round(h, 2)
                state["low5"]       = round(l, 2)
                state["range_size"] = round(h - l, 2)
            state["last_update"] = now.strftime("%H:%M:%S")
            time.sleep(10)
            continue

        if (now.hour == 9 and now.minute >= 35 and
                state["today"] != today_str and
                state["phase"] != "active"):
            state["today"] = today_str
            state["phase"] = "watching"
            log(f"Range: H={state['high5']} "
                f"L={state['low5']} "
                f"Size={state['range_size']}")

        if state["phase"] == "watching" and state["high5"]:
            if not risk_ok():
                state["phase"] = "done"
                continue

            spy_1m = get_spy_1min()
            if spy_1m is None:
                time.sleep(15)
                continue

            post = spy_1m.between_time("09:35", "12:00")
            direction = None
            for ts, bar in post.iterrows():
                if float(bar["High"]) > state["high5"]:
                    direction = "UP"; break
                if float(bar["Low"])  < state["low5"]:
                    direction = "DOWN"; break

            if direction:
                price     = get_current_price() or state["high5"]
                entry_idx = price * 10.0
                stop      = (entry_idx - STOP_POINTS
                             if direction == "UP"
                             else entry_idx + STOP_POINTS)
                target    = (entry_idx + TARGET_POINTS
                             if direction == "UP"
                             else entry_idx - TARGET_POINTS)
                log(f"Breakout {direction} entry≈{entry_idx:.0f} "
                    f"stop={stop:.0f} target={target:.0f}")
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
                    "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)
                elapsed = (now - entry_dt).total_seconds() / 60.0
            except:
                elapsed = 0

            exit_reason = None
            if current:
                idx = current * 10.0
                if state["direction"] == "UP":
                    if idx <= state["stop"]:   exit_reason = "STOP"
                    if idx >= state["target"]: exit_reason = "TARGET"
                else:
                    if idx >= state["stop"]:   exit_reason = "STOP"
                    if idx <= state["target"]: exit_reason = "TARGET"
            if elapsed >= 30:  exit_reason = "TIMED EXIT"
            if now.hour >= 12: exit_reason = "HARD CLOSE"

            if exit_reason:
                close_order(state["direction"])
                pnl_d   = state["pnl_pts"] * 5.0 * state.get("p1_qty", P1_QTY)
                day_pnl += pnl_d
                result   = "WIN" if state["pnl_pts"] > 0 else "LOSS"
                state.update({"phase": "done", "result": result})
                log(f"CLOSED: {exit_reason} | "
                    f"{state['pnl_pts']:+.1f}pts | ${pnl_d:+.0f}")

        state["last_update"] = now.strftime("%H:%M:%S")
        time.sleep(15)

# ── Start all background threads ─────────────────────────────
threading.Thread(target=run_bot,         daemon=True).start()
threading.Thread(target=refresh_balance, daemon=True).start()

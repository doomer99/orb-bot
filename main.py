# ============================================================
# main.py — 5-Minute ORB Bot + Signal Dashboard
# ------------------------------------------------------------
# Runs two things simultaneously:
#   1. The trading bot (wakes at 9:34:55 ET, fires at 9:35)
#   2. The Streamlit dashboard (always visible at your URL)
#
# Deploy to Railway: push to GitHub, connect Railway, done.
# Bot trades automatically while you're in the field.
# ============================================================

import os
import threading
import time
import json
from datetime import datetime, date
import pytz
import yfinance as yf
import pandas as pd
import requests

ET = pytz.timezone("America/New_York")

# ── Shared state (bot writes, dashboard reads) ────────────────
state = {
    "phase":       "waiting",   # waiting/building/watching/active/done
    "high5":       None,
    "low5":        None,
    "range_size":  None,
    "direction":   None,        # UP or DOWN
    "entry_idx":   None,        # index price at entry
    "stop":        None,
    "target":      None,
    "entry_time":  None,
    "result":      None,        # WIN / LOSS / OPEN
    "pnl_pts":     None,
    "last_update": None,
    "log":         [],
    "today":       None,
}

def log(msg):
    ts = datetime.now(ET).strftime("%H:%M:%S")
    line = f"{ts} {msg}"
    state["log"].append(line)
    state["log"] = state["log"][-30:]
    print(line)

# ── Market data ───────────────────────────────────────────────

def get_spy_1min():
    try:
        spy = yf.download("SPY", period="1d",
                          interval="1m", progress=False,
                          auto_adjust=True)
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
        spy = yf.download("SPY", period="1d",
                          interval="1m", progress=False,
                          auto_adjust=True)
        if hasattr(spy.columns, "levels"):
            spy.columns = spy.columns.get_level_values(0)
        return float(spy["Close"].iloc[-1])
    except:
        return None

# ── Order execution (TradersPost webhook) ─────────────────────

WEBHOOK_URL      = os.environ.get("TRADERSPOST_WEBHOOK_URL", "")
WEBHOOK_PASSWORD = os.environ.get("TRADERSPOST_PASSWORD", "")
CONTRACTS        = int(os.environ.get("CONTRACTS", "1"))
STOP_POINTS      = float(os.environ.get("STOP_POINTS", "8.0"))
TARGET_POINTS    = float(os.environ.get("TARGET_POINTS", "20.0"))
SIM_MODE         = os.environ.get("SIM_MODE", "true").lower() == "true"

def place_order(direction):
    """Send entry signal to TradersPost → Topstep."""
    if SIM_MODE:
        log(f"[SIM] Would place {direction} order — {CONTRACTS} contracts")
        return True

    if not WEBHOOK_URL:
        log("❌ No webhook URL configured")
        return False

    payload = {
        "password": WEBHOOK_PASSWORD,
        "ticker":   "MES1!",
        "action":   "buy" if direction == "UP" else "sell",
        "quantity": CONTRACTS,
    }
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code == 200:
            log(f"✅ Order placed: {direction} {CONTRACTS}x MES")
            return True
        else:
            log(f"❌ Order failed: {r.status_code} {r.text}")
            return False
    except Exception as e:
        log(f"❌ Order error: {e}")
        return False

def close_order(direction):
    """Send exit signal to TradersPost."""
    if SIM_MODE:
        log(f"[SIM] Would close {direction} position")
        return True

    if not WEBHOOK_URL:
        return False

    payload = {
        "password":      WEBHOOK_PASSWORD,
        "ticker":        "MES1!",
        "action":        "sell" if direction == "UP" else "buy",
        "quantity":      CONTRACTS,
        "closePosition": True,
    }
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        return r.status_code == 200
    except:
        return False

# ── Topstep risk guards ───────────────────────────────────────

DAILY_LOSS_LIMIT  = float(os.environ.get("DAILY_LOSS_LIMIT",  "1000"))
DAILY_LOSS_BUFFER = float(os.environ.get("DAILY_LOSS_BUFFER", "200"))
day_pnl           = 0.0  # tracks today's realized P&L in dollars

def risk_ok():
    """Check we have room to trade within Topstep's daily loss limit."""
    loss_today = -min(0.0, day_pnl)
    remaining  = DAILY_LOSS_LIMIT - loss_today
    if remaining < DAILY_LOSS_BUFFER:
        log(f"⚠️  Daily loss limit guard: ${remaining:.0f} remaining — skipping")
        return False
    return True

# ── Main bot loop ─────────────────────────────────────────────

def run_bot():
    global day_pnl
    log("ORB Bot started")

    while True:
        now = datetime.now(ET)

        # Reset at midnight
        if now.hour == 0 and now.minute == 0:
            day_pnl = 0.0
            state.update({
                "phase": "waiting", "high5": None, "low5": None,
                "direction": None, "result": None, "pnl_pts": None,
                "entry_idx": None, "today": None,
            })
            log("New day — state reset")
            time.sleep(60)
            continue

        # Skip weekends
        if now.weekday() >= 5:
            state["phase"] = "waiting"
            time.sleep(300)
            continue

        today_str = now.date().isoformat()

        # Already done today
        if state["today"] == today_str and state["phase"] == "done":
            time.sleep(60)
            continue

        # ── Before 9:30 ──
        if now.hour < 9 or (now.hour == 9 and now.minute < 30):
            state["phase"] = "waiting"
            time.sleep(30)
            continue

        # ── 9:30 - 9:34: build the range ──
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

        # ── 9:35: range is set — watch for breakout ──
        if now.hour == 9 and now.minute == 35 and state["today"] != today_str:
            state["today"] = today_str
            state["phase"] = "watching"
            log(f"Range set: HIGH={state['high5']} LOW={state['low5']} "
                f"SIZE={state['range_size']}")

        # ── 9:35 - 12:00: watch for breakout ──
        if state["phase"] in ("watching",) and state["high5"]:
            if not risk_ok():
                state["phase"] = "done"
                continue

            spy_1m = get_spy_1min()
            if spy_1m is None:
                time.sleep(15)
                continue

            post = spy_1m.between_time("09:35", "12:00")
            direction  = None
            entry_price_spy = None

            for ts, bar in post.iterrows():
                if float(bar["High"]) > state["high5"]:
                    direction       = "UP"
                    entry_price_spy = float(bar["High"])
                    break
                if float(bar["Low"]) < state["low5"]:
                    direction       = "DOWN"
                    entry_price_spy = float(bar["Low"])
                    break

            if direction:
                entry_idx = entry_price_spy * 10.0
                stop      = (entry_idx - STOP_POINTS
                             if direction == "UP"
                             else entry_idx + STOP_POINTS)
                target    = (entry_idx + TARGET_POINTS
                             if direction == "UP"
                             else entry_idx - TARGET_POINTS)

                log(f"Breakout {direction} at idx {entry_idx:.0f} "
                    f"stop={stop:.0f} target={target:.0f}")

                ok = place_order(direction)
                if ok:
                    state.update({
                        "phase":      "active",
                        "direction":  direction,
                        "entry_idx":  entry_idx,
                        "stop":       stop,
                        "target":     target,
                        "entry_time": datetime.now(ET).strftime("%H:%M:%S"),
                        "result":     "OPEN",
                        "pnl_pts":    0.0,
                    })

        # ── Active trade: monitor P&L ──
        if state["phase"] == "active":
            current = get_current_price()
            if current:
                idx = current * 10.0
                if state["direction"] == "UP":
                    pnl = idx - state["entry_idx"]
                else:
                    pnl = state["entry_idx"] - idx
                state["pnl_pts"] = round(pnl, 1)

            # Check exit conditions
            now2     = datetime.now(ET)
            entry_dt = datetime.strptime(
                f"{now2.date()} {state['entry_time']}",
                "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=ET)
            elapsed  = (now2 - entry_dt).total_seconds() / 60.0

            exit_reason = None
            if current:
                idx = current * 10.0
                if state["direction"] == "UP":
                    if idx <= state["stop"]:   exit_reason = "STOP"
                    if idx >= state["target"]: exit_reason = "TARGET"
                else:
                    if idx >= state["stop"]:   exit_reason = "STOP"
                    if idx <= state["target"]: exit_reason = "TARGET"

            if elapsed >= 30:    exit_reason = "TIMED"
            if now2.hour >= 12:  exit_reason = "HARD_CLOSE"

            if exit_reason:
                close_order(state["direction"])
                pnl_dollars = state["pnl_pts"] * 5.0 * CONTRACTS
                day_pnl    += pnl_dollars
                result      = "WIN" if state["pnl_pts"] > 0 else "LOSS"
                state.update({
                    "phase":  "done",
                    "result": result,
                })
                log(f"Closed: {exit_reason} | "
                    f"{state['pnl_pts']:+.1f}pts | ${pnl_dollars:+.0f}")

        state["last_update"] = datetime.now(ET).strftime("%H:%M:%S")
        time.sleep(15)

# ── Start bot thread ─────────────────────────────────────────

bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()

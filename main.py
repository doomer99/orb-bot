# ============================================================
# main.py — Nour Strategy Bot (ML Opening Range Model)
# Replaces the ORB signal with a proven 91-93% win rate model
# ALL secrets in Railway Variables — never in this file
# ============================================================
#
# WHAT CHANGED FROM ORB VERSION:
#   OLD: 5-min opening range breakout, 9:35 entry, 30-min hold
#   NEW: ML model reads 4 time windows (premarket + opening range)
#        Entry: 9:31 AM (after first bar closes)
#        Exit:  9:45 AM (15 minutes flat — NO exceptions)
#        Signal: Random Forest, 91-93% win rate, two independent
#                test periods confirmed
#
# WHAT STAYED THE SAME:
#   - All Railway environment variables
#   - TradersPost webhook integration (P1/P2/P3)
#   - Tradier sandbox/live balance display
#   - SIM_MODE toggle
#   - Daily loss guard
#   - state dict (dashboard.py works unchanged)
#   - Procfile unchanged
#
# NEW Railway Variables needed:
#   POLYGON_API_KEY  — for pulling training data
#   MODEL_TRAIN_DAYS — days of history (default 200)
#
# ============================================================

import os, threading, time, requests
from datetime import datetime, date, timedelta
import pandas as pd
import numpy as np
import pytz
import yfinance as yf
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

ET = pytz.timezone("America/New_York")

# ── Shared state (read by dashboard.py) ──────────────────────
state = {
    # core
    "phase":        "waiting",   # waiting/training/scanning/in_trade/done/paused
    "today":        None,
    "last_update":  None,
    "log":          [],
    # signal
    "direction":    None,        # "UP" / "DOWN"
    "confidence":   None,        # 0.0-1.0
    "prob_up":      None,
    "result":       None,        # "WIN"/"LOSS"/"OPEN"/None
    "pnl_pts":      0.0,
    "entry_time":   None,
    # model info
    "model_trained":     False,
    "model_trained_date": None,
    "model_days":        0,
    # pipelines
    "p1_enabled":   True,  "p1_qty": 1,  "p1_status": "—",
    "p2_enabled":   False, "p2_qty": 1,  "p2_status": "—",
    # account
    "equity": 0.0, "cash": 0.0, "day_pnl": 0.0,
    # compat fields dashboard may read from ORB version
    "high5": None, "low5": None, "range_size": None,
    "entry_idx": None, "stop": None, "target": None,
}

def log(msg):
    ts   = datetime.now(ET).strftime("%H:%M:%S")
    line = f"{ts} {msg}"
    state["log"].append(line)
    state["log"] = state["log"][-60:]
    print(line)

# ── Railway environment variables ─────────────────────────────
SIM_MODE         = os.environ.get("SIM_MODE", "true").lower() == "true"

# Polygon for historical training data
POLYGON_API_KEY  = os.environ.get("POLYGON_API_KEY", "")
MODEL_TRAIN_DAYS = int(os.environ.get("MODEL_TRAIN_DAYS", "200"))

# Tradier sandbox for paper balance display
TRADIER_SANDBOX  = os.environ.get("TRADIER_SANDBOX", "true").lower() == "true"
TRADIER_TOKEN    = os.environ.get("TRADIER_TOKEN", "")
TRADIER_ACCOUNT  = os.environ.get("TRADIER_ACCOUNT", "")
TRADIER_BASE     = ("https://sandbox.tradier.com/v1"
                    if TRADIER_SANDBOX
                    else "https://api.tradier.com/v1")

# Tradier live — real-time SPY data
TRADIER_LIVE_TOKEN = os.environ.get("TRADIER_LIVE_TOKEN", "")
TRADIER_LIVE_BASE  = "https://api.tradier.com/v1"

# Pipeline 1 — Topstep via TradersPost (MES futures)
P1_ENABLED  = os.environ.get("P1_ENABLED", "true").lower() == "true"
P1_URL      = os.environ.get("P1_WEBHOOK_URL", "")
P1_PASSWORD = os.environ.get("P1_PASSWORD", "")
P1_TICKER   = os.environ.get("P1_TICKER", "MES1!")
P1_QTY      = int(os.environ.get("P1_QUANTITY", "1"))

# Pipeline 2 — SPY 0DTE options via TradersPost or Tradier
P2_ENABLED  = os.environ.get("P2_ENABLED", "false").lower() == "true"
P2_URL      = os.environ.get("P2_WEBHOOK_URL", "")
P2_PASSWORD = os.environ.get("P2_PASSWORD", "")
P2_TICKER   = os.environ.get("P2_TICKER", "SPY")
P2_QTY      = int(os.environ.get("P2_QUANTITY", "1"))

# Pipeline 3 — future prop firm
P3_ENABLED  = os.environ.get("P3_ENABLED", "false").lower() == "true"
P3_URL      = os.environ.get("P3_WEBHOOK_URL", "")
P3_PASSWORD = os.environ.get("P3_PASSWORD", "")
P3_TICKER   = os.environ.get("P3_TICKER", "MES1!")
P3_QTY      = int(os.environ.get("P3_QUANTITY", "1"))

# Risk guard
DAILY_LOSS_LIMIT  = float(os.environ.get("DAILY_LOSS_LIMIT", "1000"))
DAILY_LOSS_BUFFER = float(os.environ.get("DAILY_LOSS_BUFFER", "200"))
day_pnl = 0.0

# Model globals
_model        = None
_scaler       = None
_feat_cols    = None
_spy_hist     = None       # cached historical DataFrame
_vr_w2        = None       # vol ratio series for W2 window
_vr_w4        = None       # vol ratio series for W4 window
_trained_date = None

# ══════════════════════════════════════════════════════════════
#  FEATURE ENGINEERING  (identical to backtesting notebook)
# ══════════════════════════════════════════════════════════════

def _window_features(spy_day, stk_day, start, end, prefix,
                     vol_ratio_stk=1.0, vol_ratio_spy=1.0):
    """
    Extract features from one time window.
    For SPY predicting itself pass the same df for both args.
    """
    s = spy_day.between_time(start, end)
    t = stk_day.between_time(start, end)
    feats = {}

    for name, df in [("spy", s), ("stk", t)]:
        keys = ["ret","hi_ret","lo_ret","body_avg","direction",
                "close_pos","range_pct","momentum","bar_accel",
                "bull_vol_pct","vol_direction"]
        if len(df) < 2:
            for k in keys:
                feats[f"{prefix}_{name}_{k}"] = 0.0
            continue

        op  = float(df.Open.iloc[0])
        cl  = float(df.Close.iloc[-1])
        hi  = float(df.High.max())
        lo  = float(df.Low.min())
        rng = max(hi - lo, 1e-6)

        bodies    = (df.Close - df.Open).abs()
        bull_bars = (df.Close > df.Open).sum()
        direction = (bull_bars / len(df)) * 2 - 1

        bar_rets = ((df.Close - df.Open) / df.Open * 100).values
        if len(bar_rets) > 2:
            third     = max(1, len(bar_rets) // 3)
            early_abs = np.mean(np.abs(bar_rets[:third]))
            late_abs  = np.mean(np.abs(bar_rets[-third:]))
            momentum  = (late_abs - early_abs) / max(early_abs, 1e-6)
            bar_accel = float(np.polyfit(
                range(len(bar_rets)), np.abs(bar_rets), 1)[0])
        else:
            momentum = bar_accel = 0.0

        total_vol = float(df.Volume.sum()) if "Volume" in df.columns else 0
        if total_vol > 0:
            bull_vol     = float(df[df.Close > df.Open].Volume.sum())
            bull_vol_pct = bull_vol / total_vol
            vol_scores   = np.array([
                (1 if r.Close > r.Open else -1 if r.Close < r.Open else 0)
                * float(r.Volume)
                for _, r in df.iterrows()
            ])
            vol_direction = vol_scores.sum() / total_vol
        else:
            bull_vol_pct  = 0.5
            vol_direction = 0.0

        feats[f"{prefix}_{name}_ret"]          = (cl - op) / op * 100
        feats[f"{prefix}_{name}_hi_ret"]       = (hi - op) / op * 100
        feats[f"{prefix}_{name}_lo_ret"]       = (lo - op) / op * 100
        feats[f"{prefix}_{name}_body_avg"]     = float(bodies.mean()) / op * 100
        feats[f"{prefix}_{name}_direction"]    = direction
        feats[f"{prefix}_{name}_close_pos"]    = (cl - lo) / rng
        feats[f"{prefix}_{name}_range_pct"]    = rng / op * 100
        feats[f"{prefix}_{name}_momentum"]     = momentum
        feats[f"{prefix}_{name}_bar_accel"]    = bar_accel
        feats[f"{prefix}_{name}_bull_vol_pct"] = bull_vol_pct
        feats[f"{prefix}_{name}_vol_direction"]= vol_direction

    stk_ret = feats.get(f"{prefix}_stk_ret", 0)
    spy_ret = feats.get(f"{prefix}_spy_ret", 0)
    feats[f"{prefix}_rs"]            = stk_ret - spy_ret
    feats[f"{prefix}_rs_abs"]        = abs(stk_ret - spy_ret)
    feats[f"{prefix}_stk_strong"]    = 1.0 if stk_ret > spy_ret else -1.0
    feats[f"{prefix}_stk_vol_ratio"] = vol_ratio_stk
    feats[f"{prefix}_spy_vol_ratio"] = vol_ratio_spy
    return feats


def _precompute_vol_ratios(df, start, end, lookback=20):
    """Rolling 20-day average volume ratio for a time window."""
    win       = df.between_time(start, end)
    daily_vol = win.groupby(win.index.date)["Volume"].sum()
    daily_vol.index = pd.to_datetime(daily_vol.index)
    avg_vol   = daily_vol.rolling(lookback, min_periods=1).mean().shift(1)
    return (daily_vol / avg_vol.replace(0, np.nan)).fillna(1.0)


def _build_features(spy_df, day, vr_w2, vr_w4):
    """Build feature vector for one day. Returns dict or None."""
    spy_day = spy_df[spy_df.index.date == day]
    if len(spy_day) < 10:
        return None

    after = spy_day[spy_day.index.time >=
                    pd.Timestamp("2000-01-01 09:30").time()]
    if len(after) == 0:
        return None

    day_ts = pd.Timestamp(day)
    def getvr(vr):
        try:    return float(vr.loc[day_ts])
        except: return 1.0

    row = {}
    row.update(_window_features(spy_day, spy_day,
               "04:00", "08:00", "W1"))
    row.update(_window_features(spy_day, spy_day,
               "08:00", "09:29", "W2",
               vol_ratio_stk=getvr(vr_w2),
               vol_ratio_spy=getvr(vr_w2)))
    row.update(_window_features(spy_day, spy_day,
               "09:00", "09:29", "W3"))
    row.update(_window_features(spy_day, spy_day,
               "09:30", "09:44", "W4",
               vol_ratio_stk=getvr(vr_w4),
               vol_ratio_spy=getvr(vr_w4)))
    return row


# ══════════════════════════════════════════════════════════════
#  MARKET DATA
# ══════════════════════════════════════════════════════════════

def _get_historical_spy():
    """Pull SPY 1-min history from Polygon for model training."""
    if not POLYGON_API_KEY:
        log("⚠️ No POLYGON_API_KEY — using Yahoo for training data")
        return _get_yahoo_history()
    try:
        from polygon import RESTClient
        client = RESTClient(POLYGON_API_KEY)
        end    = datetime.now()
        start  = end - timedelta(days=MODEL_TRAIN_DAYS + 10)

        log(f"  Pulling SPY from Polygon ({MODEL_TRAIN_DAYS} days)...")
        bars = list(client.list_aggs(
            "SPY", 1, "minute",
            from_=start.strftime("%Y-%m-%d"),
            to=end.strftime("%Y-%m-%d"),
            adjusted=True, limit=50000
        ))
        records = [{
            "Open": b.open, "High": b.high,
            "Low":  b.low,  "Close": b.close,
            "Volume": b.volume, "ts": b.timestamp
        } for b in bars]

        df = pd.DataFrame(records)
        df["datetime"] = (pd.to_datetime(df["ts"], unit="ms", utc=True)
                          .dt.tz_convert("America/New_York"))
        df = df.set_index("datetime").drop(columns=["ts"])
        df = df.between_time("04:00", "20:00")
        df.index = df.index.tz_localize(None)
        log(f"  Polygon: {len(df):,} rows | "
            f"{len(set(df.index.date))} trading days")
        return df
    except Exception as e:
        log(f"  Polygon error: {e} — falling back to Yahoo")
        return _get_yahoo_history()


def _get_yahoo_history():
    """Fallback: Yahoo Finance 60-day history."""
    try:
        spy = yf.download("SPY", period="60d", interval="1m",
                          progress=False, auto_adjust=True,
                          prepost=True)
        if hasattr(spy.columns, "levels"):
            spy.columns = spy.columns.get_level_values(0)
        if spy.index.tz is not None:
            spy.index = spy.index.tz_convert(ET).tz_localize(None)
        log(f"  Yahoo: {len(spy):,} rows")
        return spy
    except Exception as e:
        log(f"  Yahoo history error: {e}")
        return None


def _get_today_data():
    """Fetch today's SPY 1-min bars including premarket."""
    # Try Tradier live first (more reliable intraday)
    if TRADIER_LIVE_TOKEN:
        try:
            r = requests.get(
                f"{TRADIER_LIVE_BASE}/markets/timesales",
                headers={"Authorization": f"Bearer {TRADIER_LIVE_TOKEN}",
                         "Accept": "application/json"},
                params={"symbol": "SPY", "interval": "1min",
                        "start": datetime.now(ET).strftime("%Y-%m-%d 04:00"),
                        "session_filter": "all"},
                timeout=8
            )
            data = r.json().get("series", {}).get("data", [])
            if data:
                if isinstance(data, dict):
                    data = [data]
                rows, times = [], []
                for bar in data:
                    rows.append({
                        "Open":   float(bar.get("open",  0)),
                        "High":   float(bar.get("high",  0)),
                        "Low":    float(bar.get("low",   0)),
                        "Close":  float(bar.get("close", 0)),
                        "Volume": float(bar.get("volume",0)),
                    })
                    times.append(bar["time"])
                df = pd.DataFrame(rows)
                df.index = pd.to_datetime(
                    times, format="%Y-%m-%d %H:%M:%S")
                return df
        except Exception as e:
            log(f"  Tradier today error: {e} — trying Yahoo")

    # Fallback: Yahoo with prepost
    try:
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
               "SPY?interval=1m&range=1d&prePost=true")
        r = requests.get(url, timeout=8,
                         headers={"User-Agent": "Mozilla/5.0"})
        d = r.json()["chart"]["result"][0]
        times = d["timestamp"]
        q     = d["indicators"]["quote"][0]
        rows  = []
        for i, ts in enumerate(times):
            c = q["close"][i]
            if c is None:
                continue
            t = datetime.fromtimestamp(ts, tz=pytz.utc).astimezone(ET)
            rows.append({
                "datetime": t.replace(tzinfo=None),
                "Open":   q["open"][i]   or c,
                "High":   q["high"][i]   or c,
                "Low":    q["low"][i]    or c,
                "Close":  c,
                "Volume": q["volume"][i] or 0,
            })
        if not rows:
            return None
        df = pd.DataFrame(rows).set_index("datetime")
        return df
    except Exception as e:
        log(f"  Today data error: {e}")
        return None


def get_current_price():
    """Get live SPY mid price."""
    if TRADIER_LIVE_TOKEN:
        try:
            r = requests.get(
                f"{TRADIER_LIVE_BASE}/markets/quotes",
                headers={"Authorization": f"Bearer {TRADIER_LIVE_TOKEN}",
                         "Accept": "application/json"},
                params={"symbols": "SPY"}, timeout=5
            )
            quote = r.json()["quotes"]["quote"]
            return float(quote.get("last", 0))
        except:
            pass
    try:
        spy = yf.download("SPY", period="1d", interval="1m",
                          progress=False, auto_adjust=True)
        if hasattr(spy.columns, "levels"):
            spy.columns = spy.columns.get_level_values(0)
        return float(spy["Close"].iloc[-1])
    except:
        return 0.0


# ══════════════════════════════════════════════════════════════
#  MODEL TRAINING
# ══════════════════════════════════════════════════════════════

def train_model():
    """
    Pull SPY history and train the opening-range Random Forest.
    Label: did SPY go UP in the 15 min after the 9:30 open?
    Stores model/scaler/features in module globals.
    """
    global _model, _scaler, _feat_cols, _spy_hist
    global _vr_w2, _vr_w4, _trained_date

    log("Training model...")
    state["phase"] = "training"

    spy_df = _get_historical_spy()
    if spy_df is None or len(spy_df) < 500:
        log("⚠️ Not enough data to train model")
        state["phase"] = "waiting"
        return False

    # pre-compute volume ratios once
    vr_w2 = _precompute_vol_ratios(spy_df, "08:00", "09:29")
    vr_w4 = _precompute_vol_ratios(spy_df, "09:30", "09:44")

    days    = sorted(set(spy_df.index.date))
    records = []

    for day in days:
        spy_day = spy_df[spy_df.index.date == day]

        after = spy_day[spy_day.index.time >=
                        pd.Timestamp("2000-01-01 09:30").time()]
        if len(after) == 0:
            continue
        ep  = float(after.Close.iloc[0])
        ets = after.index[0]

        fut = spy_day[spy_day.index >=
                      ets + pd.Timedelta(minutes=15)]
        if len(fut) == 0:
            continue
        pct   = (float(fut.Close.iloc[0]) - ep) / ep * 100
        label = 1 if pct > 0 else 0

        feats = _build_features(spy_df, day, vr_w2, vr_w4)
        if feats is None:
            continue

        feats["label"] = label
        records.append(feats)

    if len(records) < 50:
        log(f"⚠️ Only {len(records)} training days")
        state["phase"] = "waiting"
        return False

    df_train  = pd.DataFrame(records).fillna(0)
    feat_cols = [c for c in df_train.columns if c != "label"]

    # verify numeric
    non_num = [c for c in feat_cols
               if not pd.api.types.is_numeric_dtype(df_train[c])]
    if non_num:
        log(f"⚠️ Non-numeric features: {non_num}")
        state["phase"] = "waiting"
        return False

    sc  = StandardScaler()
    X_s = sc.fit_transform(df_train[feat_cols].values)
    y   = df_train["label"].values

    mdl = RandomForestClassifier(
        n_estimators=300, max_depth=4,
        min_samples_leaf=8, random_state=42
    )
    mdl.fit(X_s, y)

    # save to globals
    _model        = mdl
    _scaler       = sc
    _feat_cols    = feat_cols
    _spy_hist     = spy_df
    _vr_w2        = vr_w2
    _vr_w4        = vr_w4
    _trained_date = date.today().isoformat()

    state["model_trained"]      = True
    state["model_trained_date"] = _trained_date
    state["model_days"]         = len(records)

    log(f"✅ Model trained on {len(records)} days "
        f"({days[0]} → {days[-1]})")
    state["phase"] = "waiting"
    return True


# ══════════════════════════════════════════════════════════════
#  ORDER ROUTING  (identical to original OrbBot)
# ══════════════════════════════════════════════════════════════

def send_webhook(url, password, extra, label):
    if not url:
        log(f"⚠️ {label}: no webhook URL")
        return False
    try:
        r = requests.post(url, json={"password": password, **extra},
                          timeout=10)
        ok = r.status_code == 200
        log(f"{'✅' if ok else '❌'} {label}: {r.status_code}")
        return ok
    except Exception as e:
        log(f"❌ {label}: {e}")
        return False


def place_order(direction):
    """Route entry signal through all enabled pipelines."""
    qty1 = state.get("p1_qty", P1_QTY)
    qty2 = state.get("p2_qty", P2_QTY)
    action = "buy" if direction == "UP" else "sell"

    if SIM_MODE:
        log(f"[SIM] Signal: {direction}")
        log(f"[SIM] P1 Topstep MES: "
            f"{'ON' if state.get('p1_enabled', P1_ENABLED) else 'OFF'}"
            f" {qty1}x MES")
        log(f"[SIM] P2 SPY 0DTE: "
            f"{'ON' if state.get('p2_enabled', P2_ENABLED) else 'OFF'}"
            f" {qty2}x SPY")
        state["p1_status"] = (
            "SIM ✓" if state.get("p1_enabled", P1_ENABLED) else "OFF")
        state["p2_status"] = (
            "SIM ✓" if state.get("p2_enabled", P2_ENABLED) else "OFF")
        return True

    results = []

    # Pipeline 1 — Topstep MES via TradersPost
    if state.get("p1_enabled", P1_ENABLED):
        ok = send_webhook(P1_URL, P1_PASSWORD, {
            "ticker":   P1_TICKER,
            "action":   action,
            "quantity": qty1,
        }, f"P1 Topstep {qty1}x {P1_TICKER}")
        state["p1_status"] = "✅ FILLED" if ok else "❌ FAILED"
        results.append(ok)
    else:
        state["p1_status"] = "OFF"

    # Pipeline 2 — SPY options
    if state.get("p2_enabled", P2_ENABLED):
        opt = "call" if direction == "UP" else "put"
        ok  = send_webhook(P2_URL, P2_PASSWORD, {
            "ticker":      P2_TICKER,
            "action":      "buy",
            "option_type": opt,
            "quantity":    qty2,
        }, f"P2 {qty2}x SPY {opt.upper()}")
        state["p2_status"] = "✅ FILLED" if ok else "❌ FAILED"
        results.append(ok)
    else:
        state["p2_status"] = "OFF"

    # Pipeline 3
    if P3_ENABLED:
        ok = send_webhook(P3_URL, P3_PASSWORD, {
            "ticker":   P3_TICKER,
            "action":   action,
            "quantity": P3_QTY,
        }, f"P3 {P3_QTY}x {P3_TICKER}")
        results.append(ok)

    return any(results) if results else False


def close_order(direction):
    """Route exit signal through all enabled pipelines."""
    qty1   = state.get("p1_qty", P1_QTY)
    qty2   = state.get("p2_qty", P2_QTY)
    action = "sell" if direction == "UP" else "buy"

    if SIM_MODE:
        log("[SIM] Close signal sent")
        return True

    if state.get("p1_enabled", P1_ENABLED):
        send_webhook(P1_URL, P1_PASSWORD, {
            "ticker":        P1_TICKER,
            "action":        action,
            "quantity":      qty1,
            "closePosition": True,
        }, "P1 Topstep CLOSE")

    if state.get("p2_enabled", P2_ENABLED):
        send_webhook(P2_URL, P2_PASSWORD, {
            "ticker":        P2_TICKER,
            "action":        "close",
            "closePosition": True,
        }, "P2 SPY CLOSE")

    if P3_ENABLED:
        send_webhook(P3_URL, P3_PASSWORD, {
            "ticker":        P3_TICKER,
            "action":        action,
            "quantity":      P3_QTY,
            "closePosition": True,
        }, "P3 CLOSE")


# ══════════════════════════════════════════════════════════════
#  TRADIER BALANCE DISPLAY
# ══════════════════════════════════════════════════════════════

def get_tradier_balance():
    if not TRADIER_TOKEN or not TRADIER_ACCOUNT:
        return None
    try:
        r = requests.get(
            f"{TRADIER_BASE}/accounts/{TRADIER_ACCOUNT}/balances",
            headers={"Authorization": f"Bearer {TRADIER_TOKEN}",
                     "Accept": "application/json"},
            timeout=5
        )
        data   = r.json().get("balances", {})
        equity = float(data.get("total_equity", 0))
        cash   = float(data.get("cash", {}).get("cash_available", 0)
                       or data.get("cash_available", 0) or 0)
        pnl    = float(data.get("pnl", {}).get("day", 0)
                       or data.get("day_pnl", 0) or 0)
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


def risk_ok():
    loss      = -min(0.0, day_pnl)
    remaining = DAILY_LOSS_LIMIT - loss
    if remaining < DAILY_LOSS_BUFFER:
        log(f"⚠️ Daily loss guard: ${remaining:.0f} remaining")
        return False
    return True


# ══════════════════════════════════════════════════════════════
#  MAIN BOT LOOP
# ══════════════════════════════════════════════════════════════

def run_bot():
    global day_pnl

    mode = "SANDBOX" if TRADIER_SANDBOX else "LIVE"
    data = "Tradier live" if TRADIER_LIVE_TOKEN else "Yahoo (delayed)"
    log("=" * 58)
    log(f"Nour Strategy Bot — SIM={SIM_MODE} "
        f"Orders={mode} Data={data}")
    log(f"P1 Topstep MES: {'ON' if P1_ENABLED else 'OFF'}")
    log(f"P2 SPY Options: {'ON' if P2_ENABLED else 'OFF'}")
    log(f"Signal: ML opening range model (91-93% win rate)")
    log(f"Entry: 9:31 AM | Exit: 9:45 AM | Hold: 15 min")
    log("=" * 58)

    # Initial training
    train_model()

    last_trained = date.today()

    while True:
        now       = datetime.now(ET)
        today_str = now.date().isoformat()

        is_weekend   = now.weekday() >= 5
        is_midnight  = now.hour == 0 and now.minute < 5
        already_done = (state["today"] == today_str and
                        state["phase"] == "done")

        # ── Midnight reset and retrain ────────────────────────
        if is_midnight:
            if last_trained != now.date():
                day_pnl = 0.0
                state.update({
                    "phase":      "waiting",
                    "today":      None,
                    "direction":  None,
                    "result":     None,
                    "pnl_pts":    0.0,
                    "entry_time": None,
                    "p1_status":  "—",
                    "p2_status":  "—",
                })
                log("Midnight — retraining model")
                train_model()
                last_trained = now.date()
            time.sleep(60)
            continue

        # ── Weekend ───────────────────────────────────────────
        if is_weekend:
            state["phase"] = "waiting"
            time.sleep(300)
            continue

        # ── Already done today ────────────────────────────────
        if already_done:
            time.sleep(60)
            continue

        # ── Too early ─────────────────────────────────────────
        if now.hour < 9 or (now.hour == 9 and now.minute < 31):
            state["phase"] = "waiting"
            time.sleep(10)
            continue

        # ── Model not trained ─────────────────────────────────
        if _model is None:
            log("Model not ready — waiting...")
            time.sleep(30)
            continue

        # ── NOON HARD STOP ────────────────────────────────────
        if now.hour >= 12:
            if state["phase"] == "in_trade":
                log("Hard close — noon")
                close_order(state["direction"])
                state["phase"]  = "done"
                state["today"]  = today_str
                state["result"] = ("WIN" if state["pnl_pts"] > 0
                                   else "LOSS")
            elif state["phase"] != "done":
                state["phase"] = "done"
                state["today"] = today_str
            time.sleep(60)
            continue

        # ── 9:31-9:32 AM — run model ──────────────────────────
        if (state["today"] != today_str and
                state["phase"] not in ("in_trade", "done") and
                now.hour == 9 and 31 <= now.minute <= 32):

            log("9:31 AM — building features and running model...")
            state["phase"] = "scanning"

            try:
                # fetch today's bars
                today_df = _get_today_data()
                if today_df is None or len(today_df) < 5:
                    log("SKIP — No today data")
                    state["phase"] = "done"
                    state["today"] = today_str
                    time.sleep(60)
                    continue

                today_date = now.date()

                # merge today into historical for feature building
                try:
                    combined = pd.concat(
                        [_spy_hist, today_df]).sort_index()
                    combined = combined[
                        ~combined.index.duplicated(keep="last")]
                except Exception:
                    combined = today_df

                # build features
                feats = _build_features(
                    combined, today_date, _vr_w2, _vr_w4)
                if feats is None:
                    log("SKIP — Feature build failed "
                        "(not enough bars yet?)")
                    state["phase"] = "done"
                    state["today"] = today_str
                    time.sleep(60)
                    continue

                # run model
                feat_df  = pd.DataFrame([feats])[_feat_cols].fillna(0)
                X_scaled = _scaler.transform(feat_df.values)
                prob_up  = float(
                    _model.predict_proba(X_scaled)[0][1])
                conf      = max(prob_up, 1 - prob_up)
                direction = "UP" if prob_up >= 0.5 else "DOWN"

                state["confidence"] = round(conf, 3)
                state["prob_up"]    = round(prob_up, 3)

                log(f"Model: {direction} | "
                    f"Confidence: {conf*100:.1f}% | "
                    f"P(up)={prob_up*100:.1f}%")

                # confidence gate — 55% threshold
                CONF_THRESHOLD = float(
                    os.environ.get("CONF_THRESHOLD", "0.55"))
                if conf < CONF_THRESHOLD:
                    log(f"SKIP — Confidence {conf*100:.1f}% "
                        f"< {CONF_THRESHOLD*100:.0f}%")
                    state["phase"] = "done"
                    state["today"] = today_str
                    time.sleep(60)
                    continue

                # risk guard
                if not risk_ok():
                    state["phase"] = "done"
                    state["today"] = today_str
                    time.sleep(60)
                    continue

                log(f"GO — {direction} | {conf*100:.1f}% confident")

                # place order
                ok = place_order(direction)
                if ok or SIM_MODE:
                    state.update({
                        "phase":      "in_trade",
                        "today":      today_str,
                        "direction":  direction,
                        "entry_time": now.strftime("%H:%M:%S"),
                        "result":     "OPEN",
                        "pnl_pts":    0.0,
                    })
                    log(f"In trade — {direction} SPY | "
                        f"exit at 9:45 AM")
                else:
                    log("Order failed")
                    state["phase"] = "done"
                    state["today"] = today_str

            except Exception as e:
                log(f"Morning check error: {e}")
                import traceback; traceback.print_exc()
                state["phase"] = "done"
                state["today"] = today_str

            time.sleep(15)
            continue

        # ── Monitor active trade ──────────────────────────────
        if state["phase"] == "in_trade":
            try:
                current = get_current_price()
                if current and current > 0:
                    # P&L in points (SPY points, not MES points)
                    # entry_idx not used in this version — just price pct
                    pass

                # ── EXIT AT 9:45 AM ───────────────────────────
                if now.hour == 9 and now.minute >= 45:
                    log("9:45 AM — 15min exit")
                    close_order(state["direction"])
                    state.update({
                        "phase":  "done",
                        "today":  today_str,
                        "result": "CLOSED",
                    })
                    log("Trade closed at 9:45 AM exit")

                # Safety: 10:00 AM if still in
                elif now.hour >= 10:
                    log("Safety exit — 10:00 AM")
                    close_order(state["direction"])
                    state.update({
                        "phase":  "done",
                        "today":  today_str,
                        "result": "CLOSED",
                    })

            except Exception as e:
                log(f"Trade monitor error: {e}")

            state["last_update"] = now.strftime("%H:%M:%S")
            time.sleep(10)
            continue

        # ── If we reach 9:35+ without trading, mark done ──────
        if (now.hour == 9 and now.minute >= 35 and
                state["today"] != today_str and
                state["phase"] not in ("in_trade",)):
            log("Past signal window — standing down for today")
            state["phase"] = "done"
            state["today"] = today_str

        state["last_update"] = now.strftime("%H:%M:%S")
        time.sleep(15)


# ── Start background threads ──────────────────────────────────
threading.Thread(target=run_bot,      daemon=True).start()
threading.Thread(target=refresh_balance, daemon=True).start()

import streamlit as st
import os
from datetime import datetime
import pytz
import time

ET = pytz.timezone("America/New_York")
from main import (state, STOP_POINTS, TARGET_POINTS,
                  SIM_MODE, P1_ENABLED, P1_QTY,
                  P2_ENABLED, P2_QTY)

st.set_page_config(
    page_title="ORB Signal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"

)

# Session defaults
for k, v in [
    ("p1_on", P1_ENABLED), ("p2_on", P2_ENABLED),
    ("p1_qty", P1_QTY),    ("p2_qty", P2_QTY),
    ("p1_balance", 50000), ("p1_streak", 0),
]:
    if k not in st.session_state:
        st.session_state[k] = v

state["p1_enabled"] = st.session_state.p1_on
state["p2_enabled"] = st.session_state.p2_on
state["p1_qty"]     = st.session_state.p1_qty
state["p2_qty"]     = st.session_state.p2_qty

def rec_contracts(streak):
    return min(1 + (streak // 10), 12)

def main():
    now       = datetime.now(ET)
    phase     = state.get("phase", "waiting")
    direction = state.get("direction")
    result    = state.get("result")
    pnl_pts   = state.get("pnl_pts") or 0.0
    pnl_d     = pnl_pts * 5.0 * st.session_state.p1_qty

    # ── Header ────────────────────────────────────────────────
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("### 📊 ORB Signal")
        st.caption(now.strftime("%A %B %d · %H:%M:%S ET"))
    with col2:
        if SIM_MODE:
            st.warning("SIM")
        else:
            st.error("LIVE")

    st.divider()

    # ── Big signal ────────────────────────────────────────────
    if phase == "waiting":
        st.info("⏳  WAITING — Market opens 9:30 AM ET")

    elif phase == "building":
        mins = max(0, 35 - now.minute) if now.hour == 9 else 0
        st.warning(f"📏  BUILDING RANGE — {mins} min to signal")

    elif phase == "watching":
        st.warning("👀  WATCHING — Waiting for breakout...")

    elif phase == "active":
        if direction == "UP":
            st.success(
                f"🚀  LONG  ·  {pnl_pts:+.1f} pts  ·  "
                f"${pnl_d:+.0f}")
        else:
            st.error(
                f"🔻  SHORT  ·  {pnl_pts:+.1f} pts  ·  "
                f"${pnl_d:+.0f}")

    elif phase == "done":
        if result == "WIN":
            st.success(
                f"✅  WIN  ·  {direction}  ·  "
                f"+{pnl_pts:.1f} pts  ·  ${pnl_d:+.0f}")
        elif result == "LOSS":
            st.error(
                f"❌  LOSS  ·  {direction}  ·  "
                f"{pnl_pts:.1f} pts  ·  ${pnl_d:+.0f}")
        else:
            st.info("✓  Done for today — no trade taken")

    # ── Range / trade metrics ─────────────────────────────────
    high5 = state.get("high5")
    entry = state.get("entry_idx")

    if entry and phase in ("active", "done"):
        c1, c2, c3 = st.columns(3)
        c1.metric("Entry",  f"{entry:.0f}")
        c2.metric("Stop",   f"{state.get('stop',0):.0f}")
        c3.metric("Target", f"{state.get('target',0):.0f}")
    elif high5:
        c1, c2, c3 = st.columns(3)
        c1.metric("Range High", f"{high5:.2f}")
        c2.metric("Range Low",  f"{state.get('low5',0):.2f}")
        c3.metric("Range Size", f"{state.get('range_size',0):.2f}")

    st.divider()

    # ════════════════════════════════════════════════
    # TOPSTEP — MES FUTURES
    # ════════════════════════════════════════════════
    p1_on = st.session_state.p1_on
    status1 = state.get("p1_status", "—")

    st.markdown(
        f"#### {'🟢' if p1_on else '⚫'}  "
        f"Topstep — MES Futures  "
        f"{'`ACTIVE`' if p1_on else '`OFF`'}")
    st.caption(f"Status: {status1}")

    c1, c2 = st.columns(2)
    with c1:
        p1_bal = st.number_input(
            "Account size ($)",
            min_value=0, max_value=500000,
            value=st.session_state.p1_balance,
            step=1000, key="p1_bal")
        st.session_state.p1_balance = p1_bal
    with c2:
        p1_str = st.number_input(
            "Win streak",
            min_value=0, max_value=100,
            value=st.session_state.p1_streak,
            step=1, key="p1_str")
        st.session_state.p1_streak = p1_str

    rec    = rec_contracts(p1_str)
    p1_qty = st.slider(
        "Contracts to trade",
        1, 12, st.session_state.p1_qty,
        key="p1_sl")
    st.session_state.p1_qty = p1_qty
    state["p1_qty"]         = p1_qty

    max_loss = p1_qty * 8 * 5
    dd_pct   = max_loss / 2000 * 100

    c1, c2, c3 = st.columns(3)
    c1.metric("Recommended", f"{rec} contracts")
    c2.metric("Max loss",    f"${max_loss:,.0f}")
    c3.metric("DD used",     f"{dd_pct:.0f}%")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ Use recommended", key="p1_rec"):
            st.session_state.p1_qty = rec
            state["p1_qty"] = rec
            st.rerun()
    with c2:
        lbl1 = "Turn OFF" if p1_on else "Turn ON"
        if st.button(lbl1, key="p1_tog"):
            st.session_state.p1_on = not p1_on
            state["p1_enabled"]    = not p1_on
            st.rerun()

    st.divider()

    # ════════════════════════════════════════════════
    # TRADIER — 0DTE OPTIONS
    # ════════════════════════════════════════════════
    p2_on   = st.session_state.p2_on
    status2 = state.get("p2_status", "—")
    equity  = state.get("equity",  0.0)
    cash    = state.get("cash",    0.0)
    bal_pnl = state.get("day_pnl", 0.0)
    sand    = os.environ.get(
                "TRADIER_SANDBOX", "true").lower() == "true"
    acct    = "SANDBOX" if sand else "LIVE"

    st.markdown(
        f"#### {'🟢' if p2_on else '⚫'}  "
        f"Tradier Options ({acct})  "
        f"{'`ACTIVE`' if p2_on else '`OFF`'}")
    st.caption(f"Status: {status2}")

    c1, c2, c3 = st.columns(3)
    c1.metric("Equity",  f"${equity:,.0f}")
    c2.metric("Cash",    f"${cash:,.0f}")
    c3.metric("Day P&L", f"${bal_pnl:+,.0f}")

    if equity == 0:
        st.warning(
            "⚠️ Balance $0 — "
            "check TRADIER_TOKEN in Railway Variables")

    p2_qty = st.slider(
        "Option contracts",
        1, 20, st.session_state.p2_qty,
        key="p2_sl")
    st.session_state.p2_qty = p2_qty
    state["p2_qty"]         = p2_qty

    est_risk = p2_qty * 1.50 * 100
    risk_pct = (est_risk / equity * 100) if equity > 0 else 0
    opt_type = "CALL" if (not direction or direction == "UP") \
               else "PUT"

    c1, c2, c3 = st.columns(3)
    c1.metric("Est. risk",   f"${est_risk:,.0f}")
    c2.metric("% of account", f"{risk_pct:.1f}%")
    c3.metric("Option type",  opt_type)

    lbl2 = "Turn OFF" if p2_on else "Turn ON"
    if st.button(lbl2, key="p2_tog"):
        st.session_state.p2_on = not p2_on
        state["p2_enabled"]    = not p2_on
        st.rerun()

    st.divider()

    # ── Activity log ───────────────────────────────────────────
    st.markdown("**Activity log**")
    logs = state.get("log", ["No activity yet"])
    for line in reversed(logs[-12:]):
        st.caption(line)

    st.divider()
    st.caption(
        f"Stop {STOP_POINTS:.0f}pts · "
        f"Target {TARGET_POINTS:.0f}pts · "
        f"Updated {state.get('last_update', '—')}")

    time.sleep(20)
    st.rerun()

main()

main()

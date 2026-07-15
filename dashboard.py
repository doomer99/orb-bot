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

    # Header
    c1, c2 = st.columns([5, 1])
    with c1:
        st.markdown("## 📊 ORB Signal")
        st.caption(now.strftime("%A %B %d, %Y  ·  %H:%M:%S ET"))
    with c2:
        if SIM_MODE:
            st.warning("SIM MODE")
        else:
            st.error("LIVE")

    st.divider()

    # Signal banner — full width
    if phase == "waiting":
        st.info("⏳   WAITING — Market opens at 9:30 AM ET")
    elif phase == "building":
        mins = max(0, 35 - now.minute) if now.hour == 9 else 0
        st.warning(f"📏   BUILDING RANGE — {mins} minutes until signal")
    elif phase == "watching":
        st.warning("👀   WATCHING — Range set, waiting for breakout...")
    elif phase == "active":
        if direction == "UP":
            st.success(f"🚀   LONG  ·  {pnl_pts:+.1f} pts  ·  ${pnl_d:+,.0f}")
        else:
            st.error(f"🔻   SHORT  ·  {pnl_pts:+.1f} pts  ·  ${pnl_d:+,.0f}")
    elif phase == "done":
        if result == "WIN":
            st.success(f"✅   WIN  ·  {direction}  ·  +{pnl_pts:.1f} pts  ·  ${pnl_d:+,.0f}")
        elif result == "LOSS":
            st.error(f"❌   LOSS  ·  {direction}  ·  {pnl_pts:.1f} pts  ·  ${pnl_d:+,.0f}")
        else:
            st.info("✓   Done for today — no trade taken")

    # Range or trade metrics
    high5 = state.get("high5")
    entry = state.get("entry_idx")

    if entry and phase in ("active", "done"):
        c1, c2, c3 = st.columns(3)
        c1.metric("Entry",  f"{entry:.0f}")
        c2.metric("Stop",   f"{state.get('stop', 0):.0f}")
        c3.metric("Target", f"{state.get('target', 0):.0f}")
    elif high5:
        c1, c2, c3 = st.columns(3)
        c1.metric("Range High", f"{high5:.2f}")
        c2.metric("Range Low",  f"{state.get('low5', 0):.2f}")
        c3.metric("Range Size", f"{state.get('range_size', 0):.2f}")

    st.divider()

    # Two column layout
    left, right = st.columns(2)

    # LEFT — TOPSTEP
    with left:
        p1_on   = st.session_state.p1_on
        status1 = state.get("p1_status", "—")
        icon1   = "🟢" if p1_on else "⚫"

        st.markdown(f"#### {icon1}  Topstep — MES Futures")
        st.caption(f"{'ACTIVE' if p1_on else 'OFF'}  ·  {status1}")

        st.number_input(
            "Account size ($)",
            min_value=0, max_value=500000,
            value=st.session_state.p1_balance,
            step=1000, key="p1_bal",
            on_change=lambda: setattr(
                st.session_state, 'p1_balance',
                st.session_state.p1_bal))

        st.number_input(
            "Win streak",
            min_value=0, max_value=100,
            value=st.session_state.p1_streak,
            step=1, key="p1_str",
            on_change=lambda: setattr(
                st.session_state, 'p1_streak',
                st.session_state.p1_str))

        streak = st.session_state.p1_streak
        rec    = rec_contracts(streak)

        p1_qty = st.slider(
            "Contracts to trade",
            1, 12, st.session_state.p1_qty,
            key="p1_sl")
        st.session_state.p1_qty = p1_qty
        state["p1_qty"]         = p1_qty

        max_loss = p1_qty * 8 * 5
        dd_pct   = max_loss / 2000 * 100

        m1, m2, m3 = st.columns(3)
        m1.metric("Recommended", f"{rec}c")
        m2.metric("Max loss",    f"${max_loss:,.0f}")
        m3.metric("DD limit %",  f"{dd_pct:.0f}%")

        b1, b2 = st.columns(2)
        with b1:
            if st.button("✅ Use recommended", key="p1_rec"):
                st.session_state.p1_qty = rec
                state["p1_qty"]         = rec
                st.rerun()
        with b2:
            if st.button(
                    "Turn OFF" if p1_on else "Turn ON",
                    key="p1_tog"):
                st.session_state.p1_on = not p1_on
                state["p1_enabled"]    = not p1_on
                st.rerun()

    # RIGHT — TRADIER OPTIONS
    with right:
        p2_on    = st.session_state.p2_on
        status2  = state.get("p2_status", "—")
        icon2    = "🟢" if p2_on else "⚫"
        equity   = state.get("equity",  0.0)
        cash     = state.get("cash",    0.0)
        bal_pnl  = state.get("day_pnl", 0.0)
        sand     = os.environ.get(
                       "TRADIER_SANDBOX", "true"
                   ).lower() == "true"
        acct     = "SANDBOX" if sand else "LIVE"
        opt_type = "CALL" if (
            not direction or direction == "UP") else "PUT"

        st.markdown(
            f"#### {icon2}  Tradier Options ({acct})")
        st.caption(
            f"{'ACTIVE' if p2_on else 'OFF'}  ·  {status2}")

        m1, m2, m3 = st.columns(3)
        m1.metric("Equity",  f"${equity:,.0f}")
        m2.metric("Cash",    f"${cash:,.0f}")
        m3.metric("Day P&L", f"${bal_pnl:+,.0f}")

        if equity == 0:
            st.warning("⚠️ Check TRADIER_TOKEN in Railway")

        p2_qty = st.slider(
            "Option contracts",
            1, 20, st.session_state.p2_qty,
            key="p2_sl")
        st.session_state.p2_qty = p2_qty
        state["p2_qty"]         = p2_qty

        est_risk = p2_qty * 150
        risk_pct = (est_risk / equity * 100) if equity > 0 else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Est. risk",    f"${est_risk:,.0f}")
        m2.metric("% of account", f"{risk_pct:.1f}%")
        m3.metric("Option type",  opt_type)

        if st.button(
                "Turn OFF" if p2_on else "Turn ON",
                key="p2_tog"):
            st.session_state.p2_on = not p2_on
            state["p2_enabled"]    = not p2_on
            st.rerun()

    st.divider()

    # Activity log
    st.markdown("**Activity log**")
    logs = state.get("log", ["No activity yet"])
    for line in reversed(logs[-12:]):
        st.caption(line)

    st.divider()
    st.caption(
        f"Stop {STOP_POINTS:.0f}pts  ·  "
        f"Target {TARGET_POINTS:.0f}pts  ·  "
        f"Updated {state.get('last_update', '—')}")

    time.sleep(20)
    st.rerun()

main()

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
    page_title="5-Min NY Open ORB",
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

    # ── Header ────────────────────────────────────────────────
    c1, c2 = st.columns([5, 1])
    with c1:
        st.markdown("## 5-Minute New York Open ORB")
        st.caption(
            now.strftime("%A %B %d, %Y  ·  %H:%M:%S ET"))
    with c2:
        if SIM_MODE:
            st.warning("SIM")
        else:
            st.error("LIVE")

    st.divider()

    # ── Signal banner ─────────────────────────────────────────
    if phase == "waiting":
        st.markdown("""
        <div style='background:#1a1f2e;border-radius:8px;
        padding:20px 24px;text-align:center;
        border:1px solid #2a3040'>
        <span style='font-size:28px;color:#4a6080'>
        ⏳  WAITING</span><br>
        <span style='color:#3a5060;font-size:14px'>
        Market opens at 9:30 AM ET</span>
        </div>""", unsafe_allow_html=True)

    elif phase == "building":
        mins = max(0, 35 - now.minute) \
               if now.hour == 9 else 0
        st.markdown(f"""
        <div style='background:#1a1a0a;border-radius:8px;
        padding:20px 24px;text-align:center;
        border:1px solid #3a3010'>
        <span style='font-size:28px;color:#f0a500'>
        📏  BUILDING RANGE</span><br>
        <span style='color:#6a5020;font-size:14px'>
        {mins} minutes until signal</span>
        </div>""", unsafe_allow_html=True)

    elif phase == "watching":
        st.markdown("""
        <div style='background:#1a1a0a;border-radius:8px;
        padding:20px 24px;text-align:center;
        border:1px solid #3a3010'>
        <span style='font-size:28px;color:#f0a500'>
        👀  WATCHING</span><br>
        <span style='color:#6a5020;font-size:14px'>
        Range set — waiting for breakout</span>
        </div>""", unsafe_allow_html=True)

    elif phase == "active" and direction == "UP":
        st.markdown(f"""
        <div style='background:#0a1f0f;border-radius:8px;
        padding:20px 24px;text-align:center;
        border:2px solid #2ecc71'>
        <span style='font-size:36px;color:#2ecc71;
        font-weight:700'>🚀  BUY — LONG</span><br>
        <span style='color:#1a8a44;font-size:16px'>
        {pnl_pts:+.1f} pts &nbsp;·&nbsp;
        ${pnl_d:+,.0f}</span>
        </div>""", unsafe_allow_html=True)

    elif phase == "active" and direction == "DOWN":
        st.markdown(f"""
        <div style='background:#1f0a0a;border-radius:8px;
        padding:20px 24px;text-align:center;
        border:2px solid #ff5252'>
        <span style='font-size:36px;color:#ff5252;
        font-weight:700'>🔻  SELL — SHORT</span><br>
        <span style='color:#8a1a1a;font-size:16px'>
        {pnl_pts:+.1f} pts &nbsp;·&nbsp;
        ${pnl_d:+,.0f}</span>
        </div>""", unsafe_allow_html=True)

    elif phase == "done":
        if result == "WIN":
            st.markdown(f"""
            <div style='background:#0a1f0f;border-radius:8px;
            padding:20px 24px;text-align:center;
            border:2px solid #2ecc71'>
            <span style='font-size:32px;color:#2ecc71;
            font-weight:700'>✅  WIN</span><br>
            <span style='color:#1a8a44;font-size:15px'>
            {direction} &nbsp;·&nbsp;
            +{pnl_pts:.1f} pts &nbsp;·&nbsp;
            ${pnl_d:+,.0f}</span>
            </div>""", unsafe_allow_html=True)
        elif result == "LOSS":
            st.markdown(f"""
            <div style='background:#1f0a0a;border-radius:8px;
            padding:20px 24px;text-align:center;
            border:2px solid #ff5252'>
            <span style='font-size:32px;color:#ff5252;
            font-weight:700'>❌  LOSS</span><br>
            <span style='color:#8a1a1a;font-size:15px'>
            {direction} &nbsp;·&nbsp;
            {pnl_pts:.1f} pts &nbsp;·&nbsp;
            ${pnl_d:+,.0f}</span>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style='background:#1a1f2e;border-radius:8px;
            padding:20px 24px;text-align:center;
            border:1px solid #2a3040'>
            <span style='font-size:28px;color:#4a6080'>
            ✓  NO TRADE TODAY</span>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Range / trade metrics ─────────────────────────────────
    high5 = state.get("high5")
    entry = state.get("entry_idx")

    if entry and phase in ("active", "done"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Entry",     f"{entry:.0f}")
        c2.metric("Stop",      f"{state.get('stop',0):.0f}")
        c3.metric("Target",    f"{state.get('target',0):.0f}")
        c4.metric("Live P&L",  f"${pnl_d:+,.0f}")
    elif high5:
        c1, c2, c3 = st.columns(3)
        c1.metric("Range High", f"{high5:.2f}")
        c2.metric("Range Low",
                  f"{state.get('low5',0):.2f}")
        c3.metric("Range Size",
                  f"{state.get('range_size',0):.2f}")

    st.divider()

    # ── Two columns with gap ──────────────────────────────────
    left, gap, right = st.columns([5, 1, 5])

    # ════════════════════════════════════════
    # LEFT — TOPSTEP MES FUTURES
    # ════════════════════════════════════════
    with left:
        p1_on   = st.session_state.p1_on
        status1 = state.get("p1_status", "—")
        icon1   = "🟢" if p1_on else "⚫"

        st.markdown(
            f"#### {icon1}  Topstep — MES Futures")
        st.caption(
            f"{'● ACTIVE' if p1_on else '○ OFF'}"
            f"  ·  {status1}")

        st.markdown("---")

        c1, c2 = st.columns(2)
        with c1:
            bal = st.number_input(
                "Account size ($)",
                min_value=0, max_value=500000,
                value=st.session_state.p1_balance,
                step=1000, key="p1_bal")
            st.session_state.p1_balance = bal
        with c2:
            streak = st.number_input(
                "Win streak",
                min_value=0, max_value=100,
                value=st.session_state.p1_streak,
                step=1, key="p1_str")
            st.session_state.p1_streak = streak

        rec    = rec_contracts(streak)
        p1_qty = st.slider(
            "Contracts", 1, 12,
            st.session_state.p1_qty, key="p1_sl")
        st.session_state.p1_qty = p1_qty
        state["p1_qty"]         = p1_qty

        max_loss = p1_qty * 8 * 5
        dd_pct   = max_loss / 2000 * 100

        m1, m2, m3 = st.columns(3)
        m1.metric("Recommended", f"{rec}c")
        m2.metric("Max loss",    f"${max_loss:,.0f}")
        m3.metric("DD limit",    f"{dd_pct:.0f}%")

        st.markdown("<br>", unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        with b1:
            if st.button(
                    "✅ Use recommended",
                    key="p1_rec"):
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

    # Gap column — empty, just spacing
    with gap:
        st.markdown("")

    # ════════════════════════════════════════
    # RIGHT — TRADIER OPTIONS
    # ════════════════════════════════════════
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
            not direction or direction == "UP"
        ) else "PUT"

        st.markdown(
            f"#### {icon2}  Tradier Options ({acct})")
        st.caption(
            f"{'● ACTIVE' if p2_on else '○ OFF'}"
            f"  ·  {status2}")

        st.markdown("---")

        m1, m2, m3 = st.columns(3)
        m1.metric("Equity",  f"${equity:,.0f}")
        m2.metric("Cash",    f"${cash:,.0f}")
        m3.metric("Day P&L", f"${bal_pnl:+,.0f}")

        if equity == 0:
            st.warning(
                "⚠️ Check TRADIER_TOKEN in Railway")

        p2_qty = st.slider(
            "Option contracts", 1, 20,
            st.session_state.p2_qty, key="p2_sl")
        st.session_state.p2_qty = p2_qty
        state["p2_qty"]         = p2_qty

        est_risk = p2_qty * 150
        risk_pct = (
            est_risk / equity * 100
        ) if equity > 0 else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Est. risk",    f"${est_risk:,.0f}")
        m2.metric("% of account", f"{risk_pct:.1f}%")
        m3.metric("Option type",  opt_type)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(
                "Turn OFF" if p2_on else "Turn ON",
                key="p2_tog"):
            st.session_state.p2_on = not p2_on
            state["p2_enabled"]    = not p2_on
            st.rerun()

    st.divider()

    # ── Activity log ───────────────────────────────────────────
    st.markdown("**Activity log**")
    logs = state.get("log", ["No activity yet"])
    for line in reversed(logs[-10:]):
        st.caption(line)

    st.divider()
    st.caption(
        f"Stop {STOP_POINTS:.0f}pts  ·  "
        f"Target {TARGET_POINTS:.0f}pts  ·  "
        f"5-Min NY Open ORB  ·  "
        f"Updated {state.get('last_update', '—')}")

    time.sleep(20)
    st.rerun()

main()

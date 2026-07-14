# ============================================================
# dashboard.py — ORB Signal Dashboard
# Run with: streamlit run dashboard.py
# ============================================================

import streamlit as st
import json
import os
from datetime import datetime
import pytz
import time

# Import shared state from main bot
from main import state, STOP_POINTS, TARGET_POINTS, CONTRACTS, SIM_MODE

ET = pytz.timezone("America/New_York")

st.set_page_config(
    page_title="ORB Signal",
    page_icon="📊",
    layout="centered",
)

# ── Dark instrument-panel styling ────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap');

html, body, [class*="css"] {
    background-color: #080c10 !important;
    color: #c9d4e0;
    font-family: 'JetBrains Mono', monospace;
}
.signal-box {
    border-radius: 10px;
    padding: 32px 24px;
    text-align: center;
    margin: 16px 0;
}
.signal-word {
    font-size: 72px;
    font-weight: 800;
    letter-spacing: -1px;
    line-height: 1;
}
.signal-sub {
    font-size: 16px;
    margin-top: 10px;
    opacity: 0.7;
}
.box-long    { background: rgba(46,204,113,.12);
               border: 2px solid #2ecc71; }
.box-short   { background: rgba(255,82,82,.12);
               border: 2px solid #ff5252; }
.box-waiting { background: rgba(255,176,32,.10);
               border: 2px solid #ffb020; }
.box-done    { background: rgba(80,80,80,.12);
               border: 2px solid #444; }
.col-card {
    background: #0e1620;
    border: 1px solid #1a2535;
    border-radius: 8px;
    padding: 14px;
    text-align: center;
}
.col-label { color: #5a7a9a; font-size: 11px;
             letter-spacing: .12em; text-transform: uppercase; }
.col-value { font-size: 26px; font-weight: 700;
             color: #e0eaf5; margin-top: 4px; }
.log-box {
    background: #050810;
    border: 1px solid #1a2535;
    border-radius: 8px;
    padding: 12px;
    font-size: 12px;
    color: #5a8a7a;
    height: 160px;
    overflow-y: auto;
}
</style>
""", unsafe_allow_html=True)

def color(val, good_positive=True):
    if val is None: return "#c9d4e0"
    if val > 0: return "#2ecc71" if good_positive else "#ff5252"
    if val < 0: return "#ff5252" if good_positive else "#2ecc71"
    return "#ffb020"

def main():
    now_et = datetime.now(ET)
    phase  = state.get("phase", "waiting")
    mode   = "SIM" if SIM_MODE else "LIVE"

    # ── Header ───────────────────────────────────────────────
    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown("### 📊 5-Min ORB Signal")
        st.caption(f"{now_et.strftime('%A %B %d, %Y  %H:%M:%S ET')}")
    with c2:
        color_mode = "#ffb020" if SIM_MODE else "#ff5252"
        st.markdown(f"""<div style='text-align:right;
            color:{color_mode};font-weight:700;
            font-size:14px;padding-top:8px'>{mode}</div>""",
            unsafe_allow_html=True)

    st.divider()

    # ── Big signal banner ─────────────────────────────────────
    direction = state.get("direction")
    result    = state.get("result")
    pnl       = state.get("pnl_pts")

    if phase == "waiting":
        st.markdown("""
        <div class='signal-box box-waiting'>
            <div class='signal-word' style='color:#ffb020'>⏳ WAITING</div>
            <div class='signal-sub'>Market opens at 9:30 AM ET</div>
        </div>""", unsafe_allow_html=True)

    elif phase == "building":
        mins = max(0, 35 - now_et.minute) if now_et.hour == 9 else 0
        st.markdown(f"""
        <div class='signal-box box-waiting'>
            <div class='signal-word' style='color:#ffb020'>
            📏 RANGE</div>
            <div class='signal-sub'>
            Building 5-min range — {mins} min to signal</div>
        </div>""", unsafe_allow_html=True)

    elif phase == "watching":
        st.markdown("""
        <div class='signal-box box-waiting'>
            <div class='signal-word' style='color:#ffb020'>
            👀 WATCHING</div>
            <div class='signal-sub'>
            Range set — waiting for breakout...</div>
        </div>""", unsafe_allow_html=True)

    elif phase == "active" and direction == "UP":
        pnl_c = color(pnl)
        st.markdown(f"""
        <div class='signal-box box-long'>
            <div class='signal-word' style='color:#2ecc71'>
            🚀 LONG</div>
            <div class='signal-sub'>
            Active trade — P&L:
            <span style='color:{pnl_c}'>{pnl:+.1f} pts</span>
            </div>
        </div>""", unsafe_allow_html=True)

    elif phase == "active" and direction == "DOWN":
        pnl_c = color(pnl)
        st.markdown(f"""
        <div class='signal-box box-short'>
            <div class='signal-word' style='color:#ff5252'>
            🔻 SHORT</div>
            <div class='signal-sub'>
            Active trade — P&L:
            <span style='color:{pnl_c}'>{pnl:+.1f} pts</span>
            </div>
        </div>""", unsafe_allow_html=True)

    elif phase == "done":
        if result == "WIN":
            st.markdown(f"""
            <div class='signal-box box-long'>
                <div class='signal-word' style='color:#2ecc71'>
                ✅ WIN</div>
                <div class='signal-sub'>
                {direction} trade closed +{pnl:.1f} pts
                (${pnl*5*CONTRACTS:+.0f})</div>
            </div>""", unsafe_allow_html=True)
        elif result == "LOSS":
            st.markdown(f"""
            <div class='signal-box box-short'>
                <div class='signal-word' style='color:#ff5252'>
                ❌ LOSS</div>
                <div class='signal-sub'>
                {direction} trade closed {pnl:.1f} pts
                (${pnl*5*CONTRACTS:+.0f})</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class='signal-box box-done'>
                <div class='signal-word' style='color:#888'>
                ✓ DONE</div>
                <div class='signal-sub'>
                No trade today. See you tomorrow.</div>
            </div>""", unsafe_allow_html=True)

    # ── Range metrics ─────────────────────────────────────────
    high5 = state.get("high5")
    low5  = state.get("low5")
    rng   = state.get("range_size")

    if high5:
        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f"""<div class='col-card'>
                <div class='col-label'>Range HIGH</div>
                <div class='col-value' style='color:#2ecc71'>
                {high5:.2f}</div></div>""",
                unsafe_allow_html=True)
        with c2:
            st.markdown(f"""<div class='col-card'>
                <div class='col-label'>Range LOW</div>
                <div class='col-value' style='color:#ff5252'>
                {low5:.2f}</div></div>""",
                unsafe_allow_html=True)
        with c3:
            st.markdown(f"""<div class='col-card'>
                <div class='col-label'>Range Size</div>
                <div class='col-value'>{rng:.2f}</div>
                </div>""", unsafe_allow_html=True)

    # ── Trade details ─────────────────────────────────────────
    entry = state.get("entry_idx")
    stop  = state.get("stop")
    tgt   = state.get("target")

    if entry and phase in ("active", "done"):
        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"""<div class='col-card'>
                <div class='col-label'>Entry</div>
                <div class='col-value'>{entry:.0f}</div>
                </div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""<div class='col-card'>
                <div class='col-label'>Stop</div>
                <div class='col-value' style='color:#ff5252'>
                {stop:.0f}</div></div>""",
                unsafe_allow_html=True)
        with c3:
            st.markdown(f"""<div class='col-card'>
                <div class='col-label'>Target</div>
                <div class='col-value' style='color:#2ecc71'>
                {tgt:.0f}</div></div>""",
                unsafe_allow_html=True)
        with c4:
            pnl_d = (pnl or 0) * 5 * CONTRACTS
            pnl_c = color(pnl_d)
            st.markdown(f"""<div class='col-card'>
                <div class='col-label'>P&L</div>
                <div class='col-value' style='color:{pnl_c}'>
                ${pnl_d:+.0f}</div></div>""",
                unsafe_allow_html=True)

    # ── Log ───────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("**Activity log**")
    log_html = "<br>".join(reversed(state.get("log", ["No activity yet"])))
    st.markdown(f"<div class='log-box'>{log_html}</div>",
                unsafe_allow_html=True)

    # ── Footer ────────────────────────────────────────────────
    st.divider()
    st.caption(f"Stop: {STOP_POINTS:.0f}pts  |  "
               f"Target: {TARGET_POINTS:.0f}pts  |  "
               f"Contracts: {CONTRACTS}  |  "
               f"Updated: {state.get('last_update','—')}")

    # Auto-refresh every 20 seconds
    time.sleep(20)
    st.rerun()

main()

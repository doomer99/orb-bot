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
    page_title="ORB",
    page_icon="◉",
    layout="centered"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?
family=DM+Mono:wght@300;400;500&
family=DM+Sans:wght@300;400;500;700&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, [class*="css"], .stApp {
    background: #05080d !important;
    color: #a8b8c8;
    font-family: 'DM Sans', sans-serif;
}

/* ── Typography scale ── */
.mono { font-family: 'DM Mono', monospace; }

/* ── Header bar ── */
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 0 20px 0;
    border-bottom: 1px solid #0f1820;
}
.header-left { font-size: 11px; letter-spacing: .2em;
               text-transform: uppercase; color: #3a5060; }
.header-right { font-size: 11px; color: #3a5060;
                font-family: 'DM Mono', monospace; }
.mode-badge {
    display: inline-block;
    font-size: 10px; letter-spacing: .15em;
    padding: 3px 8px; border-radius: 3px;
    font-weight: 500; margin-left: 8px;
}
.mode-sim  { color: #f0a500; border: 1px solid #3a2800; background: #1a1200; }
.mode-live { color: #ff4444; border: 1px solid #3a0000; background: #1a0000; }

/* ── Signal ring — the signature element ── */
.signal-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 32px 0 28px;
}
.ring {
    width: 180px; height: 180px;
    border-radius: 50%;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    border: 2px solid #0f1820;
    position: relative;
    margin-bottom: 16px;
}
.ring::before {
    content: '';
    position: absolute;
    inset: -6px;
    border-radius: 50%;
    border: 1.5px solid transparent;
}
.ring-long  { border-color: #1a3a28;
              background: radial-gradient(circle, #0a1f14 0%, #05080d 70%); }
.ring-long::before  { border-color: #2ecc71;
                       box-shadow: 0 0 20px rgba(46,204,113,.25),
                                   0 0 60px rgba(46,204,113,.08);
                       animation: pulse-green 2s ease-in-out infinite; }
.ring-short { border-color: #3a1a1a;
              background: radial-gradient(circle, #1f0a0a 0%, #05080d 70%); }
.ring-short::before { border-color: #ff5252;
                       box-shadow: 0 0 20px rgba(255,82,82,.25),
                                   0 0 60px rgba(255,82,82,.08);
                       animation: pulse-red 2s ease-in-out infinite; }
.ring-watch { border-color: #2a2010;
              background: radial-gradient(circle, #15110a 0%, #05080d 70%); }
.ring-watch::before { border-color: #f0a500;
                       box-shadow: 0 0 20px rgba(240,165,0,.2);
                       animation: pulse-amber 3s ease-in-out infinite; }
.ring-idle  { border-color: #0f1820;
              background: #05080d; }

@keyframes pulse-green {
    0%,100% { box-shadow: 0 0 20px rgba(46,204,113,.25),
                           0 0 60px rgba(46,204,113,.08); }
    50%      { box-shadow: 0 0 30px rgba(46,204,113,.4),
                           0 0 80px rgba(46,204,113,.15); }
}
@keyframes pulse-red {
    0%,100% { box-shadow: 0 0 20px rgba(255,82,82,.25),
                           0 0 60px rgba(255,82,82,.08); }
    50%      { box-shadow: 0 0 30px rgba(255,82,82,.4),
                           0 0 80px rgba(255,82,82,.15); }
}
@keyframes pulse-amber {
    0%,100% { box-shadow: 0 0 15px rgba(240,165,0,.2); }
    50%      { box-shadow: 0 0 25px rgba(240,165,0,.35); }
}

.ring-label {
    font-size: 28px; font-weight: 700; line-height: 1;
    letter-spacing: -.5px;
}
.ring-sub {
    font-size: 10px; letter-spacing: .15em;
    text-transform: uppercase; margin-top: 6px;
    font-family: 'DM Mono', monospace;
}
.ring-pnl {
    font-size: 13px; margin-top: 4px;
    font-family: 'DM Mono', monospace;
}

/* ── Data row ── */
.data-row {
    display: flex; gap: 8px; margin: 0 0 8px;
}
.data-cell {
    flex: 1;
    background: #080d12;
    border: 1px solid #0f1820;
    border-radius: 6px;
    padding: 12px 10px;
    text-align: center;
}
.data-label {
    font-size: 9px; letter-spacing: .18em;
    text-transform: uppercase; color: #2a4050;
    font-family: 'DM Mono', monospace;
    margin-bottom: 5px;
}
.data-value {
    font-size: 18px; font-weight: 500;
    font-family: 'DM Mono', monospace;
    color: #c0d0dc;
}
.data-value.green { color: #2ecc71; }
.data-value.red   { color: #ff5252; }
.data-value.amber { color: #f0a500; }
.data-value.dim   { color: #2a4050; font-size:14px; }

/* ── Section ── */
.section {
    background: #080d12;
    border: 1px solid #0f1820;
    border-radius: 8px;
    padding: 16px;
    margin: 8px 0;
}
.section-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 14px;
}
.section-title {
    font-size: 10px; letter-spacing: .2em;
    text-transform: uppercase; color: #3a5060;
    font-family: 'DM Mono', monospace;
}
.section-status-on  { font-size: 10px; color: #2ecc71;
                       letter-spacing: .1em; }
.section-status-off { font-size: 10px; color: #2a4050;
                       letter-spacing: .1em; }

/* ── Divider ── */
.div { border: none; border-top: 1px solid #0a1018; margin: 16px 0; }

/* ── Log ── */
.log-wrap {
    background: #030508;
    border: 1px solid #0a1018;
    border-radius: 6px;
    padding: 10px 12px;
    height: 120px;
    overflow-y: auto;
}
.log-line {
    font-size: 11px;
    font-family: 'DM Mono', monospace;
    color: #2a4a3a;
    line-height: 1.7;
}
.log-line.recent { color: #3a6a50; }

/* ── Warning ── */
.warn { font-size: 11px; color: #f0a500;
        font-family: 'DM Mono', monospace;
        padding: 6px 0; }

/* Hide Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 24px 16px 40px !important;
                   max-width: 480px !important; }

/* Streamlit widget overrides */
.stSlider label, .stNumberInput label,
.stToggle label { color: #3a5060 !important;
                   font-size: 11px !important;
                   letter-spacing: .1em !important;
                   text-transform: uppercase !important; }
.stButton button {
    background: #080d12 !important;
    border: 1px solid #0f1820 !important;
    color: #a8b8c8 !important;
    font-size: 11px !important;
    letter-spacing: .1em !important;
    border-radius: 4px !important;
    padding: 6px 14px !important;
    font-family: 'DM Mono', monospace !important;
}
.stButton button:hover {
    border-color: #2ecc71 !important;
    color: #2ecc71 !important;
}
</style>
""", unsafe_allow_html=True)

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

def fmt_pnl(v):
    return f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"

def main():
    now       = datetime.now(ET)
    phase     = state.get("phase", "waiting")
    direction = state.get("direction")
    result    = state.get("result")
    pnl_pts   = state.get("pnl_pts") or 0.0
    pnl_d     = pnl_pts * 5.0 * st.session_state.p1_qty

    # ── Header ────────────────────────────────────────────────
    mode_cls = "mode-sim" if SIM_MODE else "mode-live"
    mode_lbl = "SIM" if SIM_MODE else "LIVE"
    st.markdown(f"""
    <div class="header">
      <div class="header-left">◉ ORB Signal</div>
      <div class="header-right">
        {now.strftime("%a %b %d · %H:%M:%S ET")}
        <span class="mode-badge {mode_cls}">{mode_lbl}</span>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── Signal ring ───────────────────────────────────────────
    if phase in ("waiting", "building"):
        ring_cls   = "ring-idle"
        ring_lbl   = "—"
        ring_sub   = "OPENS 9:30 ET" if phase=="waiting" \
                     else f"RANGE · {max(0,35-now.minute)}M"
        ring_color = "#2a4050"
        ring_pnl   = ""
    elif phase == "watching":
        ring_cls   = "ring-watch"
        ring_lbl   = "·"
        ring_sub   = "WATCHING"
        ring_color = "#f0a500"
        ring_pnl   = ""
    elif phase == "active":
        ring_cls   = "ring-long" if direction=="UP" else "ring-short"
        ring_lbl   = "▲" if direction=="UP" else "▼"
        ring_sub   = "LONG" if direction=="UP" else "SHORT"
        ring_color = "#2ecc71" if direction=="UP" else "#ff5252"
        pc         = "#2ecc71" if pnl_pts>=0 else "#ff5252"
        ring_pnl   = (f"<div class='ring-pnl' style='color:{pc}'>"
                      f"{pnl_pts:+.1f}pts · {fmt_pnl(pnl_d)}</div>")
    elif phase == "done":
        if result == "WIN":
            ring_cls   = "ring-long"
            ring_lbl   = "✓"
            ring_sub   = "WIN"
            ring_color = "#2ecc71"
            ring_pnl   = (f"<div class='ring-pnl' style='color:#2ecc71'>"
                          f"+{pnl_pts:.1f}pts · {fmt_pnl(pnl_d)}</div>")
        elif result == "LOSS":
            ring_cls   = "ring-short"
            ring_lbl   = "✗"
            ring_sub   = "LOSS"
            ring_color = "#ff5252"
            ring_pnl   = (f"<div class='ring-pnl' style='color:#ff5252'>"
                          f"{pnl_pts:.1f}pts · {fmt_pnl(pnl_d)}</div>")
        else:
            ring_cls   = "ring-idle"
            ring_lbl   = "—"
            ring_sub   = "DONE"
            ring_color = "#2a4050"
            ring_pnl   = ""
    else:
        ring_cls   = "ring-idle"
        ring_lbl   = "—"
        ring_sub   = "WAITING"
        ring_color = "#2a4050"
        ring_pnl   = ""

    st.markdown(f"""
    <div class="signal-wrap">
      <div class="ring {ring_cls}">
        <div class="ring-label" style="color:{ring_color}">
            {ring_lbl}</div>
        <div class="ring-sub" style="color:{ring_color}">
            {ring_sub}</div>
        {ring_pnl}
      </div>
    </div>""", unsafe_allow_html=True)

    # ── Range metrics ─────────────────────────────────────────
    high5 = state.get("high5")
    low5  = state.get("low5")
    rng   = state.get("range_size", 0)

    h_val = f"{high5:.2f}" if high5 else "—"
    l_val = f"{low5:.2f}"  if low5  else "—"
    r_val = f"{rng:.2f}"   if high5 else "—"
    h_cls = "green" if high5 else "dim"
    l_cls = "red"   if low5  else "dim"

    entry  = state.get("entry_idx")
    stop   = state.get("stop",   0)
    target = state.get("target", 0)

    if entry and phase in ("active", "done"):
        st.markdown(f"""
        <div class="data-row">
          <div class="data-cell">
            <div class="data-label">Entry</div>
            <div class="data-value">{entry:.0f}</div>
          </div>
          <div class="data-cell">
            <div class="data-label">Stop</div>
            <div class="data-value red">{stop:.0f}</div>
          </div>
          <div class="data-cell">
            <div class="data-label">Target</div>
            <div class="data-value green">{target:.0f}</div>
          </div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="data-row">
          <div class="data-cell">
            <div class="data-label">Range High</div>
            <div class="data-value {h_cls}">{h_val}</div>
          </div>
          <div class="data-cell">
            <div class="data-label">Range Low</div>
            <div class="data-value {l_cls}">{l_val}</div>
          </div>
          <div class="data-cell">
            <div class="data-label">Range Size</div>
            <div class="data-value">{r_val}</div>
          </div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div class='div'></div>", unsafe_allow_html=True)

    # ════════════════════════════════════════════════
    # TOPSTEP — MES FUTURES
    # ════════════════════════════════════════════════
    p1_on     = st.session_state.p1_on
    p1_status = state.get("p1_status", "—")
    p1_sc     = "section-status-on" if p1_on \
                else "section-status-off"
    p1_dot    = "● ON" if p1_on else "○ OFF"

    st.markdown(f"""
    <div class="section">
      <div class="section-head">
        <div class="section-title">Topstep · MES Futures</div>
        <div class="{p1_sc}">{p1_dot} · {p1_status}</div>
      </div>""", unsafe_allow_html=True)

    c1, c2 = st.columns([2, 1])
    with c1:
        p1_bal = st.number_input(
            "Account size",
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

    rec   = rec_contracts(p1_str)
    p1_qty = st.slider("Contracts", 1, 12,
                       st.session_state.p1_qty,
                       key="p1_sl")
    st.session_state.p1_qty = p1_qty
    state["p1_qty"]         = p1_qty

    max_loss  = p1_qty * 8 * 5
    dd_pct    = max_loss / 2000 * 100
    dd_color  = ("green" if dd_pct < 50
                 else "amber" if dd_pct < 80
                 else "red")

    st.markdown(f"""
      <div class="data-row" style="margin-top:10px">
        <div class="data-cell">
          <div class="data-label">Recommended</div>
          <div class="data-value green">{rec}c</div>
        </div>
        <div class="data-cell">
          <div class="data-label">Max loss</div>
          <div class="data-value red">${max_loss:,.0f}</div>
        </div>
        <div class="data-cell">
          <div class="data-label">DD used</div>
          <div class="data-value {dd_color}">
              {dd_pct:.0f}%</div>
        </div>
      </div>""", unsafe_allow_html=True)

    bc1, bc2 = st.columns(2)
    with bc1:
        if st.button("Use recommended", key="p1_rec"):
            st.session_state.p1_qty = rec
            state["p1_qty"]         = rec
            st.rerun()
    with bc2:
        if st.button("Turn OFF" if p1_on else "Turn ON",
                     key="p1_tog"):
            st.session_state.p1_on = not p1_on
            state["p1_enabled"]    = not p1_on
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    # ════════════════════════════════════════════════
    # TRADIER — 0DTE OPTIONS
    # ════════════════════════════════════════════════
    p2_on     = st.session_state.p2_on
    p2_status = state.get("p2_status", "—")
    p2_sc     = "section-status-on" if p2_on \
                else "section-status-off"
    p2_dot    = "● ON" if p2_on else "○ OFF"

    equity  = state.get("equity",  0.0)
    cash    = state.get("cash",    0.0)
    bal_pnl = state.get("day_pnl", 0.0)
    sand    = os.environ.get("TRADIER_SANDBOX",
                             "true").lower() == "true"
    acct    = "SANDBOX" if sand else "LIVE"
    eq_c    = "green" if equity > 0 else "dim"
    pp_c    = "green" if bal_pnl >= 0 else "red"

    st.markdown(f"""
    <div class="section" style="margin-top:8px">
      <div class="section-head">
        <div class="section-title">
            Tradier · 0DTE Options ({acct})</div>
        <div class="{p2_sc}">{p2_dot} · {p2_status}</div>
      </div>
      <div class="data-row">
        <div class="data-cell">
          <div class="data-label">Equity</div>
          <div class="data-value {eq_c}">
              ${equity:,.0f}</div>
        </div>
        <div class="data-cell">
          <div class="data-label">Cash</div>
          <div class="data-value">${cash:,.0f}</div>
        </div>
        <div class="data-cell">
          <div class="data-label">Day P&L</div>
          <div class="data-value {pp_c}">
              {fmt_pnl(bal_pnl)}</div>
        </div>
      </div>""", unsafe_allow_html=True)

    if equity == 0:
        st.markdown(
            "<div class='warn'>⚠ Balance $0 — "
            "check TRADIER_TOKEN in Railway</div>",
            unsafe_allow_html=True)

    p2_qty = st.slider("Option contracts", 1, 20,
                       st.session_state.p2_qty,
                       key="p2_sl")
    st.session_state.p2_qty = p2_qty
    state["p2_qty"]         = p2_qty

    est_risk  = p2_qty * 1.50 * 100
    risk_pct  = (est_risk / equity * 100) if equity > 0 else 0
    rsk_c     = ("green" if risk_pct < 5
                 else "amber" if risk_pct < 15
                 else "red")

    st.markdown(f"""
      <div class="data-row" style="margin-top:10px">
        <div class="data-cell">
          <div class="data-label">Est. risk</div>
          <div class="data-value red">
              ${est_risk:,.0f}</div>
        </div>
        <div class="data-cell">
          <div class="data-label">% of account</div>
          <div class="data-value {rsk_c}">
              {risk_pct:.1f}%</div>
        </div>
        <div class="data-cell">
          <div class="data-label">Type</div>
          <div class="data-value">
              {'CALL' if (direction=='UP' or not direction)
               else 'PUT'}</div>
        </div>
      </div>""", unsafe_allow_html=True)

    if st.button("Turn OFF" if p2_on else "Turn ON",
                 key="p2_tog"):
        st.session_state.p2_on = not p2_on
        state["p2_enabled"]    = not p2_on
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='div'></div>", unsafe_allow_html=True)

    # ── Activity log ───────────────────────────────────────────
    st.markdown(
        "<div class='section-title' "
        "style='margin-bottom:8px'>Activity</div>",
        unsafe_allow_html=True)
    logs = state.get("log", ["—"])[-15:]
    lines = "".join(
        f"<div class='log-line"
        f"{' recent' if i >= len(logs)-3 else ''}'>"
        f"{l}</div>"
        for i, l in enumerate(reversed(logs))
    )
    st.markdown(
        f"<div class='log-wrap'>{lines}</div>",
        unsafe_allow_html=True)

    # ── Footer ─────────────────────────────────────────────────
    st.markdown(f"""
    <div style='text-align:center;padding:20px 0 0;
    font-size:10px;color:#1a2a38;
    font-family:"DM Mono",monospace;
    letter-spacing:.15em'>
    STOP {STOP_POINTS:.0f}PT · TARGET {TARGET_POINTS:.0f}PT ·
    {state.get('last_update','—')}
    </div>""", unsafe_allow_html=True)

    time.sleep(20)
    st.rerun()

main()

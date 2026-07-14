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
    layout="centered"
)

st.markdown("""
<style>
html,body,[class*="css"]{
    background:#080c10!important;
    color:#c9d4e0;
    font-family:monospace
}
.sbox{border-radius:10px;padding:28px 20px;
      text-align:center;margin:12px 0}
.sword{font-size:64px;font-weight:800;line-height:1}
.ssub{font-size:15px;margin-top:8px;opacity:.7}
.bl{background:rgba(46,204,113,.12);border:2px solid #2ecc71}
.bs{background:rgba(255,82,82,.12);border:2px solid #ff5252}
.bw{background:rgba(255,176,32,.10);border:2px solid #ffb020}
.bd{background:rgba(80,80,80,.12);border:2px solid #444}
.card{background:#0e1620;border:1px solid #1a2535;
      border-radius:8px;padding:14px;text-align:center;margin:4px 0}
.cl{color:#5a7a9a;font-size:10px;
    letter-spacing:.12em;text-transform:uppercase}
.cv{font-size:22px;font-weight:700;color:#e0eaf5;margin-top:4px}
.section{background:#0a1018;border:1px solid #1a2535;
         border-radius:10px;padding:16px;margin:10px 0}
.section-title{font-size:13px;font-weight:700;
               letter-spacing:.1em;margin-bottom:12px}
.pon{background:rgba(46,204,113,.08);
     border:1px solid #2ecc71;
     border-radius:6px;padding:8px 12px;
     display:inline-block;color:#2ecc71;
     font-size:12px;margin-right:8px}
.poff{background:rgba(80,80,80,.08);
      border:1px solid #333;
      border-radius:6px;padding:8px 12px;
      display:inline-block;color:#666;
      font-size:12px;margin-right:8px}
.log{background:#050810;border:1px solid #1a2535;
     border-radius:8px;padding:10px;font-size:11px;
     color:#4a7a6a;height:130px;overflow-y:auto}
.warn{color:#ffb020;font-size:12px;margin-top:4px}
.good{color:#2ecc71;font-size:12px;margin-top:4px}
</style>""", unsafe_allow_html=True)

# Session state defaults
for k,v in [
    ("p1_on", P1_ENABLED),
    ("p2_on", P2_ENABLED),
    ("p1_qty", P1_QTY),
    ("p2_qty", P2_QTY),
    ("p1_balance", 50000),
    ("p1_streak", 0),
    ("p1_auto", True),
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
    pnl       = state.get("pnl_pts") or 0.0
    pnl_d     = pnl * 5.0 * st.session_state.p1_qty

    # ── Header ────────────────────────────────────────────────
    c1, c2 = st.columns([4, 1])
    with c1:
        st.markdown("### 📊 5-Min ORB")
        st.caption(now.strftime("%A  %b %d  %H:%M:%S ET"))
    with c2:
        clr = "#ffb020" if SIM_MODE else "#ff5252"
        st.markdown(
            f"<div style='text-align:right;color:{clr};"
            f"font-weight:700;padding-top:10px'>"
            f"{'SIM' if SIM_MODE else 'LIVE'}</div>",
            unsafe_allow_html=True)

    st.divider()

    # ── Signal banner ──────────────────────────────────────────
    if phase == "waiting":
        st.markdown(
            "<div class='sbox bw'>"
            "<div class='sword' style='color:#ffb020'>⏳ WAITING</div>"
            "<div class='ssub'>Opens 9:30 AM ET</div></div>",
            unsafe_allow_html=True)
    elif phase == "building":
        mins = max(0, 35 - now.minute) if now.hour == 9 else 0
        st.markdown(
            f"<div class='sbox bw'>"
            f"<div class='sword' style='color:#ffb020'>📏 RANGE</div>"
            f"<div class='ssub'>Building — {mins} min to signal"
            f"</div></div>",
            unsafe_allow_html=True)
    elif phase == "watching":
        st.markdown(
            "<div class='sbox bw'>"
            "<div class='sword' style='color:#ffb020'>👀 WATCH</div>"
            "<div class='ssub'>Waiting for breakout...</div></div>",
            unsafe_allow_html=True)
    elif phase == "active":
        pc = "#2ecc71" if pnl >= 0 else "#ff5252"
        if direction == "UP":
            st.markdown(
                f"<div class='sbox bl'>"
                f"<div class='sword' style='color:#2ecc71'>"
                f"🚀 LONG</div>"
                f"<div class='ssub'>Active — "
                f"<span style='color:{pc}'>"
                f"{pnl:+.1f}pts (${pnl_d:+.0f})</span>"
                f"</div></div>",
                unsafe_allow_html=True)
        else:
            st.markdown(
                f"<div class='sbox bs'>"
                f"<div class='sword' style='color:#ff5252'>"
                f"🔻 SHORT</div>"
                f"<div class='ssub'>Active — "
                f"<span style='color:{pc}'>"
                f"{pnl:+.1f}pts (${pnl_d:+.0f})</span>"
                f"</div></div>",
                unsafe_allow_html=True)
    elif phase == "done":
        if result == "WIN":
            st.markdown(
                f"<div class='sbox bl'>"
                f"<div class='sword' style='color:#2ecc71'>"
                f"✅ WIN</div>"
                f"<div class='ssub'>{direction} "
                f"+{pnl:.1f}pts (${pnl_d:+.0f})</div></div>",
                unsafe_allow_html=True)
        elif result == "LOSS":
            st.markdown(
                f"<div class='sbox bs'>"
                f"<div class='sword' style='color:#ff5252'>"
                f"❌ LOSS</div>"
                f"<div class='ssub'>{direction} "
                f"{pnl:.1f}pts (${pnl_d:+.0f})</div></div>",
                unsafe_allow_html=True)
        else:
            st.markdown(
                "<div class='sbox bd'>"
                "<div class='sword' style='color:#888'>"
                "✓ DONE</div>"
                "<div class='ssub'>No trade today</div></div>",
                unsafe_allow_html=True)

    # ── Range and trade metrics ────────────────────────────────
    high5 = state.get("high5")
    low5  = state.get("low5")
    if high5:
        c1, c2, c3 = st.columns(3)
        for col, (lbl, val, clr) in zip(
            [c1, c2, c3],
            [("HIGH",  f"{high5:.2f}", "#2ecc71"),
             ("LOW",   f"{low5:.2f}",  "#ff5252"),
             ("RANGE", f"{state.get('range_size',0):.2f}", "#e0eaf5")]
        ):
            with col:
                st.markdown(
                    f"<div class='card'>"
                    f"<div class='cl'>{lbl}</div>"
                    f"<div class='cv' style='color:{clr}'>"
                    f"{val}</div></div>",
                    unsafe_allow_html=True)

    entry = state.get("entry_idx")
    if entry and phase in ("active", "done"):
        c1, c2, c3 = st.columns(3)
        for col, (lbl, val, clr) in zip(
            [c1, c2, c3],
            [("ENTRY",  f"{entry:.0f}",                "#e0eaf5"),
             ("STOP",   f"{state.get('stop',0):.0f}",  "#ff5252"),
             ("TARGET", f"{state.get('target',0):.0f}", "#2ecc71")]
        ):
            with col:
                st.markdown(
                    f"<div class='card'>"
                    f"<div class='cl'>{lbl}</div>"
                    f"<div class='cv' style='color:{clr}'>"
                    f"{val}</div></div>",
                    unsafe_allow_html=True)

    st.divider()

    # ════════════════════════════════════════════════════════
    # PIPELINE 1 — TOPSTEP (MES FUTURES)
    # ════════════════════════════════════════════════════════
    p1_on = st.session_state.p1_on
    p1_icon = "🟢" if p1_on else "⚫"
    p1_status = state.get("p1_status", "—")

    st.markdown(
        f"<div class='section'>"
        f"<div class='section-title' style='color:#2ecc71'>"
        f"{p1_icon} PIPELINE 1 — TOPSTEP (MES Futures)</div>",
        unsafe_allow_html=True)

    col1, col2 = st.columns([3, 1])
    with col1:
        badge = "pon" if p1_on else "poff"
        lbl   = "ACTIVE" if p1_on else "INACTIVE"
        st.markdown(
            f"<span class='{badge}'>{lbl}</span>"
            f"<span style='color:#5a7a9a;font-size:12px'>"
            f"Status: {p1_status}</span>",
            unsafe_allow_html=True)
    with col2:
        if st.button("Turn OFF" if p1_on else "Turn ON",
                     key="p1_toggle"):
            st.session_state.p1_on = not p1_on
            state["p1_enabled"]    = not p1_on
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # Topstep account info (manual entry until TradersPost API)
    tc1, tc2 = st.columns(2)
    with tc1:
        p1_bal = st.number_input(
            "Topstep account size ($)",
            min_value=0, max_value=500000,
            value=st.session_state.p1_balance,
            step=1000, key="p1_bal_input")
        st.session_state.p1_balance = p1_bal
    with tc2:
        p1_streak = st.number_input(
            "Current win streak",
            min_value=0, max_value=100,
            value=st.session_state.p1_streak,
            step=1, key="p1_streak_input")
        st.session_state.p1_streak = p1_streak

    # Contract recommendation
    rec = rec_contracts(p1_streak)
    dd_limit    = 2000.0
    max_loss    = st.session_state.p1_qty * 8 * 5
    dd_used_pct = (max_loss / dd_limit * 100)
    dd_color    = "#2ecc71" if dd_used_pct < 50 else "#ffb020" \
                  if dd_used_pct < 80 else "#ff5252"

    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        st.markdown(
            f"<div class='card'>"
            f"<div class='cl'>RECOMMENDED</div>"
            f"<div class='cv' style='color:#2ecc71;font-size:36px'>"
            f"{rec}</div>"
            f"<div style='color:#5a7a9a;font-size:10px'>"
            f"contracts</div></div>",
            unsafe_allow_html=True)
    with sc2:
        st.markdown(
            f"<div class='card'>"
            f"<div class='cl'>MAX LOSS</div>"
            f"<div class='cv' style='color:#ff5252'>"
            f"${max_loss:,.0f}</div>"
            f"<div style='color:#5a7a9a;font-size:10px'>"
            f"{st.session_state.p1_qty}c × 8pts × $5</div></div>",
            unsafe_allow_html=True)
    with sc3:
        st.markdown(
            f"<div class='card'>"
            f"<div class='cl'>DD LIMIT USED</div>"
            f"<div class='cv' style='color:{dd_color}'>"
            f"{dd_used_pct:.0f}%</div>"
            f"<div style='color:#5a7a9a;font-size:10px'>"
            f"of $2,000 limit</div></div>",
            unsafe_allow_html=True)

    # Contract slider
    p1_qty = st.slider(
        "Contracts to trade",
        min_value=1, max_value=12,
        value=st.session_state.p1_qty,
        key="p1_qty_slider")
    st.session_state.p1_qty = p1_qty
    state["p1_qty"]         = p1_qty

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ Use recommended", key="p1_use_rec"):
            st.session_state.p1_qty = rec
            state["p1_qty"]         = rec
            st.rerun()
    with c2:
        st.caption(f"Recommended: {rec} contracts "
                   f"(after {p1_streak} win streak)")

    st.markdown("</div>", unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════
    # PIPELINE 2 — TRADEYOUR / TRADIER (0DTE OPTIONS)
    # ════════════════════════════════════════════════════════
    p2_on     = st.session_state.p2_on
    p2_icon   = "🟢" if p2_on else "⚫"
    p2_status = state.get("p2_status", "—")

    # Live Tradier balance
    equity  = state.get("equity",  0.0)
    cash    = state.get("cash",    0.0)
    bal_pnl = state.get("day_pnl", 0.0)
    pnl_c   = "#2ecc71" if bal_pnl >= 0 else "#ff5252"
    sand    = os.environ.get("TRADIER_SANDBOX","true").lower()=="true"
    acct_lbl = "SANDBOX" if sand else "LIVE"

    st.markdown(
        f"<div class='section'>"
        f"<div class='section-title' style='color:#ff9f43'>"
        f"{p2_icon} PIPELINE 2 — TRADIER OPTIONS (0DTE SPY)</div>",
        unsafe_allow_html=True)

    col1, col2 = st.columns([3, 1])
    with col1:
        badge = "pon" if p2_on else "poff"
        lbl   = "ACTIVE" if p2_on else "INACTIVE"
        st.markdown(
            f"<span class='{badge}'>{lbl}</span>"
            f"<span style='color:#5a7a9a;font-size:12px'>"
            f"Status: {p2_status}</span>",
            unsafe_allow_html=True)
    with col2:
        if st.button("Turn OFF" if p2_on else "Turn ON",
                     key="p2_toggle"):
            st.session_state.p2_on = not p2_on
            state["p2_enabled"]    = not p2_on
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # Live Tradier balance display
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        eq_color = "#2ecc71" if equity > 0 else "#ff5252"
        st.markdown(
            f"<div class='card'>"
            f"<div class='cl'>EQUITY ({acct_lbl})</div>"
            f"<div class='cv' style='color:{eq_color}'>"
            f"${equity:,.0f}</div></div>",
            unsafe_allow_html=True)
    with bc2:
        st.markdown(
            f"<div class='card'>"
            f"<div class='cl'>CASH AVAILABLE</div>"
            f"<div class='cv'>${cash:,.0f}</div></div>",
            unsafe_allow_html=True)
    with bc3:
        st.markdown(
            f"<div class='card'>"
            f"<div class='cl'>DAY P&L</div>"
            f"<div class='cv' style='color:{pnl_c}'>"
            f"${bal_pnl:+,.0f}</div></div>",
            unsafe_allow_html=True)

    if equity == 0:
        st.markdown(
            "<div class='warn'>⚠️ Balance showing $0 — "
            "check TRADIER_TOKEN in Railway Variables</div>",
            unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Options quantity slider
    p2_qty = st.slider(
        "Option contracts to buy",
        min_value=1, max_value=20,
        value=st.session_state.p2_qty,
        key="p2_qty_slider")
    st.session_state.p2_qty = p2_qty
    state["p2_qty"]         = p2_qty

    # Risk estimate for options
    est_premium = 1.50  # estimated $ per option contract
    est_risk    = p2_qty * est_premium * 100
    risk_pct    = (est_risk / equity * 100) if equity > 0 else 0
    risk_color  = ("#2ecc71" if risk_pct < 5
                   else "#ffb020" if risk_pct < 15
                   else "#ff5252")

    oc1, oc2 = st.columns(2)
    with oc1:
        st.markdown(
            f"<div class='card'>"
            f"<div class='cl'>EST. MAX RISK</div>"
            f"<div class='cv' style='color:#ff5252'>"
            f"${est_risk:,.0f}</div>"
            f"<div style='color:#5a7a9a;font-size:10px'>"
            f"{p2_qty} contracts × ~$1.50 premium</div></div>",
            unsafe_allow_html=True)
    with oc2:
        st.markdown(
            f"<div class='card'>"
            f"<div class='cl'>% OF ACCOUNT</div>"
            f"<div class='cv' style='color:{risk_color}'>"
            f"{risk_pct:.1f}%</div>"
            f"<div style='color:#5a7a9a;font-size:10px'>"
            f"of ${equity:,.0f} equity</div></div>",
            unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # ── Activity log ───────────────────────────────────────────
    st.markdown("**Activity**")
    logs     = state.get("log", ["No activity yet"])
    log_html = "<br>".join(reversed(logs[-15:]))
    st.markdown(
        f"<div class='log'>{log_html}</div>",
        unsafe_allow_html=True)

    st.divider()
    st.caption(
        f"Stop {STOP_POINTS:.0f}pts · "
        f"Target {TARGET_POINTS:.0f}pts · "
        f"Updated {state.get('last_update', '—')}")

    time.sleep(20)
    st.rerun()

main()
main()

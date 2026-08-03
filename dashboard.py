# dashboard.py — Bloomberg Terminal Style Dashboard
import streamlit as st
import json, os, time
from datetime import datetime
import pytz

ET = pytz.timezone("America/New_York")
from main import router
from portfolio import Portfolio, DirectAllocation, save_portfolios, load_portfolios, get_asset_data

st.set_page_config(page_title="Command Center", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');
    .block-container {padding-top: 0.5rem; padding-bottom: 0.5rem; max-width: 100%;}
    * {font-family: 'JetBrains Mono', monospace !important;}
    #MainMenu, footer, .stDeployButton, header {display: none !important;}
    div[data-testid="stSidebar"] {min-width: 220px; max-width: 220px;}
    div[data-testid="stSidebar"] > div:first-child {padding-top: 0.5rem;}
    .top-bar {display: flex; align-items: center; justify-content: space-between; padding: 6px 12px; background: var(--surface-1); border-bottom: 1px solid var(--border); margin: -0.5rem -1rem 2px -1rem;}
    .metric-grid {display: grid; grid-template-columns: repeat(6, 1fr); margin-bottom: 12px;}
    .m-cell {padding: 8px 12px; background: var(--surface-1); border-right: 1px solid var(--border); border-bottom: 1px solid var(--border);}
    .m-cell:last-child {border-right: none;}
    .m-lbl {font-size: 10px; color: var(--text-muted); letter-spacing: 0.5px;}
    .m-val {font-size: 16px; font-weight: 500; color: var(--text-primary);}
    .m-grn {color: var(--text-success) !important;}
    .m-red {color: var(--text-danger) !important;}
    .sec-hdr {padding: 6px 10px; background: var(--surface-1); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center;}
    .sec-ttl {font-size: 11px; font-weight: 500; color: var(--text-primary); letter-spacing: 0.5px;}
    .sec-sum {font-size: 10px; color: var(--text-success);}
    .dt {width: 100%; border-collapse: collapse; font-size: 11px; background: var(--surface-1);}
    .dt th {text-align: left; padding: 3px 10px; color: var(--text-muted); font-weight: 500; border-bottom: 1px solid var(--border);}
    .dt td {padding: 5px 10px; color: var(--text-secondary); border-bottom: 1px solid var(--border);}
    .dt .r {text-align: right;}
    .dt .grn {color: var(--text-success);}
    .dt .red {color: var(--text-danger);}
    .dt .mut {color: var(--text-muted);}
    .dt .bld {font-weight: 500;}
    .bk {padding: 6px 10px; border-bottom: 1px solid var(--border); font-size: 11px;}
    .bk-on {border-left: 3px solid var(--text-success);}
    .bk-off {border-left: 3px solid transparent;}
    .bk-nm {font-weight: 500; color: var(--text-primary);}
    .bk-mt {font-size: 10px; color: var(--text-muted); margin-top: 2px;}
    .tg {font-size: 9px; padding: 1px 5px; border-radius: 3px; display: inline-block; margin-right: 3px; margin-top: 3px;}
    .tg-a {background: var(--bg-accent); color: var(--text-accent);}
    .tg-d {background: var(--surface-0); color: var(--text-secondary);}
    .tg-m {background: var(--surface-0); color: var(--text-muted);}
    .log-l {font-size: 11px; line-height: 1.7; color: var(--text-muted);}
    .log-ok {color: var(--text-success);}
    .log-sg {color: var(--text-warning);}
    .log-er {color: var(--text-danger);}
</style>
""", unsafe_allow_html=True)

state = router.get_state()
now = datetime.now(ET)
total_equity = sum(b.get("equity", 0) for b in state["brokers"].values() if b.get("connected"))
total_day_pnl = sum(b.get("day_pnl", 0) for b in state["brokers"].values() if b.get("connected"))
open_count = sum(1 for t in state["active_trades"].values() if t["status"] in ("OPEN", "SIM"))

# ── Top bar ──
col_h, col_cb = st.columns([8, 1])
with col_h:
    mode = "LIVE" if not state["sim_mode"] else "SIM"
    mode_c = "var(--text-success)" if mode == "LIVE" else "var(--text-warning)"
    st.markdown(f"""<div class="top-bar">
        <div style="display:flex;align-items:center;gap:16px;">
            <span style="font-size:13px;font-weight:700;color:var(--text-primary);letter-spacing:1px;">BROADBENT CAPITAL</span>
            <span style="color:var(--text-muted);">|</span>
            <span style="font-size:11px;color:{mode_c};">{mode}</span>
            <span style="color:var(--text-muted);">|</span>
            <span style="font-size:11px;color:var(--text-muted);">{now.strftime('%m.%d.%Y %H:%M:%S ET')}</span>
        </div></div>""", unsafe_allow_html=True)
with col_cb:
    if state.get("circuit_breaker"):
        if st.button("RESUME", key="cb_r"):
            router.deactivate_circuit_breaker()
            st.rerun()
    else:
        if st.button("HALT", key="cb_a"):
            router.activate_circuit_breaker()
            st.rerun()

if state.get("circuit_breaker"):
    st.error(f"CIRCUIT BREAKER ACTIVE — all trading halted since {state.get('circuit_breaker_time','?')}")

# ── Metrics ──
pnl_c = "m-grn" if total_day_pnl >= 0 else "m-red"
st.markdown(f"""<div class="metric-grid">
    <div class="m-cell"><div class="m-lbl">NAV</div><div class="m-val">${total_equity:,.0f}</div></div>
    <div class="m-cell"><div class="m-lbl">DAY P&L</div><div class="m-val {pnl_c}">${total_day_pnl:+,.2f}</div></div>
    <div class="m-cell"><div class="m-lbl">OPEN POS</div><div class="m-val">{open_count}</div></div>
    <div class="m-cell"><div class="m-lbl">STRATEGIES</div><div class="m-val">{sum(1 for s in state['strategies'].values() if s.get('enabled'))}</div></div>
    <div class="m-cell"><div class="m-lbl">BOOKS</div><div class="m-val">{len(router.portfolios) + len(router.allocations)}</div></div>
    <div class="m-cell"><div class="m-lbl">SIGNALS TODAY</div><div class="m-val">{sum(1 for l in state.get('log',[]) if 'signal' in l.lower())}</div></div>
</div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;"><span style="font-size:11px;font-weight:500;letter-spacing:0.5px;color:var(--text-primary);">BOOKS</span></div>', unsafe_allow_html=True)
    if st.button("+ NEW", key="new_bk"):
        st.session_state["wizard"] = True

    for pname, pf in router.portfolios.items():
        p_pnl = pf.day_pnl
        tags = '<span class="tg tg-a">AUTO-BAL</span>' if pf.sizing_mode == "risk_parity" else ""
        tags += f'<span class="tg tg-d">{pf.sizing_mode.upper()[:6]}</span><span class="tg tg-d">{pf.risk_pct}%</span>'
        pc = "var(--text-success)" if p_pnl >= 0 else "var(--text-danger)"
        st.markdown(f'<div class="bk bk-on"><div class="bk-nm">{pname}</div><div class="bk-mt">{pf.broker_id}</div><div>{tags}</div><div style="display:flex;justify-content:space-between;font-size:10px;margin-top:3px;"><span style="color:var(--text-secondary);">{len(pf.strategy_names)} strats</span><span style="color:{pc};">${p_pnl:+,.0f}</span></div></div>', unsafe_allow_html=True)

    for aname, al in router.allocations.items():
        act = aname in state["active_trades"]
        cls = "bk-on" if act and al.enabled else "bk-off"
        tags = f'<span class="tg tg-d">SOLO</span><span class="tg tg-d">{al.allocation_pct:.0f}%</span><span class="tg tg-d">{al.quantity}x {al.symbol}</span>'
        st.markdown(f'<div class="bk {cls}"><div class="bk-nm">{aname}</div><div class="bk-mt">{al.broker_id}</div><div>{tags}</div></div>', unsafe_allow_html=True)

    booked = set()
    for p in router.portfolios.values():
        booked.update(p.strategy_names)
    booked.update(router.allocations.keys())
    for sn, sr in state["strategies"].items():
        if sn in booked:
            continue
        act = sn in state["active_trades"]
        cls = "bk-on" if act else "bk-off"
        st.markdown(f'<div class="bk {cls}"><div style="display:flex;justify-content:space-between;"><span class="bk-nm">{sn}</span><span style="font-size:10px;color:{"var(--text-success)" if sr.get("enabled") else "var(--text-muted)"};">{"ON" if sr.get("enabled") else "OFF"}</span></div><div class="bk-mt">{sr.get("broker","none")}</div></div>', unsafe_allow_html=True)

    # Drawdown
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    dd_u = abs(min(0, total_day_pnl))
    dd_l = float(os.environ.get("DAILY_LOSS_LIMIT", "4500"))
    dd_p = min(100, dd_u / dd_l * 100) if dd_l > 0 else 0
    dd_clr = "var(--text-success)" if dd_p < 50 else ("var(--text-warning)" if dd_p < 80 else "var(--text-danger)")
    st.markdown(f'<div style="padding:0 4px;"><div style="font-size:10px;color:var(--text-muted);letter-spacing:0.5px;">DRAWDOWN</div><div style="height:6px;background:var(--surface-0);border-radius:3px;overflow:hidden;margin:4px 0 3px;"><div style="width:{dd_p}%;height:100%;background:{dd_clr};border-radius:3px;"></div></div><div style="display:flex;justify-content:space-between;font-size:10px;"><span style="color:var(--text-secondary);">${dd_u:,.0f}</span><span style="color:var(--text-muted);">${dd_l:,.0f}</span></div></div>', unsafe_allow_html=True)

    # Strategies
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    st.markdown('<div style="padding:5px 10px;border-bottom:1px solid var(--border);"><span style="font-size:10px;font-weight:500;color:var(--text-muted);letter-spacing:0.5px;">STRATEGIES</span></div>', unsafe_allow_html=True)
    for sn, sr in state["strategies"].items():
        wr = sr.get("stats", {}).get("win_rate", 0)
        c = "var(--text-secondary)" if sr.get("enabled") else "var(--text-muted)"
        st.markdown(f'<div style="display:flex;justify-content:space-between;padding:2px 10px;font-size:10px;"><span style="color:{c};">{sn}</span><span style="color:var(--text-muted);">{wr}%</span></div>', unsafe_allow_html=True)

    # Connections
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.markdown('<div style="padding:5px 10px;border-bottom:1px solid var(--border);"><span style="font-size:10px;font-weight:500;color:var(--text-muted);letter-spacing:0.5px;">CONNECTIONS</span></div>', unsafe_allow_html=True)
    for bid, br in state["brokers"].items():
        dot = "var(--text-success)" if br.get("connected") else "var(--text-muted)"
        eq = br.get("equity", 0)
        lb = f"${eq/1000:.0f}k" if eq > 0 else "OFF"
        st.markdown(f'<div style="display:flex;justify-content:space-between;padding:2px 10px;font-size:10px;align-items:center;"><div style="display:flex;align-items:center;gap:4px;"><div style="width:5px;height:5px;border-radius:50%;background:{dot};"></div><span style="color:{"var(--text-secondary)" if br.get("connected") else "var(--text-muted)"};">{br.get("name",bid)}</span></div><span style="color:var(--text-muted);">{lb}</span></div>', unsafe_allow_html=True)

    # Actions
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        st.button("close", key="ca")
    with c2:
        st.button("off", key="da")
    with c3:
        st.button("log", key="ex")

# ══════════════════════════════════════════════════════════════
#  MAIN CONTENT
# ══════════════════════════════════════════════════════════════
if st.session_state.get("wizard"):
    st.subheader("New book")
    btype = st.radio("", ["Single strategy", "Portfolio"], horizontal=True, label_visibility="collapsed")

    if btype == "Single strategy":
        snames = list(state["strategies"].keys())
        bids = list(state["brokers"].keys())
        bnames = {b: state["brokers"][b].get("name", b) for b in bids}
        syms = ["SPY","QQQ","TSLA","NVDA","AAPL","AMZN","GOOGL","META","MSFT","GLD","MES1!","MNQ1!"]
        c1, c2 = st.columns(2)
        with c1:
            ss = st.selectbox("Strategy", snames, key="ws")
            sb = st.selectbox("Account", bids, format_func=lambda x: bnames.get(x,x), key="wb")
        with c2:
            sy = st.selectbox("Symbol", syms, key="wy")
            sq = st.number_input("Qty", 1, 100, 1, key="wq")
        sa = st.slider("Allocation %", 10, 100, 100, 10, key="wa")
        c1, c2 = st.columns([1,4])
        with c1:
            if st.button("Create", type="primary", key="wc"):
                router.allocations[ss] = DirectAllocation(ss, {"broker": sb, "symbol": sy, "allocation_pct": sa, "quantity": sq, "enabled": True})
                if ss in router.strategies:
                    router.strategies[ss].enabled = True
                router.save_portfolio_config()
                st.session_state["wizard"] = False
                st.rerun()
        with c2:
            if st.button("Cancel", key="wx"):
                st.session_state["wizard"] = False
                st.rerun()
    else:
        bids = list(state["brokers"].keys())
        bnames = {b: state["brokers"][b].get("name",b) for b in bids}
        snames = list(state["strategies"].keys())
        c1, c2 = st.columns(2)
        with c1:
            pn = st.text_input("Name", placeholder="e.g. Morning Scalps", key="pn")
            pb = st.selectbox("Account", bids, format_func=lambda x: bnames.get(x,x), key="pb")
        with c2:
            ps = st.selectbox("Sizing", ["risk_parity","equal_contracts","weighted","manual"], format_func=lambda x: {"risk_parity":"Risk parity (auto-balance)","equal_contracts":"Equal contracts","weighted":"Win rate weighted","manual":"Manual"}.get(x,x), key="ps")
            pr = st.slider("Risk %", 0.1, 5.0, 1.0, 0.1, key="pr")
        pt = st.multiselect("Strategies", snames, key="pt")
        if pt and pb:
            eq = state["brokers"].get(pb, {}).get("equity", 100000)
            syms = [router.routes.get(s, {}).get("symbol", "SPY") for s in pt]
            ad = get_asset_data(syms)
            tp = Portfolio("preview", {"risk_pct": pr, "sizing_mode": ps})
            sz = tp.calculate_position_sizes(eq, ad)
            st.caption(f"Preview — ${eq * pr / 100:,.0f} daily risk budget")
            for sym, qty in sz.items():
                st.text(f"  {sym}: {qty}x")
        c1, c2 = st.columns([1,4])
        with c1:
            if st.button("Create", type="primary", key="pc"):
                if pn and pt:
                    router.portfolios[pn] = Portfolio(pn, {"broker": pb, "risk_pct": pr, "sizing_mode": ps, "strategies": pt, "enabled": True})
                    for s in pt:
                        if s in router.strategies:
                            router.strategies[s].enabled = True
                    router.save_portfolio_config()
                    st.session_state["wizard"] = False
                    st.rerun()
        with c2:
            if st.button("Cancel", key="pcx"):
                st.session_state["wizard"] = False
                st.rerun()
else:
    # Open positions
    ot = {k: v for k, v in state["active_trades"].items() if v["status"] in ("OPEN", "SIM")}
    html = f'<div class="sec-hdr"><span class="sec-ttl">OPEN POSITIONS</span><span class="sec-sum">{len(ot)} active</span></div><table class="dt"><thead><tr><th>STRATEGY</th><th>BOOK</th><th>SYMBOL</th><th class="r">QTY</th><th>DIR</th><th class="r">CONF</th><th class="r">ENTRY</th></tr></thead><tbody>'
    for tn, tr in ot.items():
        d = tr["direction"]
        dc = "grn" if d in ("UP","LONG") else "red"
        bk = "Direct"
        for pn2, pf2 in router.portfolios.items():
            if tn in pf2.strategy_names:
                bk = pn2[:12]
                break
        ss2 = state["strategies"].get(tn, {})
        at = ss2.get("active_trade", {})
        cf = at.get("confidence", 0)
        et = at.get("entry_time", "?")
        sy2 = tr.get("symbol", "SPY")
        html += f'<tr><td>{tn}</td><td class="mut">{bk}</td><td class="mut">{sy2}</td><td class="r">—</td><td class="{dc}">{d}</td><td class="r mut">{cf:.1%}</td><td class="r mut">{et}</td></tr>'
    if not ot:
        html += '<tr><td colspan="7" class="mut" style="text-align:center;padding:12px;">No open positions</td></tr>'
    html += '</tbody></table>'
    st.markdown(html, unsafe_allow_html=True)
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # Closed
    cl = [l for l in state.get("log", []) if "closed" in l.lower() or "CLOSED" in l]
    st.markdown(f'<div class="sec-hdr"><span class="sec-ttl">CLOSED</span><span class="sec-sum">{len(cl)} today</span></div>', unsafe_allow_html=True)
    if cl:
        for line in reversed(cl[-10:]):
            st.markdown(f'<div style="padding:3px 10px;font-size:11px;color:var(--text-muted);background:var(--surface-1);">{line}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="padding:12px 10px;font-size:11px;color:var(--text-muted);background:var(--surface-1);text-align:center;">No closed trades today</div>', unsafe_allow_html=True)
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    # System log
    st.markdown('<div class="sec-hdr"><span class="sec-ttl">SYSTEM</span></div>', unsafe_allow_html=True)
    lh = '<div style="padding:6px 10px;background:var(--surface-1);">'
    for line in reversed(state.get("log", [])[-20:]):
        if "filled" in line.lower() or "FILL" in line:
            lh += f'<div class="log-l"><span class="log-ok">FILL</span> {line}</div>'
        elif "signal" in line.lower():
            lh += f'<div class="log-l"><span class="log-sg">SGNL</span> {line}</div>'
        elif "failed" in line.lower() or "error" in line.lower():
            lh += f'<div class="log-l"><span class="log-er">ERR</span> {line}</div>'
        else:
            lh += f'<div class="log-l">{line}</div>'
    if not state.get("log"):
        lh += '<div class="log-l">No activity yet</div>'
    lh += '</div>'
    st.markdown(lh, unsafe_allow_html=True)

# Auto-refresh during market hours
if 9 <= now.hour <= 16 and now.weekday() < 5:
    time.sleep(15)
    st.rerun()

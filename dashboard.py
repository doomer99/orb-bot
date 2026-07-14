import streamlit as st
import os
from datetime import datetime
import pytz
import time

ET = pytz.timezone("America/New_York")
from main import state, STOP_POINTS, TARGET_POINTS, SIM_MODE, P1_ENABLED, P1_QTY, P2_ENABLED, P2_QTY

st.set_page_config(page_title="ORB Signal", page_icon="📊", layout="centered")

st.markdown("""
<style>
html,body,[class*="css"]{background:#080c10!important;color:#c9d4e0;font-family:monospace}
.sbox{border-radius:10px;padding:28px 20px;text-align:center;margin:12px 0}
.sword{font-size:64px;font-weight:800;line-height:1}
.ssub{font-size:15px;margin-top:8px;opacity:.7}
.bl{background:rgba(46,204,113,.12);border:2px solid #2ecc71}
.bs{background:rgba(255,82,82,.12);border:2px solid #ff5252}
.bw{background:rgba(255,176,32,.10);border:2px solid #ffb020}
.bd{background:rgba(80,80,80,.12);border:2px solid #444}
.card{background:#0e1620;border:1px solid #1a2535;border-radius:8px;padding:14px;text-align:center;margin:4px 0}
.cl{color:#5a7a9a;font-size:10px;letter-spacing:.12em;text-transform:uppercase}
.cv{font-size:22px;font-weight:700;color:#e0eaf5;margin-top:4px}
.pon{background:rgba(46,204,113,.08);border:1px solid #2ecc71;border-radius:8px;padding:12px;margin:6px 0}
.poff{background:rgba(80,80,80,.08);border:1px solid #333;border-radius:8px;padding:12px;margin:6px 0}
.log{background:#050810;border:1px solid #1a2535;border-radius:8px;padding:10px;font-size:11px;color:#4a7a6a;height:140px;overflow-y:auto}
</style>""", unsafe_allow_html=True)

for k,v in [("p1_on",P1_ENABLED),("p2_on",P2_ENABLED),("p1_qty",P1_QTY),("p2_qty",P2_QTY),("acct",50000),("streak",0),("auto",True)]:
    if k not in st.session_state: st.session_state[k]=v

state["p1_enabled"]=st.session_state.p1_on
state["p2_enabled"]=st.session_state.p2_on
state["p1_qty"]=st.session_state.p1_qty
state["p2_qty"]=st.session_state.p2_qty

def rec(streak): return min(1+(streak//10),12)

def main():
    now=datetime.now(ET); phase=state.get("phase","waiting")
    direction=state.get("direction"); result=state.get("result")
    pnl=state.get("pnl_pts") or 0.0
    pnl_d=pnl*5.0*st.session_state.p1_qty

    # Header
    c1,c2=st.columns([4,1])
    with c1:
        st.markdown("### 📊 5-Min ORB")
        st.caption(now.strftime("%A  %b %d  %H:%M:%S ET"))
    with c2:
        clr="#ffb020" if SIM_MODE else "#ff5252"
        st.markdown(f"<div style='text-align:right;color:{clr};font-weight:700;padding-top:10px'>{'SIM' if SIM_MODE else 'LIVE'}</div>",unsafe_allow_html=True)

    st.divider()

    # Signal banner
    if phase=="waiting":
        st.markdown("<div class='sbox bw'><div class='sword' style='color:#ffb020'>⏳ WAITING</div><div class='ssub'>Opens 9:30 AM ET</div></div>",unsafe_allow_html=True)
    elif phase=="building":
        mins=max(0,35-now.minute) if now.hour==9 else 0
        st.markdown(f"<div class='sbox bw'><div class='sword' style='color:#ffb020'>📏 RANGE</div><div class='ssub'>Building — {mins} min to signal</div></div>",unsafe_allow_html=True)
    elif phase=="watching":
        st.markdown("<div class='sbox bw'><div class='sword' style='color:#ffb020'>👀 WATCH</div><div class='ssub'>Waiting for breakout...</div></div>",unsafe_allow_html=True)
    elif phase=="active":
        pc="#2ecc71" if pnl>=0 else "#ff5252"
        if direction=="UP":
            st.markdown(f"<div class='sbox bl'><div class='sword' style='color:#2ecc71'>🚀 LONG</div><div class='ssub'>Active — <span style='color:{pc}'>{pnl:+.1f}pts (${pnl_d:+.0f})</span></div></div>",unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='sbox bs'><div class='sword' style='color:#ff5252'>🔻 SHORT</div><div class='ssub'>Active — <span style='color:{pc}'>{pnl:+.1f}pts (${pnl_d:+.0f})</span></div></div>",unsafe_allow_html=True)
    elif phase=="done":
        if result=="WIN":
            st.markdown(f"<div class='sbox bl'><div class='sword' style='color:#2ecc71'>✅ WIN</div><div class='ssub'>{direction} +{pnl:.1f}pts (${pnl_d:+.0f})</div></div>",unsafe_allow_html=True)
        elif result=="LOSS":
            st.markdown(f"<div class='sbox bs'><div class='sword' style='color:#ff5252'>❌ LOSS</div><div class='ssub'>{direction} {pnl:.1f}pts (${pnl_d:+.0f})</div></div>",unsafe_allow_html=True)
        else:
            st.markdown("<div class='sbox bd'><div class='sword' style='color:#888'>✓ DONE</div><div class='ssub'>No trade today</div></div>",unsafe_allow_html=True)

    # Range metrics
    high5=state.get("high5"); low5=state.get("low5")
    if high5:
        c1,c2,c3=st.columns(3)
        for col,(lbl,val,clr) in zip([c1,c2,c3],[("HIGH",f"{high5:.2f}","#2ecc71"),("LOW",f"{low5:.2f}","#ff5252"),("RANGE",f"{state.get('range_size',0):.2f}","#e0eaf5")]):
            with col: st.markdown(f"<div class='card'><div class='cl'>{lbl}</div><div class='cv' style='color:{clr}'>{val}</div></div>",unsafe_allow_html=True)

    entry=state.get("entry_idx")
    if entry and phase in ("active","done"):
        c1,c2,c3=st.columns(3)
        for col,(lbl,val,clr) in zip([c1,c2,c3],[("ENTRY",f"{entry:.0f}","#e0eaf5"),("STOP",f"{state.get('stop',0):.0f}","#ff5252"),("TARGET",f"{state.get('target',0):.0f}","#2ecc71")]):
            with col: st.markdown(f"<div class='card'><div class='cl'>{lbl}</div><div class='cv' style='color:{clr}'>{val}</div></div>",unsafe_allow_html=True)

    st.divider()

    # Account balance
    st.markdown("#### 💰 Account Balance")
    equity=state.get("equity",0.0)
    cash=state.get("cash",0.0)
    bal_pnl=state.get("day_pnl",0.0)
    pnl_c="#2ecc71" if bal_pnl>=0 else "#ff5252"
    sand=os.environ.get("TRADIER_SANDBOX","true").lower()=="true"
    lbl="SANDBOX" if sand else "LIVE"
    c1,c2,c3=st.columns(3)
    with c1:
        st.markdown(f"<div class='card'><div class='cl'>EQUITY ({lbl})</div><div class='cv' style='color:#2ecc71'>${equity:,.0f}</div></div>",unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='card'><div class='cl'>CASH</div><div class='cv'>${cash:,.0f}</div></div>",unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='card'><div class='cl'>DAY P&L</div><div class='cv' style='color:{pnl_c}'>${bal_pnl:+,.0f}</div></div>",unsafe_allow_html=True)

    st.divider()

    # Pipeline toggles
    st.markdown("#### ⚡ Pipelines")
    for key,lbl,desc,sk in [("p1_on","P1 — Topstep","MES futures","p1_status"),("p2_on","P2 — TradeYour","0DTE options","p2_status")]:
        is_on=st.session_state[key]; icon="🟢" if is_on else "⚫"
        cls="pon" if is_on else "poff"; status=state.get(sk,"—")
        qty=st.session_state.get(key.replace("_on","_qty"),1)
        col1,col2=st.columns([3,1])
        with col1:
            st.markdown(f"<div class='{cls}'>{icon} <b>{lbl}</b> ({desc})<br><span style='color:#5a7a9a;font-size:12px'>Qty: {qty} | {status}</span></div>",unsafe_allow_html=True)
        with col2:
            if st.button("OFF" if is_on else "ON",key=f"btn_{key}"):
                st.session_state[key]=not is_on
                state[key]=not is_on
                st.rerun()

    st.divider()

    # Contract sizing
    st.markdown("#### 📐 Contract Sizing")
    auto=st.toggle("Auto-size (step-up rules)",value=st.session_state.auto)
    st.session_state.auto=auto
    if auto:
        c1,c2=st.columns(2)
        with c1:
            acct=st.number_input("Account ($)",min_value=1000,max_value=500000,value=st.session_state.acct,step=1000)
            st.session_state.acct=acct
        with c2:
            streak=st.number_input("Win streak",min_value=0,max_value=100,value=st.session_state.streak,step=1)
            st.session_state.streak=streak
        r=rec(streak)
        st.markdown(f"<div class='card' style='margin-top:8px'><div class='cl'>RECOMMENDED CONTRACTS</div><div class='cv' style='font-size:40px;color:#2ecc71'>{r}</div><div style='color:#5a7a9a;font-size:11px;margin-top:4px'>1 per 10 wins, max 12</div></div>",unsafe_allow_html=True)
        if st.button("✅ Apply to Pipeline 1"):
            st.session_state.p1_qty=r; state["p1_qty"]=r
            st.success(f"Set to {r} contracts")
    else:
        p1m=st.slider("Topstep contracts",1,12,st.session_state.p1_qty)
        st.session_state.p1_qty=p1m; state["p1_qty"]=p1m
        p2m=st.slider("TradeYour quantity",1,20,st.session_state.p2_qty)
        st.session_state.p2_qty=p2m; state["p2_qty"]=p2m
        st.markdown(f"<div class='card'><div class='cl'>MAX LOSS THIS TRADE</div><div class='cv' style='color:#ff5252'>${p1m*8*5:,.0f}</div><div style='color:#5a7a9a;font-size:11px;margin-top:4px'>{p1m} contracts x 8pts x $5</div></div>",unsafe_allow_html=True)

    st.divider()

    # Log
    st.markdown("**Activity**")
    logs=state.get("log",["No activity yet"])
    st.markdown(f"<div class='log'>{'<br>'.join(reversed(logs[-15:]))}</div>",unsafe_allow_html=True)
    st.divider()
    st.caption(f"Stop {STOP_POINTS:.0f}pts · Target {TARGET_POINTS:.0f}pts · Updated {state.get('last_update','—')}")
    time.sleep(20)
    st.rerun()

main()
main()

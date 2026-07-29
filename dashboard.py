# dashboard.py — Trading Command Center (Streamlit)
# Run with: streamlit run dashboard.py

import streamlit as st
import time
from datetime import datetime
import pytz

ET = pytz.timezone("America/New_York")

# Import the router from main.py
from main import router

st.set_page_config(
    page_title="Trading Command Center",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════
#  STYLING
# ══════════════════════════════════════════════════════════════
st.markdown("""
<style>
    .block-container {padding-top: 1.5rem; padding-bottom: 1rem;}
    .metric-card {
        background: #1e1e2e;
        border: 1px solid #333;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
    }
    .broker-card {
        background: #1a1a2e;
        border: 1px solid #2a2a4a;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
    }
    .strategy-card {
        background: #1a2e1a;
        border: 1px solid #2a4a2a;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
    }
    .log-box {
        background: #111;
        border: 1px solid #333;
        border-radius: 8px;
        padding: 12px;
        font-family: monospace;
        font-size: 12px;
        max-height: 400px;
        overflow-y: auto;
    }
    .status-live {color: #22c55e; font-weight: bold;}
    .status-off {color: #666;}
    .status-error {color: #ef4444;}
    .pnl-pos {color: #22c55e; font-size: 24px; font-weight: bold;}
    .pnl-neg {color: #ef4444; font-size: 24px; font-weight: bold;}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  GET STATE
# ══════════════════════════════════════════════════════════════
state = router.get_state()
now = datetime.now(ET)


# ══════════════════════════════════════════════════════════════
#  HEADER
# ══════════════════════════════════════════════════════════════
col1, col2, col3 = st.columns([3, 1, 1])
with col1:
    st.title("📊 Trading Command Center")
    mode = "🟡 SIM MODE" if state["sim_mode"] else "🟢 LIVE"
    st.caption(f"{mode} | {now.strftime('%A %B %d, %Y %I:%M %p ET')}")
with col3:
    if st.button("🔄 Refresh"):
        st.rerun()


# ══════════════════════════════════════════════════════════════
#  SIDEBAR — BROKER ACCOUNTS
# ══════════════════════════════════════════════════════════════
st.sidebar.header("🏦 Accounts")

for bid, broker in state["brokers"].items():
    with st.sidebar.container():
        connected = "🟢" if broker.get("connected") else "🔴"
        st.sidebar.subheader(f"{connected} {broker.get('name', bid)}")

        if broker.get("connected"):
            equity = broker.get("equity", 0)
            day_pnl = broker.get("day_pnl", 0)
            cash = broker.get("cash", 0)

            c1, c2 = st.sidebar.columns(2)
            c1.metric("Equity", f"${equity:,.2f}")
            pnl_color = "🟢" if day_pnl >= 0 else "🔴"
            c2.metric("Day P&L",
                      f"${day_pnl:+,.2f}",
                      delta=f"{pnl_color}")
            st.sidebar.caption(f"Cash: ${cash:,.2f} | Type: {broker.get('type', '?')}")

            # Positions
            positions = broker.get("positions", [])
            if positions:
                st.sidebar.caption(f"Open positions: {len(positions)}")
                for p in positions:
                    st.sidebar.text(
                        f"  {p['symbol']} {p['quantity']}x "
                        f"P&L: ${p.get('pnl', 0):+.2f}"
                    )
        else:
            err = broker.get("error", "Unknown error")
            st.sidebar.error(f"Disconnected: {err}")

        st.sidebar.divider()

# Quick add broker hint
st.sidebar.caption(
    "💡 Add brokers via Railway env vars:\n"
    "TRADIER_TOKEN, TRADIER_ACCOUNT\n"
    "P1_WEBHOOK_URL (TradersPost)"
)


# ══════════════════════════════════════════════════════════════
#  MAIN — STRATEGIES
# ══════════════════════════════════════════════════════════════
st.header("⚡ Strategies")

strat_cols = st.columns(max(len(state["strategies"]), 1))

for i, (name, strat) in enumerate(state["strategies"].items()):
    col = strat_cols[i % len(strat_cols)]

    with col:
        # Status indicator
        if strat.get("active_trade"):
            trade = strat["active_trade"]
            direction = trade["direction"]
            arrow = "📈" if direction == "UP" else "📉"
            st.subheader(f"{arrow} {name}")
            st.success(
                f"**{direction}** | {trade['confidence']:.1%} confident\n\n"
                f"Entry: {trade['entry_time']} | Status: {trade['status']}"
            )
        elif strat.get("enabled") and strat.get("ready"):
            st.subheader(f"✅ {name}")
            st.info("Ready — waiting for signal window")
        elif strat.get("enabled"):
            st.subheader(f"⏳ {name}")
            st.warning("Enabled but not ready (initializing)")
        else:
            st.subheader(f"⏸️ {name}")
            st.caption("Disabled")

        # Stats
        stats = strat.get("stats", {})
        if stats.get("total", 0) > 0:
            c1, c2, c3 = st.columns(3)
            c1.metric("Win Rate", f"{stats['win_rate']}%")
            c2.metric("Trades", stats["total"])
            c3.metric("Recent P&L", f"{stats['recent_pnl']:+.2f}%")

        # Route info
        broker_id = strat.get("broker", "none")
        broker_name = state["brokers"].get(broker_id, {}).get("name", broker_id)
        st.caption(
            f"→ {broker_name} | {strat.get('quantity', 1)}x "
            f"{strat.get('symbol', 'SPY')}"
        )
        st.caption(strat.get("description", ""))

        # Last signal
        last = strat.get("last_signal")
        if last:
            st.caption(
                f"Last signal: {last['direction']} @ "
                f"{last.get('entry_time', '?')} "
                f"({last['confidence']:.1%})"
            )


# ══════════════════════════════════════════════════════════════
#  ACTIVITY LOG
# ══════════════════════════════════════════════════════════════
st.header("📋 Activity Log")

log_lines = state.get("log", [])
if log_lines:
    log_text = "\n".join(reversed(log_lines[-40:]))
    st.code(log_text, language=None)
else:
    st.caption("No activity yet")


# ══════════════════════════════════════════════════════════════
#  CONTROLS
# ══════════════════════════════════════════════════════════════
with st.expander("⚙️ Controls"):
    st.subheader("Strategy Toggles")
    st.caption(
        "Strategy enable/disable and routing is controlled via "
        "Railway environment variables. Set these in your Railway dashboard:"
    )
    st.code("""
# Enable/disable strategies
ROUTE_NOUR_ENABLED=true
ROUTE_NOUR_BROKER=tradier_sandbox
ROUTE_NOUR_QTY=1
ROUTE_NOUR_SYMBOL=SPY

# Future strategies
ROUTE_STOCHASTIC_ENABLED=false
ROUTE_STOCHASTIC_BROKER=tradier_sandbox
ROUTE_TREND_FLIP_ENABLED=false
ROUTE_TREND_FLIP_BROKER=topstep
    """)

    st.subheader("Broker Setup")
    st.code("""
# Tradier (sandbox or live)
TRADIER_TOKEN=your_token
TRADIER_ACCOUNT=your_account_id
TRADIER_SANDBOX=true

# TradersPost / TopStep
P1_WEBHOOK_URL=https://traderspost.io/...
P1_PASSWORD=your_password
P1_TICKER=MES1!
    """)


# ══════════════════════════════════════════════════════════════
#  AUTO-REFRESH
# ══════════════════════════════════════════════════════════════
# Refresh every 15 seconds during market hours
if 9 <= now.hour <= 16 and now.weekday() < 5:
    time.sleep(15)
    st.rerun()

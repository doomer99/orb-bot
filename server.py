# server.py — FastAPI server for the trading dashboard
# Replaces Streamlit. Serves HTML + JSON API for live state.

import os
import json
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import threading
import requests as http_requests

from main import router
from portfolio import Portfolio, DirectAllocation

app = FastAPI(title="Broadbent Capital")

# ── Config ──

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Alternative AI providers — set whichever you have
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Log which keys are configured at startup
print(f"API Keys: Polygon={'YES' if POLYGON_API_KEY else 'NO'} | Gemini={'YES' if GEMINI_API_KEY else 'NO'} | DeepSeek={'YES' if DEEPSEEK_API_KEY else 'NO'} | Anthropic={'YES' if ANTHROPIC_API_KEY else 'NO'}")


# ══════════════════════════════════════════════
# EXISTING ENDPOINTS (unchanged)
# ══════════════════════════════════════════════

@app.get("/api/state")
def get_state():
    """Full state snapshot for the dashboard."""
    return router.get_state()


@app.post("/api/circuit-breaker/activate")
def activate_cb():
    router.activate_circuit_breaker()
    return {"ok": True}


@app.post("/api/circuit-breaker/deactivate")
def deactivate_cb():
    router.deactivate_circuit_breaker()
    return {"ok": True}


class CreateAllocationReq(BaseModel):
    strategy: str
    broker: str
    symbol: str = "SPY"
    quantity: int = 1
    allocation_pct: float = 100.0


@app.post("/api/allocation/create")
def create_allocation(req: CreateAllocationReq):
    alloc = DirectAllocation(req.strategy, {
        "broker": req.broker,
        "symbol": req.symbol,
        "quantity": req.quantity,
        "allocation_pct": req.allocation_pct,
        "enabled": True,
    })
    router.allocations[req.strategy] = alloc
    if req.strategy in router.strategies:
        router.strategies[req.strategy].enabled = True
    router.save_portfolio_config()
    return {"ok": True}


class CreatePortfolioReq(BaseModel):
    name: str
    broker: str
    strategies: List[str]
    sizing_mode: str = "risk_parity"
    risk_pct: float = 1.0


@app.post("/api/portfolio/create")
def create_portfolio(req: CreatePortfolioReq):
    portfolio = Portfolio(req.name, {
        "broker": req.broker,
        "risk_pct": req.risk_pct,
        "sizing_mode": req.sizing_mode,
        "strategies": req.strategies,
        "enabled": True,
    })
    router.portfolios[req.name] = portfolio
    for sn in req.strategies:
        if sn in router.strategies:
            router.strategies[sn].enabled = True
    router.save_portfolio_config()
    return {"ok": True}


@app.post("/api/book/{name}/toggle")
def toggle_book(name: str):
    if name in router.portfolios:
        router.portfolios[name].enabled = not router.portfolios[name].enabled
        router.save_portfolio_config()
        return {"ok": True, "enabled": router.portfolios[name].enabled}
    if name in router.allocations:
        router.allocations[name].enabled = not router.allocations[name].enabled
        router.save_portfolio_config()
        return {"ok": True, "enabled": router.allocations[name].enabled}
    return {"ok": False, "error": "Not found"}


# ══════════════════════════════════════════════
# NEW ENDPOINTS
# ══════════════════════════════════════════════

# ── Sell All (per portfolio) ──

class SellAllReq(BaseModel):
    name: str


@app.post("/api/portfolio/sell-all")
def sell_all(req: SellAllReq):
    """Close all open positions in a specific portfolio."""
    closed = []
    for trade_name, trade in list(router.active_trades.items()):
        if trade["status"] not in ("OPEN", "SIM"):
            continue
        # Check if this trade belongs to the requested portfolio
        routing = router._resolve_route(trade_name)
        belongs = False
        if routing["type"] == "portfolio" and routing.get("portfolio") == req.name:
            belongs = True
        elif routing["type"] == "direct" and trade_name == req.name:
            belongs = True
        # Also match by strategy name if portfolio contains it
        if req.name in router.portfolios:
            if trade_name in router.portfolios[req.name].strategy_names:
                belongs = True
        if belongs:
            router.log(f"SELL ALL [{req.name}] — closing [{trade_name}]")
            router.close_order(trade_name)
            closed.append(trade_name)
    return {"ok": True, "closed": closed}


# ── Kill All (emergency stop) ──

@app.post("/api/kill-all")
def kill_all():
    """Emergency: activate circuit breaker, close everything."""
    router.activate_circuit_breaker()
    return {"ok": True}


# ── Polygon Quotes (for watchlist prices) ──

@app.get("/api/quotes")
def get_quotes(symbols: str = "SPY"):
    """Fetch latest quotes from Polygon for watchlist."""
    if not POLYGON_API_KEY:
        return {"error": "POLYGON_API_KEY not set", "quotes": {}}
    
    symbol_list = [s.strip().upper() for s in symbols.split(",")]
    quotes = {}
    
    try:
        # Polygon snapshot endpoint — gets latest price for multiple tickers
        tickers_param = ",".join(symbol_list)
        r = http_requests.get(
            f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers",
            params={"tickers": tickers_param, "apiKey": POLYGON_API_KEY},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            for ticker in data.get("tickers", []):
                sym = ticker.get("ticker", "")
                day = ticker.get("day", {})
                quotes[sym] = {
                    "price": ticker.get("lastTrade", {}).get("p", 0) or day.get("c", 0),
                    "change": day.get("c", 0) - day.get("o", 0) if day.get("o") else 0,
                    "change_pct": ((day.get("c", 0) - day.get("o", 0)) / day.get("o", 1) * 100) if day.get("o") else 0,
                    "volume": day.get("v", 0),
                }
        else:
            # Fallback: try individual quotes
            for sym in symbol_list:
                try:
                    r2 = http_requests.get(
                        f"https://api.polygon.io/v2/aggs/ticker/{sym}/prev",
                        params={"apiKey": POLYGON_API_KEY},
                        timeout=5
                    )
                    if r2.status_code == 200:
                        results = r2.json().get("results", [])
                        if results:
                            quotes[sym] = {
                                "price": results[0].get("c", 0),
                                "change": results[0].get("c", 0) - results[0].get("o", 0),
                                "volume": results[0].get("v", 0),
                            }
                except Exception:
                    pass
    except Exception as e:
        return {"error": str(e), "quotes": quotes}
    
    return {"quotes": quotes}


# ── Terminal AI System ──

def _build_terminal_context():
    """Build context string from current state for AI prompts."""
    state = router.get_state()
    
    # Summarize positions
    positions = []
    for name, trade in state.get("active_trades", {}).items():
        if trade.get("status") in ("OPEN", "SIM"):
            positions.append(f"  - {name}: {trade.get('direction', '?')} {trade.get('symbol', '?')}")
    
    # Summarize brokers
    brokers = []
    for bid, b in state.get("brokers", {}).items():
        if b.get("connected"):
            brokers.append(f"  - {b.get('name', bid)}: equity=${b.get('equity', 0):,.0f}, day_pnl=${b.get('day_pnl', 0):,.2f}")
    
    # Summarize portfolios
    portfolios = []
    for name, p in state.get("portfolios", {}).items():
        portfolios.append(f"  - {name}: broker={p.get('broker', '?')}, strategies={p.get('strategies', [])}")
    
    ctx = f"""Current state of Broadbent Capital trading system:
Mode: {'SIM' if state.get('sim_mode') else 'LIVE'}
Circuit breaker: {'ACTIVE' if state.get('circuit_breaker') else 'inactive'}

Connected brokers:
{chr(10).join(brokers) if brokers else '  None connected'}

Open positions:
{chr(10).join(positions) if positions else '  No open positions'}

Portfolios:
{chr(10).join(portfolios) if portfolios else '  No portfolios configured'}

Recent log:
{chr(10).join('  ' + l for l in (state.get('log', []))[-10:])}
"""
    return ctx


def _call_ai(prompt: str, system_prompt: str = "") -> str:
    """Call whichever AI provider is configured. Tries Gemini first, then DeepSeek, then Claude."""
    
    # Try Gemini (free tier)
    if GEMINI_API_KEY:
        try:
            r = http_requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}],
                    "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.7}
                },
                timeout=30
            )
            print(f"Gemini status: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                print(f"Gemini response: {r.text[:300]}")
        except Exception as e:
            print(f"Gemini error: {e}")
    
    # Try DeepSeek
    if DEEPSEEK_API_KEY:
        try:
            r = http_requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_prompt} if system_prompt else None,
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.7
                },
                timeout=30
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"DeepSeek error: {e}")
    
    # Try Claude
    if ANTHROPIC_API_KEY:
        try:
            r = http_requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 1000,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=30
            )
            if r.status_code == 200:
                return r.json()["content"][0]["text"]
        except Exception as e:
            print(f"Claude error: {e}")
    
    return ""


TERMINAL_SYSTEM_PROMPT = """You are Terminal, the AI assistant for Broadbent Capital — a personal algorithmic trading operation.

Your job is to provide concise, actionable market intelligence. When generating a daily briefing, cover:
1. OVERNIGHT/PRE-MARKET: Futures direction, key overnight moves, dollar/yields/VIX
2. SECTOR ROTATION: Which sectors are leading/lagging, where money is flowing
3. OPPORTUNITIES: New trade setups across all sectors — oversold bounces, breakouts, unusual volume. Include things NOT on the watchlist.
4. POSITION ANALYSIS: Commentary on any open positions, key levels to watch
5. RISK FLAGS: Upcoming catalysts (FOMC, earnings, economic data), correlation warnings, exposure concerns
6. CALENDAR: Today's economic events with times and estimates

Keep it tight — this displays in a small panel. No fluff. Use specific numbers (RSI values, price levels, percentages). 
Speak directly like a trading desk analyst would."""


@app.get("/api/terminal/briefing")
def terminal_briefing():
    """Auto-generate daily briefing using AI + current portfolio context."""
    context = _build_terminal_context()
    prompt = f"""Generate today's trading briefing for Broadbent Capital.

{context}

Cover: overnight moves, sector rotation, new opportunities, position analysis, risk flags, and today's calendar. Be specific with numbers and levels."""
    
    briefing = _call_ai(prompt, TERMINAL_SYSTEM_PROMPT)
    
    if not briefing:
        return {"briefing": "No AI provider configured. Set GEMINI_API_KEY, DEEPSEEK_API_KEY, or ANTHROPIC_API_KEY in your environment variables."}
    
    return {"briefing": briefing}


class TerminalAskReq(BaseModel):
    question: str
    context: Optional[dict] = None


@app.post("/api/terminal/ask")
def terminal_ask(req: TerminalAskReq):
    """Ask Terminal a question with portfolio context."""
    context = _build_terminal_context()
    prompt = f"""{context}

User question: {req.question}

Answer concisely and specifically. Use numbers, levels, and actionable insight."""
    
    answer = _call_ai(prompt, TERMINAL_SYSTEM_PROMPT)
    
    if not answer:
        return {"answer": "No AI provider configured. Set GEMINI_API_KEY, DEEPSEEK_API_KEY, or ANTHROPIC_API_KEY."}
    
    return {"answer": answer}


# ── Serve HTML dashboard ──

@app.get("/", response_class=HTMLResponse)
def dashboard():
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(html_path, "r") as f:
        return f.read()


# ── Start ──

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

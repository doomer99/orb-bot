# server.py — FastAPI server for the trading dashboard
import os
import json
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
import requests as http_requests

from main import router

app = FastAPI(title="Broadbent Capital")

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

print(f"API Keys: Polygon={'YES' if POLYGON_API_KEY else 'NO'} | "
      f"Gemini={'YES' if GEMINI_API_KEY else 'NO'} | "
      f"DeepSeek={'YES' if DEEPSEEK_API_KEY else 'NO'} | "
      f"Anthropic={'YES' if ANTHROPIC_API_KEY else 'NO'}")


# ══════════════════════════════════════════════
#  CORE API
# ══════════════════════════════════════════════

@app.get("/api/state")
def get_state():
    return router.get_state()


@app.post("/api/circuit-breaker/activate")
def activate_cb():
    router.activate_circuit_breaker()
    return {"ok": True}


@app.post("/api/circuit-breaker/deactivate")
def deactivate_cb():
    router.deactivate_circuit_breaker()
    return {"ok": True}


# ══════════════════════════════════════════════
#  PORTFOLIO CRUD
# ══════════════════════════════════════════════

class CreatePortfolioReq(BaseModel):
    name: str
    broker: str
    strategy: str
    symbol: str = "SPY"
    quantity: int = 1
    risk_pct: float = 1.0
    max_daily_loss: float = 0


@app.post("/api/portfolio/create")
def create_portfolio(req: CreatePortfolioReq):
    portfolio = router.create_portfolio(
        name=req.name, broker=req.broker, strategy=req.strategy,
        symbol=req.symbol, quantity=req.quantity,
        risk_pct=req.risk_pct, max_daily_loss=req.max_daily_loss,
    )
    return {"ok": True, "portfolio": portfolio.to_dict()}


@app.delete("/api/portfolio/{name}")
def delete_portfolio(name: str):
    ok = router.delete_portfolio(name)
    return {"ok": ok, "error": None if ok else "Not found"}


@app.post("/api/portfolio/{name}/toggle")
def toggle_portfolio(name: str):
    if name in router.portfolios:
        p = router.portfolios[name]
        p.enabled = not p.enabled
        from portfolio import save_portfolios
        save_portfolios(router.portfolios)
        router.log(f"Portfolio [{name}] {'enabled' if p.enabled else 'disabled'} via dashboard")
        return {"ok": True, "enabled": p.enabled}
    return {"ok": False, "error": "Not found"}


class UpdatePortfolioReq(BaseModel):
    risk_pct: Optional[float] = None
    quantity: Optional[int] = None
    max_daily_loss: Optional[float] = None
    symbol: Optional[str] = None


@app.put("/api/portfolio/{name}")
def update_portfolio(name: str, req: UpdatePortfolioReq):
    if name not in router.portfolios:
        return {"ok": False, "error": "Not found"}
    p = router.portfolios[name]
    if req.risk_pct is not None:
        p.risk_pct = req.risk_pct
    if req.quantity is not None:
        p.quantity = req.quantity
    if req.max_daily_loss is not None:
        p.max_daily_loss = req.max_daily_loss
    if req.symbol is not None:
        p.symbol = req.symbol
    from portfolio import save_portfolios
    save_portfolios(router.portfolios)
    router.log(f"Portfolio [{name}] updated via dashboard")
    return {"ok": True, "portfolio": p.to_dict()}


# ══════════════════════════════════════════════
#  SELL / KILL
# ══════════════════════════════════════════════

@app.post("/api/portfolio/{name}/close")
def close_portfolio_trade(name: str):
    ok = router._close_order(name)
    return {"ok": ok}


@app.post("/api/kill-all")
def kill_all():
    router.activate_circuit_breaker()
    return {"ok": True}


# ══════════════════════════════════════════════
#  QUOTES
# ══════════════════════════════════════════════

@app.get("/api/quotes")
def get_quotes(symbols: str = "SPY"):
    if not POLYGON_API_KEY:
        return {"error": "POLYGON_API_KEY not set", "quotes": {}}
    symbol_list = [s.strip().upper() for s in symbols.split(",")]
    quotes = {}
    try:
        tickers_param = ",".join(symbol_list)
        r = http_requests.get(
            "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers",
            params={"tickers": tickers_param, "apiKey": POLYGON_API_KEY},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            for ticker in data.get("tickers", []):
                sym = ticker.get("ticker", "")
                day = ticker.get("day", {})
                quotes[sym] = {
                    "price": ticker.get("lastTrade", {}).get("p", 0) or day.get("c", 0),
                    "change_pct": ((day.get("c", 0) - day.get("o", 0)) / day.get("o", 1) * 100) if day.get("o") else 0,
                    "volume": day.get("v", 0),
                }
        else:
            for sym in symbol_list:
                try:
                    r2 = http_requests.get(
                        f"https://api.polygon.io/v2/aggs/ticker/{sym}/prev",
                        params={"apiKey": POLYGON_API_KEY},
                        timeout=5,
                    )
                    if r2.status_code == 200:
                        results = r2.json().get("results", [])
                        if results:
                            quotes[sym] = {
                                "price": results[0].get("c", 0),
                                "change_pct": 0,
                                "volume": results[0].get("v", 0),
                            }
                except Exception:
                    pass
    except Exception as e:
        return {"error": str(e), "quotes": quotes}
    return {"quotes": quotes}


# ══════════════════════════════════════════════
#  AI TERMINAL
# ══════════════════════════════════════════════

def _build_terminal_context():
    state = router.get_state()
    positions = []
    for name, trade in state.get("active_trades", {}).items():
        if trade.get("status") in ("OPEN", "SIM"):
            positions.append(f"  - {name}: {trade.get('direction', '?')} "
                             f"{trade.get('symbol', '?')} x{trade.get('quantity', 1)}")
    brokers = []
    for bid, b in state.get("brokers", {}).items():
        if b.get("connected"):
            brokers.append(f"  - {b.get('name', bid)}: equity=${b.get('equity', 0):,.0f}, "
                           f"day_pnl=${b.get('day_pnl', 0):,.2f}")
    portfolios = []
    for pname, p in state.get("portfolios", {}).items():
        status = "enabled" if p.get("enabled") else "disabled"
        traded = "traded" if p.get("today_traded") else "waiting"
        portfolios.append(f"  - {pname}: {p.get('strategy', '?')} -> "
                          f"{p.get('broker', '?')} ({p.get('symbol', '?')}) [{status}, {traded}]")
    return f"""Broadbent Capital trading system:
Mode: {'SIM' if state.get('sim_mode') else 'LIVE'}
Brokers:
{chr(10).join(brokers) if brokers else '  None connected'}
Portfolios:
{chr(10).join(portfolios) if portfolios else '  None configured'}
Open positions:
{chr(10).join(positions) if positions else '  None'}
Recent log:
{chr(10).join('  ' + l for l in (state.get('log', []))[-10:])}"""


def _call_ai(prompt, system_prompt=""):
    if GEMINI_API_KEY:
        try:
            r = http_requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
                json={"contents": [{"parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}],
                      "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.7}},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"Gemini error: {e}")
    if DEEPSEEK_API_KEY:
        try:
            msgs = []
            if system_prompt:
                msgs.append({"role": "system", "content": system_prompt})
            msgs.append({"role": "user", "content": prompt})
            r = http_requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                          "Content-Type": "application/json"},
                json={"model": "deepseek-chat", "messages": msgs,
                      "max_tokens": 1000, "temperature": 0.7},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"DeepSeek error: {e}")
    if ANTHROPIC_API_KEY:
        try:
            r = http_requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY,
                          "anthropic-version": "2023-06-01",
                          "Content-Type": "application/json"},
                json={"model": "claude-sonnet-4-6", "max_tokens": 1000,
                      "system": system_prompt,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["content"][0]["text"]
        except Exception as e:
            print(f"Claude error: {e}")
    return ""


TERMINAL_SYSTEM_PROMPT = """You are Terminal, the AI assistant for Broadbent Capital — a personal algorithmic trading operation.
Provide concise, actionable market intelligence. Cover overnight moves, sector rotation, opportunities, position analysis, risk flags, and calendar.
Keep it tight. Use specific numbers. Speak like a trading desk analyst."""


@app.get("/api/terminal/briefing")
def terminal_briefing():
    context = _build_terminal_context()
    prompt = (f"Generate today's trading briefing.\n\n{context}\n\n"
              f"Cover: overnight moves, sector rotation, opportunities, "
              f"position analysis, risk flags, calendar.")
    briefing = _call_ai(prompt, TERMINAL_SYSTEM_PROMPT)
    if not briefing:
        return {"briefing": "No AI provider configured. Set GEMINI_API_KEY, "
                            "DEEPSEEK_API_KEY, or ANTHROPIC_API_KEY."}
    return {"briefing": briefing}


class TerminalAskReq(BaseModel):
    question: str


@app.post("/api/terminal/ask")
def terminal_ask(req: TerminalAskReq):
    context = _build_terminal_context()
    prompt = (f"{context}\n\nUser question: {req.question}\n\n"
              f"Answer concisely with numbers and actionable insight.")
    answer = _call_ai(prompt, TERMINAL_SYSTEM_PROMPT)
    if not answer:
        return {"answer": "No AI provider configured."}
    return {"answer": answer}


# ══════════════════════════════════════════════
#  SERVE DASHBOARD HTML
# ══════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def dashboard():
    paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html"),
        "/app/dashboard.html",
        "dashboard.html",
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, "r") as f:
                return f.read()
    return HTMLResponse(f"<h1>dashboard.html not found</h1><p>Searched: {paths}</p>",
                        status_code=500)


# ══════════════════════════════════════════════
#  START
# ══════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, workers=1)

# server.py — FastAPI server for the trading dashboard
# Replaces Streamlit. Serves HTML + JSON API for live state.

import os
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import threading

from main import router
from portfolio import Portfolio, DirectAllocation

app = FastAPI(title="Broadbent Capital")


# ── API Routes ──

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

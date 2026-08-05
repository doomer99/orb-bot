# router.py — Portfolio-driven order router
# Each portfolio = one broker + one strategy + risk config.
# The main loop iterates portfolios, not strategies.
import time, threading, json, os, pytz
from datetime import datetime, date
from typing import Dict, List, Optional
from brokers import TradierBroker, TradersPostBroker
from brokers.base import BaseBroker
from strategies.base import BaseStrategy, Signal
from config import BROKERS, SIM_MODE, DAILY_LOSS_LIMIT, DAILY_LOSS_BUFFER, DATA_DIR
from portfolio import Portfolio, load_portfolios, save_portfolios, get_asset_data

ET = pytz.timezone("America/New_York")
TRADES_FILE = os.path.join(DATA_DIR, "active_trades.json")


class Router:
    def __init__(self):
        self.brokers: Dict[str, BaseBroker] = {}
        self.strategies: Dict[str, BaseStrategy] = {}
        self.portfolios: Dict[str, Portfolio] = {}
        self.active_trades: Dict[str, dict] = {}
        self.log_lines: List[str] = []
        self.day_pnl: float = 0.0
        self._running = False
        self._circuit_breaker_active = False
        self._circuit_breaker_time = None

        # Load saved portfolios
        self.portfolios = load_portfolios()
        self._load_active_trades()

    # ── Logging ──
    def log(self, msg: str):
        ts = datetime.now(ET).strftime("%H:%M:%S")
        line = f"{ts} {msg}"
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-100:]
        print(line)

    # ── Active trades persistence ──
    def _load_active_trades(self):
        try:
            if os.path.exists(TRADES_FILE):
                with open(TRADES_FILE, "r") as f:
                    saved = json.load(f)
                for name, trade in saved.items():
                    if trade.get("status") in ("OPEN", "SIM"):
                        sig_data = trade.get("signal", {})
                        trade["signal"] = Signal(
                            direction=sig_data.get("direction", "UP"),
                            confidence=sig_data.get("confidence", 0.5),
                            symbol=sig_data.get("symbol", "SPY"),
                            quantity=sig_data.get("quantity", 1),
                        )
                        if "entry_time" in trade and isinstance(trade["entry_time"], str):
                            try:
                                trade["entry_time"] = datetime.fromisoformat(trade["entry_time"])
                            except Exception:
                                trade["entry_time"] = datetime.now(ET)
                        self.active_trades[name] = trade
                if self.active_trades:
                    print(f"Restored {len(self.active_trades)} active trade(s) from disk")
        except Exception as e:
            print(f"Could not load active trades: {e}")

    def _save_active_trades(self):
        try:
            to_save = {}
            for name, trade in self.active_trades.items():
                t = dict(trade)
                if hasattr(t.get("signal"), "direction"):
                    sig = t["signal"]
                    t["signal"] = {
                        "direction": sig.direction,
                        "confidence": sig.confidence,
                        "symbol": sig.symbol,
                        "quantity": sig.quantity,
                    }
                if hasattr(t.get("entry_time"), "isoformat"):
                    t["entry_time"] = t["entry_time"].isoformat()
                to_save[name] = t
            with open(TRADES_FILE, "w") as f:
                json.dump(to_save, f, indent=2)
        except Exception as e:
            print(f"Could not save active trades: {e}")

    # ── Circuit breaker ──
    def activate_circuit_breaker(self):
        self.log("CIRCUIT BREAKER ACTIVATED — closing all positions")
        self._circuit_breaker_active = True
        self._circuit_breaker_time = datetime.now(ET)
        for name in list(self.active_trades):
            trade = self.active_trades[name]
            if trade["status"] in ("OPEN", "SIM"):
                self.log(f"Emergency close: [{name}]")
                self._close_order(name)
        self.log("All orders blocked until re-authorization")

    def deactivate_circuit_breaker(self):
        self._circuit_breaker_active = False
        self._circuit_breaker_time = None
        self.log("Circuit breaker deactivated — trading resumed")

    @property
    def circuit_breaker_active(self) -> bool:
        return self._circuit_breaker_active

    # ── Brokers ──
    def _create_broker(self, broker_id: str, cfg: dict) -> BaseBroker:
        if cfg["type"] == "tradier":
            return TradierBroker(cfg.get("name", broker_id), cfg)
        elif cfg["type"] == "webhook":
            return TradersPostBroker(cfg.get("name", broker_id), cfg)
        else:
            raise ValueError(f"Unknown broker type: {cfg['type']}")

    def init_brokers(self):
        for broker_id, cfg in BROKERS.items():
            try:
                broker = self._create_broker(broker_id, cfg)
                connected = broker.connect()
                self.brokers[broker_id] = broker
                status = "connected" if connected else f"{broker.last_error}"
                self.log(f"Broker [{broker_id}] {cfg.get('name', '')}: {status}")
            except Exception as e:
                self.log(f"Broker [{broker_id}] error: {e}")

    def _get_broker(self, broker_id: str) -> Optional[BaseBroker]:
        return self.brokers.get(broker_id)

    # ── Strategies ──
    def register_strategy(self, strategy: BaseStrategy):
        self.strategies[strategy.name] = strategy
        # Enable strategy if any portfolio references it
        has_portfolio = any(
            p.strategy_name == strategy.name and p.enabled
            for p in self.portfolios.values()
        )
        strategy.enabled = has_portfolio
        self.log(f"Strategy [{strategy.name}]: {'enabled' if strategy.enabled else 'disabled (no portfolio)'}")

    def init_strategies(self):
        for name, strategy in self.strategies.items():
            if not strategy.enabled:
                continue
            try:
                self.log(f"Initializing [{name}]...")
                ok = strategy.initialize()
                self.log(f"[{name}] {'ready' if ok else 'init failed'}")
            except Exception as e:
                self.log(f"[{name}] init error: {e}")

    # ── Portfolio management ──
    def create_portfolio(self, name: str, broker: str, strategy: str,
                         symbol: str = "SPY", quantity: int = 1,
                         risk_pct: float = 1.0, max_daily_loss: float = 0) -> Portfolio:
        portfolio = Portfolio(name, {
            "broker": broker,
            "strategy": strategy,
            "symbol": symbol,
            "quantity": quantity,
            "risk_pct": risk_pct,
            "max_daily_loss": max_daily_loss,
            "enabled": True,
        })
        self.portfolios[name] = portfolio
        # Enable the strategy if it wasn't already
        if strategy in self.strategies:
            self.strategies[strategy].enabled = True
        save_portfolios(self.portfolios)
        self.log(f"Portfolio [{name}] created: {strategy} -> {broker} ({symbol})")
        return portfolio

    def delete_portfolio(self, name: str) -> bool:
        if name not in self.portfolios:
            return False
        # Close any active trade first
        if name in self.active_trades:
            self._close_order(name)
        del self.portfolios[name]
        save_portfolios(self.portfolios)
        self.log(f"Portfolio [{name}] deleted")
        return True

    # ── Orders ──
    def _get_equity(self, broker: BaseBroker) -> float:
        """Get account equity from broker, or 0 if unavailable."""
        if not broker:
            return 0
        try:
            info = broker.get_account_info()
            return info.equity or 0
        except Exception:
            return 0

    def _place_order(self, portfolio_name: str, signal: Signal) -> bool:
        """Place an order for a specific portfolio."""
        if self._circuit_breaker_active:
            self.log(f"[{portfolio_name}] blocked — circuit breaker active")
            return False

        portfolio = self.portfolios.get(portfolio_name)
        if not portfolio:
            self.log(f"[{portfolio_name}] portfolio not found")
            return False

        broker = self._get_broker(portfolio.broker_id)
        symbol = portfolio.symbol
        equity = self._get_equity(broker)

        # Dynamic sizing from equity + risk, or fallback to static quantity
        if equity > 0:
            asset_data = get_asset_data([symbol])
            quantity = portfolio.calculate_quantity(equity, asset_data)
            self.log(f"[{portfolio_name}] sized: {quantity}x {symbol} "
                     f"(equity=${equity:,.0f}, risk={portfolio.risk_pct}%)")
        else:
            quantity = portfolio.quantity
            self.log(f"[{portfolio_name}] static: {quantity}x {symbol} (no equity data)")

        # Check portfolio-level risk
        if not portfolio.risk_ok(equity):
            self.log(f"[{portfolio_name}] blocked — daily loss limit reached")
            return False

        # SIM mode
        if SIM_MODE:
            self.log(f"[SIM] {portfolio_name} -> {signal.direction} "
                     f"{quantity}x {symbol} (conf={signal.confidence:.1%})")
            self.active_trades[portfolio_name] = {
                "signal": signal, "entry_time": datetime.now(ET),
                "status": "SIM", "quantity": quantity, "symbol": symbol,
            }
            self._save_active_trades()
            return True

        # Live order
        if not broker:
            self.log(f"[{portfolio_name}] no broker '{portfolio.broker_id}' available")
            return False
        if not broker.is_connected:
            self.log(f"[{portfolio_name}] broker not connected")
            return False

        self.log(f"[ORDER] {portfolio_name} -> {broker.name}: "
                 f"{signal.direction} {quantity}x {symbol}")
        result = broker.place_order(
            direction=signal.direction, symbol=symbol, quantity=quantity
        )

        if result.success:
            self.log(f"[{portfolio_name}] filled: {result.message}")
            self.active_trades[portfolio_name] = {
                "signal": signal, "entry_time": datetime.now(ET),
                "order_id": result.order_id, "occ_symbol": result.symbol,
                "status": "OPEN", "quantity": quantity, "symbol": symbol,
            }
            self._save_active_trades()
        else:
            self.log(f"[{portfolio_name}] FAILED: {result.message}")
        return result.success

    def _close_order(self, portfolio_name: str) -> bool:
        """Close an active trade for a portfolio."""
        trade = self.active_trades.get(portfolio_name)
        if not trade:
            return False

        portfolio = self.portfolios.get(portfolio_name)
        if not portfolio:
            # Portfolio was deleted but trade still open — try to close anyway
            self.log(f"[{portfolio_name}] orphan trade — marking closed")
            trade["status"] = "CLOSED"
            self._save_active_trades()
            return True

        broker = self._get_broker(portfolio.broker_id)
        symbol = trade.get("symbol", portfolio.symbol)
        quantity = trade.get("quantity", portfolio.quantity)

        if SIM_MODE:
            self.log(f"[SIM] {portfolio_name} closed")
            trade["status"] = "CLOSED"
            self._save_active_trades()
            return True

        if not broker:
            self.log(f"[{portfolio_name}] no broker for close")
            return False

        result = broker.close_position(
            symbol=symbol, quantity=quantity,
            direction=trade["signal"].direction,
            occ_symbol=trade.get("occ_symbol"),
        )
        if result.success:
            self.log(f"[{portfolio_name}] closed: {result.message}")
            trade["status"] = "CLOSED"
            self._save_active_trades()
        else:
            self.log(f"[{portfolio_name}] close failed: {result.message}")
        return result.success

    # ── Global risk ──
    def risk_ok(self) -> bool:
        loss = -min(0.0, self.day_pnl)
        remaining = DAILY_LOSS_LIMIT - loss
        if remaining < DAILY_LOSS_BUFFER:
            self.log(f"Daily loss guard: ${remaining:.0f} remaining")
            return False
        return True

    # ── Main loop ──
    def run(self):
        self._running = True
        mode = "SIM" if SIM_MODE else "LIVE"
        self.log("=" * 58)
        self.log(f"Trading Command Center — mode={mode}")
        self.log(f"Brokers: {len(BROKERS)} | Strategies: {len(self.strategies)} "
                 f"| Portfolios: {len(self.portfolios)}")
        self.log("=" * 58)

        self.init_brokers()
        self.init_strategies()

        # Log portfolio config
        for name, p in self.portfolios.items():
            status = "enabled" if p.enabled else "disabled"
            self.log(f"Portfolio [{name}]: {p.strategy_name} -> "
                     f"{p.broker_id} ({p.symbol}) [{status}]")

        last_reset = None

        while self._running:
            now = datetime.now(ET)
            today = now.date()

            # Circuit breaker — sleep and skip
            if self._circuit_breaker_active:
                time.sleep(10)
                continue

            # Midnight reset
            if now.hour == 0 and now.minute < 5 and last_reset != today:
                self.log("Midnight — resetting all portfolios and strategies")
                self.day_pnl = 0.0
                self.active_trades.clear()
                self._save_active_trades()
                for strategy in self.strategies.values():
                    strategy.reset_daily()
                for portfolio in self.portfolios.values():
                    portfolio.reset_daily()
                self.init_strategies()
                last_reset = today
                time.sleep(60)
                continue

            # Weekend — sleep
            if now.weekday() >= 5:
                time.sleep(300)
                continue

            # Pre-market — sleep
            if now.hour < 9:
                time.sleep(30)
                continue

            # Noon hard stop — close everything
            if now.hour >= 12:
                for name in list(self.active_trades):
                    if self.active_trades[name]["status"] in ("OPEN", "SIM"):
                        self.log(f"Noon hard stop — closing [{name}]")
                        self._close_order(name)
                time.sleep(60)
                continue

            # ── Main portfolio loop ──
            for port_name, portfolio in self.portfolios.items():
                if not portfolio.enabled:
                    continue

                # Get the strategy for this portfolio
                strategy = self.strategies.get(portfolio.strategy_name)
                if not strategy or not strategy.is_ready:
                    continue

                # Check trading window
                win_start, win_end = strategy.get_trading_window()
                current_time = now.time()

                # Handle active trades (exit checks)
                if port_name in self.active_trades:
                    trade = self.active_trades[port_name]
                    if trade["status"] in ("OPEN", "SIM"):
                        if strategy.should_exit(now, 0, 0, trade["signal"].direction):
                            self.log(f"Exit signal — [{port_name}]")
                            self._close_order(port_name)
                            strategy.record_trade(trade["signal"], "CLOSED")
                    continue  # already in a trade or just closed, skip to next

                # Not in a trade — check for new signal
                if portfolio.today_traded:
                    continue
                if not (win_start <= current_time <= win_end):
                    continue
                if not self.risk_ok():
                    continue

                try:
                    signal = strategy.check_signal(now)
                    if signal:
                        self.log(f"[{port_name}] signal: {signal.direction} "
                                 f"({signal.confidence:.1%})")
                        success = self._place_order(port_name, signal)
                        # Mark this portfolio as traded today regardless of success
                        # so we don't spam retries
                        portfolio.today_traded = True
                except Exception as e:
                    self.log(f"[{port_name}] signal error: {e}")

            time.sleep(10)

    # ── Dashboard state ──
    def get_state(self) -> dict:
        broker_states = {}
        for bid, broker in self.brokers.items():
            try:
                info = broker.get_account_info()
                broker_states[bid] = {
                    "name": broker.name, "type": broker.broker_type,
                    "connected": broker.is_connected,
                    "equity": info.equity, "cash": info.cash,
                    "day_pnl": info.day_pnl,
                    "positions": [p.__dict__ for p in info.positions],
                    "error": info.error,
                }
            except Exception as e:
                broker_states[bid] = {"name": broker.name, "connected": False, "error": str(e)}

        strategy_states = {}
        for name, strategy in self.strategies.items():
            strategy_states[name] = strategy.to_dict()

        portfolio_states = {}
        for name, portfolio in self.portfolios.items():
            p = portfolio.to_dict()
            p["today_traded"] = portfolio.today_traded
            trade = self.active_trades.get(name)
            if trade:
                p["active_trade"] = {
                    "direction": trade["signal"].direction,
                    "confidence": trade["signal"].confidence,
                    "entry_time": trade["entry_time"].strftime("%H:%M:%S")
                        if hasattr(trade["entry_time"], "strftime") else str(trade["entry_time"]),
                    "status": trade["status"],
                    "symbol": trade.get("symbol", portfolio.symbol),
                    "quantity": trade.get("quantity", portfolio.quantity),
                }
            portfolio_states[name] = p

        return {
            "sim_mode": SIM_MODE,
            "circuit_breaker": self._circuit_breaker_active,
            "circuit_breaker_time": self._circuit_breaker_time.strftime("%H:%M:%S")
                if self._circuit_breaker_time else None,
            "brokers": broker_states,
            "strategies": strategy_states,
            "portfolios": portfolio_states,
            "active_trades": {
                k: {
                    "direction": v["signal"].direction,
                    "status": v["status"],
                    "symbol": v.get("symbol", "SPY"),
                    "quantity": v.get("quantity", 1),
                }
                for k, v in self.active_trades.items()
            },
            "log": self.log_lines,
            "day_pnl": self.day_pnl,
        }

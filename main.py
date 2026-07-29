# main.py — Entry point for the Trading Command Center
# Starts the router, registers strategies, launches dashboard

import threading
from router import Router
from strategies.nour import NourStrategy

# ══════════════════════════════════════════════════════════════
#  BUILD THE SYSTEM
# ══════════════════════════════════════════════════════════════

router = Router()

# Register all strategies
router.register_strategy(NourStrategy())

# Future strategies — uncomment when ready:
# from strategies.stochastic import StochasticStrategy
# router.register_strategy(StochasticStrategy())
#
# from strategies.trend_flip import TrendFlipStrategy
# router.register_strategy(TrendFlipStrategy())

# ══════════════════════════════════════════════════════════════
#  START
# ══════════════════════════════════════════════════════════════

# Run the trading loop in a background thread
threading.Thread(target=router.run, daemon=True).start()

# The dashboard (dashboard.py) imports `router` from this file
# and reads router.get_state() to render the UI

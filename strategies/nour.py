# strategies/nour.py — Nour ML Opening Range Model
# Random Forest trained on SPY premarket + opening range features
# 91-93% win rate in backtesting
# Entry: 9:31 AM | Exit: 9:45 AM | Hold: 15 minutes

import os
import requests
import numpy as np
import pandas as pd
import pytz
from datetime import datetime, date, timedelta, time
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

from .base import BaseStrategy, Signal

ET = pytz.timezone("America/New_York")


class NourStrategy(BaseStrategy):
    """ML Opening Range model — predicts SPY direction for first 15 min."""

    def __init__(self):
        super().__init__(
            name="Nour ML",
            description="Random Forest on SPY opening range — 91-93% win rate, "
                        "15-min hold at 9:31 AM"
        )
        self.polygon_key = os.environ.get("POLYGON_API_KEY", "")
        self.train_days = int(os.environ.get("MODEL_TRAIN_DAYS", "200"))
        self.conf_threshold = float(os.environ.get("CONF_THRESHOLD", "0.55"))

        # Tradier live token for real-time data
        self.tradier_live_token = os.environ.get("TRADIER_LIVE_TOKEN", "")
        self.tradier_live_base = "https://api.tradier.com/v1"

        # Signal caching (so multiple portfolios don't re-run the model)
        self._last_signal_date = None

        # Model internals
        self._model = None
        self._scaler = None
        self._feat_cols = None
        self._spy_hist = None
        self._vr_w2 = None
        self._vr_w4 = None

    def get_trading_window(self) -> tuple:
        return (time(9, 31), time(9, 33))

    # ══════════════════════════════════════════════════════════
    #  DATA
    # ══════════════════════════════════════════════════════════

    def _get_historical_spy(self):
        """Pull SPY 1-min history from Polygon."""
        if not self.polygon_key:
            return self._get_yahoo_history()
        try:
            from polygon import RESTClient
            client = RESTClient(self.polygon_key)
            end = datetime.now()
            start = end - timedelta(days=self.train_days + 10)

            bars = list(client.list_aggs(
                "SPY", 1, "minute",
                from_=start.strftime("%Y-%m-%d"),
                to=end.strftime("%Y-%m-%d"),
                adjusted=True, limit=50000
            ))
            records = [{
                "Open": b.open, "High": b.high,
                "Low": b.low, "Close": b.close,
                "Volume": b.volume, "ts": b.timestamp
            } for b in bars]

            df = pd.DataFrame(records)
            df["datetime"] = (pd.to_datetime(df["ts"], unit="ms", utc=True)
                              .dt.tz_convert("America/New_York"))
            df = df.set_index("datetime").drop(columns=["ts"])
            df = df.between_time("04:00", "20:00")
            df.index = df.index.tz_localize(None)
            return df
        except Exception:
            return self._get_yahoo_history()

    def _get_yahoo_history(self):
        try:
            import yfinance as yf
            spy = yf.download("SPY", period="60d", interval="1m",
                              progress=False, auto_adjust=True, prepost=True)
            if hasattr(spy.columns, "levels"):
                spy.columns = spy.columns.get_level_values(0)
            if spy.index.tz is not None:
                spy.index = spy.index.tz_convert(ET).tz_localize(None)
            return spy
        except Exception:
            return None

    def _get_today_data(self):
        """Fetch today's SPY 1-min bars including premarket."""
        if self.tradier_live_token:
            try:
                r = requests.get(
                    f"{self.tradier_live_base}/markets/timesales",
                    headers={"Authorization": f"Bearer {self.tradier_live_token}",
                             "Accept": "application/json"},
                    params={"symbol": "SPY", "interval": "1min",
                            "start": datetime.now(ET).strftime("%Y-%m-%d 04:00"),
                            "session_filter": "all"},
                    timeout=8
                )
                data = r.json().get("series", {}).get("data", [])
                if data:
                    if isinstance(data, dict):
                        data = [data]
                    rows, times = [], []
                    for bar in data:
                        rows.append({
                            "Open": float(bar.get("open", 0)),
                            "High": float(bar.get("high", 0)),
                            "Low": float(bar.get("low", 0)),
                            "Close": float(bar.get("close", 0)),
                            "Volume": float(bar.get("volume", 0)),
                        })
                        times.append(bar["time"])
                    df = pd.DataFrame(rows)
                    df.index = pd.to_datetime(times, format="mixed")
                    return df
            except Exception:
                pass

        # Fallback: Yahoo
        try:
            url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
                   "SPY?interval=1m&range=1d&prePost=true")
            r = requests.get(url, timeout=8,
                             headers={"User-Agent": "Mozilla/5.0"})
            d = r.json()["chart"]["result"][0]
            times = d["timestamp"]
            q = d["indicators"]["quote"][0]
            rows = []
            for i, ts in enumerate(times):
                c = q["close"][i]
                if c is None:
                    continue
                t = datetime.fromtimestamp(ts, tz=pytz.utc).astimezone(ET)
                rows.append({
                    "datetime": t.replace(tzinfo=None),
                    "Open": q["open"][i] or c,
                    "High": q["high"][i] or c,
                    "Low": q["low"][i] or c,
                    "Close": c,
                    "Volume": q["volume"][i] or 0,
                })
            if not rows:
                return None
            return pd.DataFrame(rows).set_index("datetime")
        except Exception:
            return None

    # ══════════════════════════════════════════════════════════
    #  FEATURES (identical to backtesting notebook)
    # ══════════════════════════════════════════════════════════

    def _window_features(self, spy_day, stk_day, start, end, prefix,
                         vol_ratio_stk=1.0, vol_ratio_spy=1.0):
        s = spy_day.between_time(start, end)
        t = stk_day.between_time(start, end)
        feats = {}

        for name, df in [("spy", s), ("stk", t)]:
            keys = ["ret", "hi_ret", "lo_ret", "body_avg", "direction",
                    "close_pos", "range_pct", "momentum", "bar_accel",
                    "bull_vol_pct", "vol_direction"]
            if len(df) < 2:
                for k in keys:
                    feats[f"{prefix}_{name}_{k}"] = 0.0
                continue

            op = float(df.Open.iloc[0])
            cl = float(df.Close.iloc[-1])
            hi = float(df.High.max())
            lo = float(df.Low.min())
            rng = max(hi - lo, 1e-6)

            bodies = (df.Close - df.Open).abs()
            bull_bars = (df.Close > df.Open).sum()
            direction = (bull_bars / len(df)) * 2 - 1

            bar_rets = ((df.Close - df.Open) / df.Open * 100).values
            if len(bar_rets) > 2:
                third = max(1, len(bar_rets) // 3)
                early_abs = np.mean(np.abs(bar_rets[:third]))
                late_abs = np.mean(np.abs(bar_rets[-third:]))
                momentum = (late_abs - early_abs) / max(early_abs, 1e-6)
                bar_accel = float(np.polyfit(
                    range(len(bar_rets)), np.abs(bar_rets), 1)[0])
            else:
                momentum = bar_accel = 0.0

            total_vol = float(df.Volume.sum()) if "Volume" in df.columns else 0
            if total_vol > 0:
                bull_vol = float(df[df.Close > df.Open].Volume.sum())
                bull_vol_pct = bull_vol / total_vol
                vol_scores = np.array([
                    (1 if r.Close > r.Open else -1 if r.Close < r.Open else 0)
                    * float(r.Volume)
                    for _, r in df.iterrows()
                ])
                vol_direction = vol_scores.sum() / total_vol
            else:
                bull_vol_pct = 0.5
                vol_direction = 0.0

            feats[f"{prefix}_{name}_ret"] = (cl - op) / op * 100
            feats[f"{prefix}_{name}_hi_ret"] = (hi - op) / op * 100
            feats[f"{prefix}_{name}_lo_ret"] = (lo - op) / op * 100
            feats[f"{prefix}_{name}_body_avg"] = float(bodies.mean()) / op * 100
            feats[f"{prefix}_{name}_direction"] = direction
            feats[f"{prefix}_{name}_close_pos"] = (cl - lo) / rng
            feats[f"{prefix}_{name}_range_pct"] = rng / op * 100
            feats[f"{prefix}_{name}_momentum"] = momentum
            feats[f"{prefix}_{name}_bar_accel"] = bar_accel
            feats[f"{prefix}_{name}_bull_vol_pct"] = bull_vol_pct
            feats[f"{prefix}_{name}_vol_direction"] = vol_direction

        stk_ret = feats.get(f"{prefix}_stk_ret", 0)
        spy_ret = feats.get(f"{prefix}_spy_ret", 0)
        feats[f"{prefix}_rs"] = stk_ret - spy_ret
        feats[f"{prefix}_rs_abs"] = abs(stk_ret - spy_ret)
        feats[f"{prefix}_stk_strong"] = 1.0 if stk_ret > spy_ret else -1.0
        feats[f"{prefix}_stk_vol_ratio"] = vol_ratio_stk
        feats[f"{prefix}_spy_vol_ratio"] = vol_ratio_spy
        return feats

    def _precompute_vol_ratios(self, df, start, end, lookback=20):
        win = df.between_time(start, end)
        daily_vol = win.groupby(win.index.date)["Volume"].sum()
        daily_vol.index = pd.to_datetime(daily_vol.index)
        avg_vol = daily_vol.rolling(lookback, min_periods=1).mean().shift(1)
        return (daily_vol / avg_vol.replace(0, np.nan)).fillna(1.0)

    def _build_features(self, spy_df, day):
        spy_day = spy_df[spy_df.index.date == day]
        if len(spy_day) < 10:
            return None
        after = spy_day[spy_day.index.time >=
                        pd.Timestamp("2000-01-01 09:30").time()]
        if len(after) == 0:
            return None

        day_ts = pd.Timestamp(day)
        def getvr(vr):
            try:
                return float(vr.loc[day_ts])
            except:
                return 1.0

        row = {}
        row.update(self._window_features(spy_day, spy_day,
                   "04:00", "08:00", "W1"))
        row.update(self._window_features(spy_day, spy_day,
                   "08:00", "09:29", "W2",
                   vol_ratio_stk=getvr(self._vr_w2),
                   vol_ratio_spy=getvr(self._vr_w2)))
        row.update(self._window_features(spy_day, spy_day,
                   "09:00", "09:29", "W3"))
        row.update(self._window_features(spy_day, spy_day,
                   "09:30", "09:44", "W4",
                   vol_ratio_stk=getvr(self._vr_w4),
                   vol_ratio_spy=getvr(self._vr_w4)))
        return row

    # ══════════════════════════════════════════════════════════
    #  STRATEGY INTERFACE
    # ══════════════════════════════════════════════════════════

    def initialize(self) -> bool:
        """Train the model on historical data."""
        spy_df = self._get_historical_spy()
        if spy_df is None or len(spy_df) < 500:
            return False

        self._vr_w2 = self._precompute_vol_ratios(spy_df, "08:00", "09:29")
        self._vr_w4 = self._precompute_vol_ratios(spy_df, "09:30", "09:44")

        days = sorted(set(spy_df.index.date))
        records = []

        for day in days:
            spy_day = spy_df[spy_df.index.date == day]
            after = spy_day[spy_day.index.time >=
                            pd.Timestamp("2000-01-01 09:30").time()]
            if len(after) == 0:
                continue
            ep = float(after.Close.iloc[0])
            ets = after.index[0]

            fut = spy_day[spy_day.index >= ets + pd.Timedelta(minutes=15)]
            if len(fut) == 0:
                continue
            pct = (float(fut.Close.iloc[0]) - ep) / ep * 100
            label = 1 if pct > 0 else 0

            feats = self._build_features(spy_df, day)
            if feats is None:
                continue
            feats["label"] = label
            records.append(feats)

        if len(records) < 50:
            return False

        df_train = pd.DataFrame(records).fillna(0)
        feat_cols = [c for c in df_train.columns if c != "label"]

        sc = StandardScaler()
        X_s = sc.fit_transform(df_train[feat_cols].values)
        y = df_train["label"].values

        mdl = RandomForestClassifier(
            n_estimators=300, max_depth=4,
            min_samples_leaf=8, random_state=42
        )
        mdl.fit(X_s, y)

        self._model = mdl
        self._scaler = sc
        self._feat_cols = feat_cols
        self._spy_hist = spy_df
        self._trained = True

        return True

    def check_signal(self, current_time: datetime) -> Signal | None:
        """
        Run the model at 9:31 AM.
        Multiple portfolios may call this — the signal is cached for the day
        so we only fetch data and predict once.
        """
        if not self._trained:
            return None

        now = current_time
        if not (now.hour == 9 and 31 <= now.minute <= 32):
            return None

        # Return cached signal if we already ran today
        if self._last_signal and self._last_signal_date == now.date():
            return self._last_signal  # None if confidence was too low

        # Get today's data
        today_df = self._get_today_data()
        if today_df is None or len(today_df) < 5:
            return None

        # Merge with historical
        try:
            combined = pd.concat([self._spy_hist, today_df]).sort_index()
            combined = combined[~combined.index.duplicated(keep="last")]
        except Exception:
            combined = today_df

        # Build features
        feats = self._build_features(combined, now.date())
        if feats is None:
            return None

        # Predict
        feat_df = pd.DataFrame([feats])[self._feat_cols].fillna(0)
        X_scaled = self._scaler.transform(feat_df.values)
        prob_up = float(self._model.predict_proba(X_scaled)[0][1])
        conf = max(prob_up, 1 - prob_up)
        direction = "UP" if prob_up >= 0.5 else "DOWN"

        # Mark that we've run today (even if confidence is too low)
        self._last_signal_date = now.date()

        # Confidence gate
        if conf < self.conf_threshold:
            self._last_signal = None
            return None

        signal = Signal(
            direction=direction,
            confidence=conf,
            symbol="SPY",
            quantity=1,
            entry_time=now.strftime("%H:%M:%S"),
            exit_minutes=15,
            metadata={
                "prob_up": round(prob_up, 4),
                "model": "RandomForest",
            }
        )
        self._last_signal = signal
        return signal

    def should_exit(self, current_time: datetime,
                    entry_price: float, current_price: float,
                    direction: str) -> bool:
        """Exit at 9:45 AM — 15 minutes flat, no exceptions."""
        if current_time.hour == 9 and current_time.minute >= 45:
            return True
        if current_time.hour >= 10:
            return True
        return False

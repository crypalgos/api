import logging
from typing import List

import numpy as np
from crypalgos_core.engine.strategy_base import StrategyBase
from crypalgos_core.indicators.base import BaseIndicator

logger = logging.getLogger(__name__)

# Bounded rolling window for the in-memory candle history this warmup
# recomputes indicators over on every live bar (the "periodic recompute"
# design chosen for live/paper trading -- see plan Phase 1.5 notes).
# Matches SeriesBuffer's own max_history=1000 cap: no indicator can see
# further back than that anyway, so retaining more here would be pure waste.
MAX_HISTORY_BARS = 1000


def discover_indicators(strategy: StrategyBase) -> List[BaseIndicator]:
    """Reflectively finds every BaseIndicator instance a compiled strategy's
    initialize() set as a plain attribute (self.ema_btcusd = Indicator.EMA(...)).
    Compiled strategies have no explicit indicator registry -- this is the
    same dir()/isinstance scan engine/simulator.py uses for backtest, so live
    and backtest discover indicators identically.
    """
    indicators: List[BaseIndicator] = []
    for attr_name in dir(strategy):
        try:
            attr_val = getattr(strategy, attr_name, None)
        except Exception:
            continue
        if isinstance(attr_val, BaseIndicator):
            attr_val.name = attr_name
            indicators.append(attr_val)
    return indicators


def _compute_one(indicator: BaseIndicator, candles: np.ndarray) -> None:
    """Same close-only-then-full-OHLCV retry pattern as
    engine/simulator.py's indicator precompute step (audit finding #56) --
    most indicators take close prices only; ATR/BollingerBands need the
    full OHLCV array. Raises (does not silently continue) on a genuine
    failure, matching #56's fixed behavior rather than the bug it replaced.
    """
    try:
        indicator.compute(candles[:, 4])
    except Exception:
        indicator.compute(candles)


class IndicatorWarmup:
    """Owns the growing (bounded) in-memory candle history for one live
    session and keeps every discovered indicator's buffer in sync with it.

    Backtest precomputes each indicator once over the full historical
    array, then reveals one more value per bar via update_step(). Live
    trading has no such bounded array up front -- this seeds from a
    ClickHouse history fetch (done once, at bootstrap -- see
    RuntimeFactory.build()), then on every new live bar, recomputes each
    indicator over the whole retained window and calls update_step() for
    just the newest index (#23's staleness tracking makes re-calling
    update_step() for already-seen indices a safe no-op, so recompute-and-
    replay-the-tail is correct, just not the most efficient possible
    design -- chosen deliberately over a bigger, riskier change to
    crypalgos_core's indicator internals).
    """

    def __init__(self, indicators: List[BaseIndicator]) -> None:
        self.indicators = indicators
        self._candles: List[np.ndarray] = []

    def seed(self, candles: np.ndarray | list[list[float]]) -> None:
        """Seed indicators from canonical historical OHLCV rows.

        ClickHouse provides a NumPy array while Delta Testnet REST provides a
        list of rows. Normalize both at this boundary before inspecting array
        metadata or stacking rows for indicator computation.
        """
        candle_arr = np.asarray(candles, dtype=np.float64)
        if candle_arr.size == 0:
            logger.warning(
                "IndicatorWarmup.seed() called with zero candles -- "
                "indicators will start cold and reject conditions until "
                "enough live bars accumulate."
            )
            return
        trimmed = candle_arr[-MAX_HISTORY_BARS:]
        self._candles = list(trimmed)
        candle_arr = np.stack(self._candles)
        for indicator in self.indicators:
            if not self._safe_compute(indicator, candle_arr):
                continue
            # Full replay, not just the last index: SeriesBuffer.append() has
            # no notion of "this index was already appended" -- update_step()
            # unconditionally appends whenever the computed value at that
            # index isn't NaN. Seeding must walk every historical index once
            # so the buffer actually has depth (e.g. .value[1] for a
            # one-bar-back comparison) before the first live bar arrives;
            # on_new_bar() below relies on that having already happened and
            # only ever advances by exactly one new, never-before-seen index
            # per call, which is what makes update_step() safe to call there
            # without re-triggering this same duplicate-append risk.
            for k in range(len(candle_arr)):
                indicator.update_step(k)
        logger.info(
            "IndicatorWarmup seeded %d indicator(s) with %d historical bars",
            len(self.indicators),
            len(self._candles),
        )

    def on_new_bar(self, candle_row: List[float]) -> None:
        """Called by TradingRuntime.tick() for every live bar, before the
        strategy's on_event() runs. Only ever advances by exactly one new
        index relative to the last call -- see seed()'s docstring above for
        why that's what makes a single update_step() call safe here."""
        if not self._candles:
            logger.warning(
                "IndicatorWarmup.on_new_bar() called before seed() -- "
                "indicators have no history yet."
            )
        self._candles.append(np.asarray(candle_row, dtype=np.float64))
        if len(self._candles) > MAX_HISTORY_BARS:
            self._candles = self._candles[-MAX_HISTORY_BARS:]
        if not self.indicators:
            return
        candle_arr = np.stack(self._candles)
        last_index = len(candle_arr) - 1
        for indicator in self.indicators:
            if self._safe_compute(indicator, candle_arr):
                indicator.update_step(last_index)

    def _safe_compute(self, indicator: BaseIndicator, candle_arr: np.ndarray) -> bool:
        try:
            _compute_one(indicator, candle_arr)
            return True
        except Exception:
            logger.exception(
                "IndicatorWarmup: %s failed to compute over %d bars",
                getattr(indicator, "name", indicator.__class__.__name__),
                len(candle_arr),
            )
            return False

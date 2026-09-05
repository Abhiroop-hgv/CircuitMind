"""
The forecasting tool.

This is a plain statistical model, called as a tool. No language model touches
any of these numbers -- asking one to extrapolate a time series is the shortest
path to a hallucinated quantity on a purchase order.

Holt-Winters exponential smoothing: level, trend, and a yearly seasonal term.
Chosen because the data suits it -- 24 monthly observations with a clear upward
trend and a repeating annual shape. ARIMA needs more history to identify orders
reliably; a gradient-boosted model needs features we do not have and would
overfit 24 points cheerfully.

Twenty-four months is exactly two seasonal cycles, which is the documented
minimum for fitting a seasonal term. It fits, but it is thin, and the code says
so rather than presenting the interval as tighter than it is.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing

SEASONAL_PERIODS = 12
MIN_FOR_SEASONAL = 24


@dataclass
class Forecast:
    method: str
    points: List[int]           # forecast per future period
    lower: List[int]            # ~80% interval, from in-sample residuals
    upper: List[int]
    fitted_rmse: float
    history_points: int
    caveat: str = ""


def forecast(history: List[float], periods: int) -> Forecast:
    """
    history: one value per month, oldest first, no gaps.
    periods: how many months ahead to predict.
    """
    series = np.asarray([float(x) for x in history], dtype=float)

    if len(series) < 6:
        # Not enough to fit anything honest. Say so rather than produce a
        # number with a confident-looking interval around it.
        flat = float(series.mean()) if len(series) else 0.0
        return Forecast(
            method="mean (insufficient history)",
            points=[int(round(flat))] * periods,
            lower=[int(round(flat * 0.7))] * periods,
            upper=[int(round(flat * 1.3))] * periods,
            fitted_rmse=0.0,
            history_points=len(series),
            caveat="fewer than 6 observations -- this is an average, not a forecast",
        )

    seasonal = len(series) >= MIN_FOR_SEASONAL
    caveat = ""
    if seasonal and len(series) < MIN_FOR_SEASONAL + SEASONAL_PERIODS:
        caveat = (f"only {len(series)} months of history -- two seasonal cycles is the "
                  f"minimum for a yearly term, so the seasonal shape is thinly evidenced")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # statsmodels is chatty about short series
        model = ExponentialSmoothing(
            series,
            trend="add",
            seasonal="add" if seasonal else None,
            seasonal_periods=SEASONAL_PERIODS if seasonal else None,
            initialization_method="estimated",
        ).fit(optimized=True)

        predicted = np.asarray(model.forecast(periods), dtype=float)
        residuals = series - np.asarray(model.fittedvalues, dtype=float)

    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    band = 1.28 * rmse  # ~80%, and widening with horizon below

    points, lower, upper = [], [], []
    for step, value in enumerate(predicted, start=1):
        value = max(0.0, float(value))
        spread = band * np.sqrt(step)  # uncertainty grows the further out we look
        points.append(int(round(value)))
        lower.append(int(round(max(0.0, value - spread))))
        upper.append(int(round(value + spread)))

    return Forecast(
        method="Holt-Winters" + (" (additive trend + yearly seasonal)" if seasonal
                                 else " (additive trend, no seasonal)"),
        points=points, lower=lower, upper=upper,
        fitted_rmse=round(rmse, 1),
        history_points=len(series),
        caveat=caveat,
    )

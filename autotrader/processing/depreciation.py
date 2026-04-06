"""Depreciation predictor - projects future values based on price history and market data."""

import logging
from datetime import datetime, timezone
from statistics import mean

from autotrader.config import AVERAGE_ANNUAL_MILEAGE, get_mileage_band
from autotrader.storage.database import get_db, get_listing, get_market_stats

logger = logging.getLogger(__name__)

# Average annual depreciation rates by age bracket (year 1 is steepest)
# Based on typical UK used car depreciation curves
DEPRECIATION_CURVES = {
    # age_years: annual_depreciation_percent
    1: 0.25,  # 25% in year 1
    2: 0.15,  # 15% in year 2
    3: 0.12,  # 12% in year 3
    4: 0.10,
    5: 0.08,
    6: 0.07,
    7: 0.06,
    8: 0.05,
    9: 0.05,
    10: 0.04,
}
DEFAULT_ANNUAL_DEPRECIATION = 0.04  # 4% for 10+ year old cars


def _get_depreciation_rate(age_years: int) -> float:
    """Get the expected annual depreciation rate for a car of given age."""
    return DEPRECIATION_CURVES.get(age_years, DEFAULT_ANNUAL_DEPRECIATION)


def predict_depreciation(
    listing_id: str | None = None,
    current_price: int | None = None,
    make: str | None = None,
    model: str | None = None,
    year: int | None = None,
    mileage: int | None = None,
    months_ahead: list[int] | None = None,
) -> dict:
    """Predict future value of a vehicle.

    Can either take a listing_id to look up from DB, or raw values.

    Args:
        listing_id: Look up listing from DB.
        current_price: Current asking price.
        make: Vehicle make.
        model: Vehicle model.
        year: Registration year.
        mileage: Current mileage.
        months_ahead: List of months to predict (default: [3, 6, 12, 24]).

    Returns:
        Dict with predictions, depreciation curve, and confidence level.
    """
    if months_ahead is None:
        months_ahead = [3, 6, 12, 24]

    # Load from DB if listing_id provided
    if listing_id:
        listing = get_listing(listing_id)
        if listing:
            current_price = current_price or listing.get("price")
            make = make or listing.get("make")
            model = model or listing.get("model")
            year = year or listing.get("year")
            mileage = mileage or listing.get("mileage")

    if not current_price or not year:
        return {"error": "Need at least current_price and year"}

    current_year = datetime.now(timezone.utc).year
    age = max(current_year - year, 0)

    # Check if we have market data for better predictions
    market_stats = []
    confidence = "low"
    if make and model:
        market_stats = get_market_stats(make, model)
        if market_stats:
            total_samples = sum(s.get("sample_count", 0) for s in market_stats)
            if total_samples >= 20:
                confidence = "high"
            elif total_samples >= 5:
                confidence = "medium"

    # Try to compute empirical depreciation from market data
    empirical_rate = _compute_empirical_rate(market_stats, year, current_price)

    predictions = []
    for months in sorted(months_ahead):
        years_ahead = months / 12.0
        future_age = age + years_ahead

        # Compute cumulative depreciation
        remaining_value = float(current_price)
        month_step = 0
        while month_step < months:
            step_age = age + (month_step / 12.0)
            annual_rate = empirical_rate or _get_depreciation_rate(int(step_age) + 1)
            monthly_rate = annual_rate / 12.0
            remaining_value *= (1 - monthly_rate)
            month_step += 1

        predicted_price = max(int(remaining_value), 500)  # Floor at £500
        total_depreciation = current_price - predicted_price
        monthly_cost = total_depreciation / months if months > 0 else 0

        # Estimated future mileage
        future_mileage = None
        if mileage is not None:
            future_mileage = mileage + int(AVERAGE_ANNUAL_MILEAGE * (months / 12.0))

        predictions.append({
            "months": months,
            "predicted_price": predicted_price,
            "depreciation_amount": total_depreciation,
            "depreciation_percent": round((total_depreciation / current_price) * 100, 1),
            "monthly_cost": round(monthly_cost, 2),
            "estimated_mileage": future_mileage,
        })

    return {
        "current_price": current_price,
        "make": make,
        "model": model,
        "year": year,
        "age": age,
        "mileage": mileage,
        "confidence": confidence,
        "depreciation_rate_used": round(
            (empirical_rate or _get_depreciation_rate(age + 1)) * 100, 1
        ),
        "predictions": predictions,
    }


def _compute_empirical_rate(
    market_stats: list[dict], year: int | None, current_price: int
) -> float | None:
    """Try to compute empirical depreciation from market data across years.

    If we have data for the same model across multiple years, we can
    estimate the actual depreciation rate from real market prices.
    """
    if not market_stats or not year:
        return None

    # Get median prices by year
    year_prices = {}
    for stat in market_stats:
        y = stat.get("year")
        if y and stat.get("median_price"):
            year_prices.setdefault(y, []).append(stat["median_price"])

    if len(year_prices) < 2:
        return None

    # Average the medians per year
    year_avg = {y: mean(prices) for y, prices in year_prices.items()}

    # Compute year-over-year depreciation rates
    rates = []
    sorted_years = sorted(year_avg.keys())
    for i in range(len(sorted_years) - 1):
        older_year = sorted_years[i]
        newer_year = sorted_years[i + 1]
        if year_avg[newer_year] > 0:
            rate = (year_avg[newer_year] - year_avg[older_year]) / year_avg[newer_year]
            if 0 < rate < 0.5:  # Sanity check
                rates.append(rate)

    if rates:
        return mean(rates)
    return None


def get_depreciation_comparison(listing_ids: list[str]) -> list[dict]:
    """Compare depreciation projections for multiple listings."""
    results = []
    for lid in listing_ids[:5]:
        prediction = predict_depreciation(listing_id=lid, months_ahead=[6, 12, 24])
        if "error" not in prediction:
            results.append(prediction)
    return results

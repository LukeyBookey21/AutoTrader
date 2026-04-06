"""Market value calculator - estimates car value from scraped data."""

import logging
from statistics import mean, median, stdev

from autotrader.config import SPEC_UPLIFT, get_mileage_band
from autotrader.storage.database import get_db, get_market_stats

logger = logging.getLogger(__name__)


def calculate_valuation(
    make: str,
    model: str,
    year: int,
    mileage: int,
    features: list[str] | None = None,
    seller_type: str = "trade",
) -> dict:
    """Calculate an estimated market value based on scraped data.

    This is our own valuation using the dataset we've built, not
    AutoTrader's proprietary valuation.

    Args:
        make: Vehicle manufacturer.
        model: Vehicle model.
        year: Registration year.
        mileage: Current mileage.
        features: List of normalised feature keys.
        seller_type: 'trade' or 'private'.

    Returns:
        Dict with estimated values, confidence, and breakdown.
    """
    mileage_band = get_mileage_band(mileage)

    # Get exact match stats
    stats = get_market_stats(make, model, year=year, mileage_band=mileage_band)

    # Fall back to same year any mileage
    if not stats:
        stats = get_market_stats(make, model, year=year)

    # Fall back to any year
    if not stats:
        stats = get_market_stats(make, model)

    if not stats:
        return {
            "error": "No market data available for this vehicle",
            "make": make,
            "model": model,
            "year": year,
            "mileage": mileage,
        }

    # Get raw listing prices for this segment from DB
    comparables = _get_comparable_prices(make, model, year, mileage)

    # Base valuation from market stats
    best_stat = stats[0]
    base_price = best_stat["median_price"]
    sample_count = sum(s.get("sample_count", 0) for s in stats)

    # Mileage adjustment - if mileage is unusual for the band, adjust
    mileage_adjustment = _mileage_adjustment(mileage, year, base_price)

    # Spec uplift
    spec_uplift_total = 0
    spec_details = []
    if features:
        for feat in features:
            uplift = SPEC_UPLIFT.get(feat, 0)
            if uplift > 0:
                spec_uplift_total += uplift
                spec_details.append({"feature": feat, "uplift": uplift})

    # Seller type adjustment
    seller_adjustment = 0
    if seller_type == "private":
        seller_adjustment = int(-base_price * 0.08)  # Private ~8% cheaper

    # Final valuation
    estimated_value = int(base_price + mileage_adjustment + spec_uplift_total + seller_adjustment)

    # Confidence
    if sample_count >= 20:
        confidence = "high"
    elif sample_count >= 5:
        confidence = "medium"
    else:
        confidence = "low"

    # Value range
    if comparables and len(comparables) >= 3:
        low_value = int(sorted(comparables)[max(0, len(comparables) // 10)])
        high_value = int(sorted(comparables)[min(len(comparables) - 1, len(comparables) * 9 // 10)])
    else:
        low_value = int(estimated_value * 0.85)
        high_value = int(estimated_value * 1.15)

    return {
        "make": make,
        "model": model,
        "year": year,
        "mileage": mileage,
        "mileage_band": mileage_band,
        "estimated_value": estimated_value,
        "value_range": {"low": low_value, "high": high_value},
        "confidence": confidence,
        "sample_count": sample_count,
        "breakdown": {
            "base_market_price": int(base_price),
            "mileage_adjustment": mileage_adjustment,
            "spec_uplift": spec_uplift_total,
            "seller_adjustment": seller_adjustment,
            "spec_details": spec_details,
        },
        "seller_type": seller_type,
    }


def _mileage_adjustment(mileage: int, year: int, base_price: float) -> int:
    """Adjust price based on mileage relative to expected for age."""
    from datetime import datetime, timezone
    current_year = datetime.now(timezone.utc).year
    age = max(current_year - year, 1)
    from autotrader.config import AVERAGE_ANNUAL_MILEAGE
    expected = age * AVERAGE_ANNUAL_MILEAGE

    if expected <= 0:
        return 0

    ratio = mileage / expected
    # Below average mileage adds value, above subtracts
    if ratio < 0.5:
        return int(base_price * 0.08)  # 8% premium for very low mileage
    elif ratio < 0.75:
        return int(base_price * 0.04)
    elif ratio <= 1.0:
        return 0
    elif ratio <= 1.25:
        return int(-base_price * 0.04)
    elif ratio <= 1.5:
        return int(-base_price * 0.08)
    else:
        return int(-base_price * 0.12)


def _get_comparable_prices(
    make: str, model: str, year: int, mileage: int
) -> list[int]:
    """Get raw prices of comparable listings from DB."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT price FROM listings
               WHERE LOWER(make) = LOWER(?)
               AND LOWER(model) = LOWER(?)
               AND year BETWEEN ? AND ?
               AND price IS NOT NULL
               ORDER BY price""",
            (make, model, year - 1, year + 1),
        ).fetchall()
        return [row[0] for row in rows]

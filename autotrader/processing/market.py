"""Market analysis - computes aggregate statistics for deal scoring."""

import logging
from statistics import mean, median

from autotrader.config import get_mileage_band
from autotrader.storage.database import get_all_listings_for_scoring, save_market_stats

logger = logging.getLogger(__name__)


def compute_market_stats(make: str | None = None, model: str | None = None) -> list[dict]:
    """Compute market statistics grouped by make/model/year/mileage band.

    Aggregates all detail-scraped listings to produce per-segment stats
    used by the deal scoring engine.
    """
    listings = get_all_listings_for_scoring(make, model)
    if not listings:
        logger.warning("No listings available for market analysis")
        return []

    # Group listings by (make, model, year, mileage_band)
    groups: dict[tuple, list[int]] = {}
    for listing in listings:
        if not listing.get("price") or not listing.get("mileage"):
            continue

        key = (
            (listing.get("make") or "").lower(),
            (listing.get("model") or "").lower(),
            listing.get("year"),
            get_mileage_band(listing["mileage"]),
        )
        groups.setdefault(key, []).append(listing["price"])

    # Compute stats for each group
    stats = []
    for (make_val, model_val, year, mileage_band), prices in groups.items():
        if len(prices) < 2:
            # Not enough data for meaningful stats, but still record
            pass

        sorted_prices = sorted(prices)
        stats.append({
            "make": make_val,
            "model": model_val,
            "year": year,
            "mileage_band": mileage_band,
            "avg_price": round(mean(sorted_prices), 2),
            "median_price": round(median(sorted_prices), 2),
            "min_price": min(sorted_prices),
            "max_price": max(sorted_prices),
            "sample_count": len(sorted_prices),
        })

    # Save to database
    if stats:
        save_market_stats(stats)
        logger.info(f"Computed market stats for {len(stats)} segments "
                    f"from {len(listings)} listings")

    return stats

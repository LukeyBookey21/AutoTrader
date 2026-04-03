"""Deal scoring engine - scores each listing on a 0-100 scale."""

import logging
from datetime import datetime, timezone

from autotrader.config import AVERAGE_ANNUAL_MILEAGE, SPEC_UPLIFT, get_mileage_band
from autotrader.storage.database import (
    get_all_listings_for_scoring,
    get_market_stats,
    update_listing_scores,
)

logger = logging.getLogger(__name__)


def _score_price_vs_market(price: int, market_median: float, market_avg: float) -> tuple[int, str]:
    """Score 0-50 based on how the price compares to market.

    Returns (points, explanation).
    """
    if market_median <= 0:
        return 25, "Insufficient market data for comparison"

    # Use the lower of median and avg as reference to be conservative
    reference = min(market_median, market_avg)
    diff_pct = ((reference - price) / reference) * 100

    if diff_pct >= 20:
        return 50, f"{diff_pct:.0f}% below market average (excellent)"
    elif diff_pct >= 15:
        return 45, f"{diff_pct:.0f}% below market average (very good)"
    elif diff_pct >= 10:
        return 40, f"{diff_pct:.0f}% below market average (good)"
    elif diff_pct >= 5:
        return 35, f"{diff_pct:.0f}% below market average (above average)"
    elif diff_pct >= 0:
        return 30, f"Around market average price"
    elif diff_pct >= -5:
        return 20, f"{-diff_pct:.0f}% above market average"
    elif diff_pct >= -10:
        return 10, f"{-diff_pct:.0f}% above market average"
    else:
        return 0, f"{-diff_pct:.0f}% above market average (expensive)"


def _score_mileage(
    mileage: int, year: int, market_median_mileage: float | None = None
) -> tuple[int, str]:
    """Score 0-15 based on mileage relative to age expectations.

    Returns (points, explanation).
    """
    if not year or not mileage:
        return 7, "Mileage data incomplete"

    current_year = datetime.now(timezone.utc).year
    age = max(current_year - year, 1)
    expected_mileage = age * AVERAGE_ANNUAL_MILEAGE

    ratio = mileage / expected_mileage if expected_mileage > 0 else 1.0

    if ratio <= 0.5:
        return 15, f"Very low mileage for age ({mileage:,} vs {expected_mileage:,} expected)"
    elif ratio <= 0.75:
        return 12, f"Below average mileage ({mileage:,} vs {expected_mileage:,} expected)"
    elif ratio <= 1.0:
        return 9, f"Average mileage for age"
    elif ratio <= 1.25:
        return 5, f"Above average mileage ({mileage:,} vs {expected_mileage:,} expected)"
    else:
        return 2, f"High mileage for age ({mileage:,} vs {expected_mileage:,} expected)"


def _score_spec_uplift(normalised_features: list[str], price: int) -> tuple[int, str]:
    """Score 0-15 based on premium features present.

    Features add value - if the car has premium features but is priced
    at the same level as lesser-spec examples, that's a better deal.

    Returns (points, explanation).
    """
    total_uplift = 0
    valuable_features = []

    for feature in normalised_features:
        uplift = SPEC_UPLIFT.get(feature, 0)
        if uplift > 0:
            total_uplift += uplift
            valuable_features.append(feature)

    if not valuable_features:
        return 0, "No premium features detected"

    # Score based on spec uplift as percentage of price
    uplift_pct = (total_uplift / price * 100) if price > 0 else 0

    if uplift_pct >= 10:
        points = 15
    elif uplift_pct >= 7:
        points = 12
    elif uplift_pct >= 4:
        points = 9
    elif uplift_pct >= 2:
        points = 6
    else:
        points = 3

    feature_summary = ", ".join(
        f.replace("_", " ").title() for f in valuable_features[:5]
    )
    extra = f" +{len(valuable_features) - 5} more" if len(valuable_features) > 5 else ""

    return points, f"Premium specs worth ~{total_uplift:,}: {feature_summary}{extra}"


def _score_market_signals(listing: dict) -> tuple[int, str]:
    """Score 0-20 based on market signals (price drops, days listed, etc.).

    Returns (points, explanation).
    """
    points = 0
    reasons = []

    # Price drop is a positive signal
    if listing.get("price_dropped"):
        points += 5
        drop = listing.get("price_drop_amount")
        if drop:
            reasons.append(f"Price reduced by {drop:,}")
        else:
            reasons.append("Price recently reduced")

    # Days on market - long-listed cars may have motivated sellers
    days = listing.get("days_on_market")
    if days is not None:
        if days >= 60:
            points += 5
            reasons.append(f"Listed {days} days (likely motivated seller)")
        elif days >= 30:
            points += 3
            reasons.append(f"Listed {days} days")
        elif days <= 3:
            reasons.append("Newly listed")

    # Private sellers tend to be cheaper
    if listing.get("seller_type") == "private":
        points += 3
        reasons.append("Private seller (typically lower price)")

    # AutoTrader's own rating as a corroborating signal
    at_rating = (listing.get("at_deal_rating") or "").lower()
    if "great" in at_rating:
        points += 5
        reasons.append("AutoTrader rates as 'Great price'")
    elif "good" in at_rating:
        points += 3
        reasons.append("AutoTrader rates as 'Good price'")
    elif "fair" in at_rating:
        points += 1
        reasons.append("AutoTrader rates as 'Fair price'")
    elif "high" in at_rating:
        reasons.append("AutoTrader rates as 'Higher price'")

    # Image count as quality signal (more images = more transparent)
    images = listing.get("images_count", 0)
    if images and images >= 15:
        points += 2
        reasons.append(f"{images} photos (comprehensive)")
    elif images and images <= 3:
        points -= 1
        reasons.append(f"Only {images} photos (limited transparency)")

    # Cap at 20
    points = max(0, min(20, points))

    explanation = "; ".join(reasons) if reasons else "No notable market signals"
    return points, explanation


def score_listing(listing: dict, market_stats: list[dict]) -> dict:
    """Score a single listing.

    Args:
        listing: Full listing dict.
        market_stats: Market stats for the listing's make/model.

    Returns:
        Dict with 'id', 'deal_score', 'deal_explanation'.
    """
    price = listing.get("price", 0)
    if not price:
        return {
            "id": listing["id"],
            "deal_score": None,
            "deal_explanation": "Cannot score: no price data",
        }

    # Find matching market stats
    year = listing.get("year")
    mileage = listing.get("mileage", 0)
    mileage_band = get_mileage_band(mileage) if mileage else None

    matching_stats = None
    for stat in market_stats:
        if stat.get("year") == year and stat.get("mileage_band") == mileage_band:
            matching_stats = stat
            break

    # Fall back to same year, any mileage band
    if not matching_stats:
        year_stats = [s for s in market_stats if s.get("year") == year]
        if year_stats:
            # Use the one with the most samples
            matching_stats = max(year_stats, key=lambda s: s.get("sample_count", 0))

    # Fall back to any stats for this make/model
    if not matching_stats and market_stats:
        matching_stats = max(market_stats, key=lambda s: s.get("sample_count", 0))

    # Component scores
    explanations = []

    # 1. Price vs Market (0-50)
    if matching_stats and matching_stats.get("sample_count", 0) >= 2:
        price_score, price_exp = _score_price_vs_market(
            price, matching_stats["median_price"], matching_stats["avg_price"]
        )
        explanations.append(f"Price: {price_exp} (based on {matching_stats['sample_count']} comparable listings)")
    else:
        price_score = 25  # Neutral when no comparison data
        explanations.append("Price: Insufficient market data for comparison")

    # 2. Mileage Value (0-15)
    mileage_score, mileage_exp = _score_mileage(mileage, year)
    explanations.append(f"Mileage: {mileage_exp}")

    # 3. Spec Uplift (0-15)
    normalised = listing.get("features_normalised", [])
    spec_score, spec_exp = _score_spec_uplift(normalised, price)
    explanations.append(f"Spec: {spec_exp}")

    # 4. Market Signals (0-20)
    signal_score, signal_exp = _score_market_signals(listing)
    explanations.append(f"Signals: {signal_exp}")

    # Total
    total = price_score + mileage_score + spec_score + signal_score
    total = max(0, min(100, total))

    # Rating label
    if total >= 80:
        label = "Exceptional Deal"
    elif total >= 65:
        label = "Great Deal"
    elif total >= 50:
        label = "Good Deal"
    elif total >= 35:
        label = "Fair Deal"
    else:
        label = "Below Average"

    explanation = f"[{label}] Score: {total}/100\n" + "\n".join(f"  - {e}" for e in explanations)

    return {
        "id": listing["id"],
        "deal_score": total,
        "deal_explanation": explanation,
    }


def score_all_listings(make: str | None = None, model: str | None = None) -> int:
    """Score all detail-scraped listings in the database.

    Args:
        make: Optional filter by make.
        model: Optional filter by model.

    Returns:
        Number of listings scored.
    """
    listings = get_all_listings_for_scoring(make, model)
    if not listings:
        logger.warning("No listings available for scoring")
        return 0

    # Group by make/model to fetch market stats efficiently
    make_model_pairs = set()
    for listing in listings:
        m = (listing.get("make") or "").lower()
        mo = (listing.get("model") or "").lower()
        if m and mo:
            make_model_pairs.add((m, mo))

    # Fetch market stats for each make/model pair
    stats_cache: dict[tuple, list[dict]] = {}
    for m, mo in make_model_pairs:
        stats_cache[(m, mo)] = get_market_stats(m, mo)

    # Score each listing
    scores = []
    for listing in listings:
        m = (listing.get("make") or "").lower()
        mo = (listing.get("model") or "").lower()
        stats = stats_cache.get((m, mo), [])
        result = score_listing(listing, stats)
        scores.append(result)

    # Save scores to database
    valid_scores = [s for s in scores if s["deal_score"] is not None]
    if valid_scores:
        update_listing_scores(valid_scores)
        logger.info(f"Scored {len(valid_scores)} listings")

    return len(valid_scores)

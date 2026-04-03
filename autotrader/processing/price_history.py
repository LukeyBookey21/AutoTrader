"""Price history tracking - records price snapshots over time for each listing."""

import json
import logging
from datetime import datetime, timezone

from autotrader.storage.database import get_db

logger = logging.getLogger(__name__)


def record_price_snapshot(listing_id: str, price: int):
    """Record a price snapshot for a listing.

    Called during each scrape to track price changes over time.
    Only records if the price has changed since the last snapshot.
    """
    if not price:
        return

    now = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        # Get the most recent snapshot
        last = conn.execute(
            """SELECT price FROM price_history
               WHERE listing_id = ?
               ORDER BY recorded_at DESC LIMIT 1""",
            (listing_id,),
        ).fetchone()

        # Only record if price changed or no previous record
        if not last or last[0] != price:
            conn.execute(
                """INSERT INTO price_history (listing_id, price, recorded_at)
                   VALUES (?, ?, ?)""",
                (listing_id, price, now),
            )
            if last and last[0] != price:
                change = price - last[0]
                direction = "dropped" if change < 0 else "increased"
                logger.info(
                    f"Listing {listing_id}: price {direction} by "
                    f"£{abs(change):,} (was £{last[0]:,}, now £{price:,})"
                )


def record_price_snapshots_batch(listings: list[dict]):
    """Record price snapshots for multiple listings."""
    for listing in listings:
        if listing.get("price") and listing.get("id"):
            record_price_snapshot(listing["id"], listing["price"])


def get_price_history(listing_id: str) -> list[dict]:
    """Get full price history for a listing.

    Returns:
        List of {price, recorded_at} dicts, oldest first.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT price, recorded_at FROM price_history
               WHERE listing_id = ?
               ORDER BY recorded_at ASC""",
            (listing_id,),
        ).fetchall()
        return [{"price": row[0], "recorded_at": row[1]} for row in rows]


def get_price_drops(min_drop: int = 100, limit: int = 50) -> list[dict]:
    """Find listings with the largest recent price drops.

    Args:
        min_drop: Minimum drop in GBP to include.
        limit: Maximum results.

    Returns:
        List of dicts with listing_id, current_price, original_price, total_drop.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT
                ph.listing_id,
                l.title,
                l.price as current_price,
                (SELECT price FROM price_history
                 WHERE listing_id = ph.listing_id
                 ORDER BY recorded_at ASC LIMIT 1) as original_price,
                l.url
               FROM price_history ph
               JOIN listings l ON l.id = ph.listing_id
               GROUP BY ph.listing_id
               HAVING COUNT(*) > 1
               AND original_price - current_price >= ?
               ORDER BY (original_price - current_price) DESC
               LIMIT ?""",
            (min_drop, limit),
        ).fetchall()

        results = []
        for row in rows:
            results.append({
                "listing_id": row[0],
                "title": row[1],
                "current_price": row[2],
                "original_price": row[3],
                "total_drop": row[3] - row[2] if row[3] and row[2] else 0,
                "url": row[4],
            })
        return results


def get_market_price_trend(make: str, model: str, year: int | None = None) -> list[dict]:
    """Get average price trend over time for a make/model.

    Useful for showing market direction charts.
    """
    conditions = ["LOWER(l.make) = LOWER(?)", "LOWER(l.model) = LOWER(?)"]
    params: list = [make, model]
    if year:
        conditions.append("l.year = ?")
        params.append(year)

    where = " AND ".join(conditions)

    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT
                DATE(ph.recorded_at) as date,
                AVG(ph.price) as avg_price,
                COUNT(DISTINCT ph.listing_id) as sample_count
               FROM price_history ph
               JOIN listings l ON l.id = ph.listing_id
               WHERE {where}
               GROUP BY DATE(ph.recorded_at)
               ORDER BY date ASC""",
            params,
        ).fetchall()

        return [
            {"date": row[0], "avg_price": round(row[1], 2), "sample_count": row[2]}
            for row in rows
        ]

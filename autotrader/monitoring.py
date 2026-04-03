"""Price monitoring & alerts - watches saved searches and notifies on changes."""

import asyncio
import json
import logging
from datetime import datetime, timezone

from autotrader.storage.database import get_db, init_db

logger = logging.getLogger(__name__)


def save_watch(
    name: str,
    search_params: dict,
    min_score: int | None = None,
    max_price: int | None = None,
    required_features: list[str] | None = None,
):
    """Save a search watch for monitoring.

    Args:
        name: Human-readable name for this watch.
        search_params: Dict of search parameters.
        min_score: Only alert for listings scoring above this.
        max_price: Only alert for listings below this price.
        required_features: Only alert if listing has these features.
    """
    with get_db() as conn:
        conn.execute(
            """INSERT INTO watches
               (name, search_params, min_score, max_price, required_features, active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (
                name,
                json.dumps(search_params),
                min_score,
                max_price,
                json.dumps(required_features or []),
            ),
        )
    logger.info(f"Saved watch: {name}")


def list_watches() -> list[dict]:
    """List all saved watches."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM watches ORDER BY created_at DESC"
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d["search_params"] = json.loads(d["search_params"])
            d["required_features"] = json.loads(d["required_features"])
            results.append(d)
        return results


def delete_watch(watch_id: int):
    """Delete a saved watch."""
    with get_db() as conn:
        conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))


def get_alerts(limit: int = 50, unread_only: bool = False) -> list[dict]:
    """Get recent alerts."""
    condition = "AND read = 0" if unread_only else ""
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM alerts
                WHERE 1=1 {condition}
                ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_alerts_read(alert_ids: list[int] | None = None):
    """Mark alerts as read."""
    with get_db() as conn:
        if alert_ids:
            placeholders = ",".join(["?"] * len(alert_ids))
            conn.execute(
                f"UPDATE alerts SET read = 1 WHERE id IN ({placeholders})",
                alert_ids,
            )
        else:
            conn.execute("UPDATE alerts SET read = 1")


def _create_alert(conn, watch_id: int, listing_id: str, alert_type: str, message: str):
    """Create a new alert."""
    conn.execute(
        """INSERT INTO alerts (watch_id, listing_id, alert_type, message)
           VALUES (?, ?, ?, ?)""",
        (watch_id, listing_id, alert_type, message),
    )


async def run_watch_check(watch: dict) -> list[dict]:
    """Run a single watch check and generate alerts for new/changed listings.

    Returns list of new alerts generated.
    """
    from autotrader.storage.database import search_listings

    params = watch["search_params"]
    min_score = watch.get("min_score")
    max_price = watch.get("max_price")
    required_features = watch.get("required_features", [])

    # Query current matching listings
    listings = search_listings(
        make=params.get("make"),
        model=params.get("model"),
        year_from=params.get("year_from"),
        year_to=params.get("year_to"),
        price_from=params.get("price_from"),
        price_to=params.get("price_to"),
        mileage_max=params.get("mileage_max"),
        fuel_type=params.get("fuel_type"),
        transmission=params.get("transmission"),
        features=required_features or None,
        sort_by="deal_score",
        sort_order="DESC",
        limit=500,
    )

    # Apply additional filters
    if min_score:
        listings = [l for l in listings if l.get("deal_score") and l["deal_score"] >= min_score]
    if max_price:
        listings = [l for l in listings if l.get("price") and l["price"] <= max_price]

    new_alerts = []

    with get_db() as conn:
        # Get previously seen listing IDs for this watch
        seen_rows = conn.execute(
            "SELECT listing_id FROM watch_seen WHERE watch_id = ?",
            (watch["id"],),
        ).fetchall()
        seen_ids = {row[0] for row in seen_rows}

        for listing in listings:
            lid = listing["id"]

            if lid not in seen_ids:
                # New listing alert
                score = listing.get("deal_score", 0) or 0
                price = listing.get("price", 0)
                title = listing.get("title", "Unknown")

                msg = (
                    f"New listing: {title} - £{price:,} "
                    f"(Score: {score:.0f}/100)"
                )
                _create_alert(conn, watch["id"], lid, "new_listing", msg)
                new_alerts.append({"listing_id": lid, "type": "new_listing", "message": msg})

                # Mark as seen
                conn.execute(
                    "INSERT OR IGNORE INTO watch_seen (watch_id, listing_id) VALUES (?, ?)",
                    (watch["id"], lid),
                )

        # Check for price drops on already-seen listings
        for lid in seen_ids:
            row = conn.execute(
                """SELECT l.title, l.price, ph.price as old_price
                   FROM listings l
                   LEFT JOIN (
                       SELECT listing_id, price FROM price_history
                       WHERE listing_id = ?
                       ORDER BY recorded_at DESC LIMIT 1 OFFSET 1
                   ) ph ON ph.listing_id = l.id
                   WHERE l.id = ?""",
                (lid, lid),
            ).fetchone()

            if row and row[2] and row[1] and row[1] < row[2]:
                drop = row[2] - row[1]
                msg = f"Price drop: {row[0]} - now £{row[1]:,} (was £{row[2]:,}, -£{drop:,})"
                _create_alert(conn, watch["id"], lid, "price_drop", msg)
                new_alerts.append({"listing_id": lid, "type": "price_drop", "message": msg})

        # Update last checked timestamp
        conn.execute(
            "UPDATE watches SET last_checked = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), watch["id"]),
        )

    return new_alerts


async def run_all_watches() -> list[dict]:
    """Run all active watches and return generated alerts."""
    watches = list_watches()
    active = [w for w in watches if w.get("active")]

    all_alerts = []
    for watch in active:
        logger.info(f"Checking watch: {watch['name']}")
        alerts = await run_watch_check(watch)
        all_alerts.extend(alerts)
        if alerts:
            logger.info(f"  Generated {len(alerts)} alerts")

    return all_alerts


async def monitor_loop(interval_minutes: int = 30):
    """Run monitoring in a loop. For use with the CLI 'monitor' command."""
    logger.info(f"Starting monitoring loop (interval: {interval_minutes}min)")
    while True:
        try:
            alerts = await run_all_watches()
            if alerts:
                print(f"\n[{datetime.now().strftime('%H:%M')}] {len(alerts)} new alerts:")
                for alert in alerts:
                    print(f"  {alert['type']}: {alert['message']}")
            else:
                print(f"[{datetime.now().strftime('%H:%M')}] No new alerts.")
        except Exception as e:
            logger.error(f"Monitor error: {e}")

        await asyncio.sleep(interval_minutes * 60)

"""SQLite database operations for storing and querying listings."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from autotrader.config import CACHE_TTL_HOURS, DB_PATH


def _ensure_db_dir():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    """Get a new database connection with row factory."""
    _ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create database tables if they don't exist."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT,
                price INTEGER,
                make TEXT,
                model TEXT,
                variant TEXT,
                year INTEGER,
                mileage INTEGER,
                fuel_type TEXT,
                transmission TEXT,
                body_type TEXT,
                engine_size REAL,
                doors INTEGER,
                colour TEXT,
                seller_type TEXT,
                seller_name TEXT,
                location TEXT,
                distance REAL,
                images_count INTEGER,
                description TEXT,
                at_deal_rating TEXT,
                deal_score REAL,
                deal_explanation TEXT,
                price_when_new INTEGER,
                days_on_market INTEGER,
                price_dropped INTEGER DEFAULT 0,
                price_drop_amount INTEGER,
                features_raw TEXT DEFAULT '[]',
                features_normalised TEXT DEFAULT '[]',
                scraped_at TIMESTAMP,
                first_seen TIMESTAMP,
                detail_scraped INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                params_json TEXT NOT NULL,
                result_count INTEGER,
                searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS market_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                make TEXT NOT NULL,
                model TEXT NOT NULL,
                year INTEGER,
                mileage_band TEXT,
                avg_price REAL,
                median_price REAL,
                min_price REAL,
                max_price REAL,
                sample_count INTEGER,
                computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_listings_make_model
                ON listings(make, model);
            CREATE INDEX IF NOT EXISTS idx_listings_year
                ON listings(year);
            CREATE INDEX IF NOT EXISTS idx_listings_price
                ON listings(price);
            CREATE INDEX IF NOT EXISTS idx_listings_scraped
                ON listings(scraped_at);
            CREATE INDEX IF NOT EXISTS idx_market_stats_lookup
                ON market_stats(make, model, year, mileage_band);

            -- Price history tracking
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT NOT NULL,
                price INTEGER NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (listing_id) REFERENCES listings(id)
            );
            CREATE INDEX IF NOT EXISTS idx_price_history_listing
                ON price_history(listing_id, recorded_at);

            -- MOT data storage (ALTER TABLE handled separately)

            -- Monitoring watches
            CREATE TABLE IF NOT EXISTS watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                search_params TEXT NOT NULL,
                min_score INTEGER,
                max_price INTEGER,
                required_features TEXT DEFAULT '[]',
                active INTEGER DEFAULT 1,
                last_checked TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS watch_seen (
                watch_id INTEGER NOT NULL,
                listing_id TEXT NOT NULL,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (watch_id, listing_id),
                FOREIGN KEY (watch_id) REFERENCES watches(id) ON DELETE CASCADE,
                FOREIGN KEY (listing_id) REFERENCES listings(id)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                watch_id INTEGER,
                listing_id TEXT,
                alert_type TEXT NOT NULL,
                message TEXT NOT NULL,
                read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (watch_id) REFERENCES watches(id),
                FOREIGN KEY (listing_id) REFERENCES listings(id)
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_unread
                ON alerts(read, created_at);
        """)

        # Safe column additions (ignore if already exists)
        for col, col_type, default in [
            ("mot_data", "TEXT", "NULL"),
        ]:
            try:
                conn.execute(
                    f"ALTER TABLE listings ADD COLUMN {col} {col_type} DEFAULT {default}"
                )
            except sqlite3.OperationalError:
                pass  # Column already exists


def upsert_listing(conn: sqlite3.Connection, listing: dict[str, Any]):
    """Insert or update a listing. Preserves first_seen on update."""
    now = datetime.now(timezone.utc).isoformat()
    listing.setdefault("scraped_at", now)
    listing.setdefault("first_seen", now)

    # Serialise list fields to JSON
    for field in ("features_raw", "features_normalised"):
        if isinstance(listing.get(field), list):
            listing[field] = json.dumps(listing[field])

    # Check if listing exists to preserve first_seen
    existing = conn.execute(
        "SELECT first_seen FROM listings WHERE id = ?", (listing["id"],)
    ).fetchone()
    if existing:
        listing["first_seen"] = existing["first_seen"]

    columns = list(listing.keys())
    placeholders = ", ".join(["?"] * len(columns))
    updates = ", ".join(
        [f"{c} = excluded.{c}" for c in columns if c != "id" and c != "first_seen"]
    )

    sql = f"""
        INSERT INTO listings ({', '.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(id) DO UPDATE SET {updates}
    """
    conn.execute(sql, [listing.get(c) for c in columns])


def upsert_listings(listings: list[dict[str, Any]]):
    """Bulk upsert multiple listings."""
    with get_db() as conn:
        for listing in listings:
            upsert_listing(conn, listing)


def get_listing(listing_id: str) -> dict | None:
    """Get a single listing by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM listings WHERE id = ?", (listing_id,)
        ).fetchone()
        if row:
            return _row_to_dict(row)
    return None


def listing_needs_detail_scrape(listing_id: str) -> bool:
    """Check if a listing needs its detail page scraped."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT detail_scraped, scraped_at FROM listings WHERE id = ?",
            (listing_id,),
        ).fetchone()
        if not row:
            return True
        if not row["detail_scraped"]:
            return True
        if row["scraped_at"]:
            scraped = datetime.fromisoformat(row["scraped_at"])
            if scraped.tzinfo is None:
                scraped = scraped.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)
            return scraped < cutoff
    return False


def search_listings(
    make: str | None = None,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    price_from: int | None = None,
    price_to: int | None = None,
    mileage_max: int | None = None,
    fuel_type: str | None = None,
    transmission: str | None = None,
    features: list[str] | None = None,
    sort_by: str = "deal_score",
    sort_order: str = "DESC",
    limit: int = 200,
) -> list[dict]:
    """Query listings from the database with filters."""
    conditions = []
    params: list[Any] = []

    if make:
        conditions.append("LOWER(make) = LOWER(?)")
        params.append(make)
    if model:
        conditions.append("LOWER(model) = LOWER(?)")
        params.append(model)
    if year_from:
        conditions.append("year >= ?")
        params.append(year_from)
    if year_to:
        conditions.append("year <= ?")
        params.append(year_to)
    if price_from:
        conditions.append("price >= ?")
        params.append(price_from)
    if price_to:
        conditions.append("price <= ?")
        params.append(price_to)
    if mileage_max:
        conditions.append("mileage <= ?")
        params.append(mileage_max)
    if fuel_type:
        conditions.append("LOWER(fuel_type) = LOWER(?)")
        params.append(fuel_type)
    if transmission:
        conditions.append("LOWER(transmission) = LOWER(?)")
        params.append(transmission)

    # Feature filtering uses JSON contains on normalised features
    if features:
        for feat in features:
            conditions.append("features_normalised LIKE ?")
            params.append(f'%"{feat}"%')

    where = " AND ".join(conditions) if conditions else "1=1"

    allowed_sorts = {
        "deal_score", "price", "year", "mileage", "days_on_market", "scraped_at"
    }
    if sort_by not in allowed_sorts:
        sort_by = "deal_score"
    if sort_order.upper() not in ("ASC", "DESC"):
        sort_order = "DESC"

    sql = f"""
        SELECT * FROM listings
        WHERE {where}
        ORDER BY {sort_by} {sort_order} NULLS LAST
        LIMIT ?
    """
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(row) for row in rows]


def save_search_history(params: dict, result_count: int):
    """Record a search in history."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO search_history (params_json, result_count) VALUES (?, ?)",
            (json.dumps(params), result_count),
        )


def save_market_stats(stats: list[dict]):
    """Save computed market statistics."""
    with get_db() as conn:
        # Clear old stats for the same segments
        for s in stats:
            conn.execute(
                """DELETE FROM market_stats
                   WHERE make = ? AND model = ? AND year = ? AND mileage_band = ?""",
                (s["make"], s["model"], s["year"], s["mileage_band"]),
            )
        conn.executemany(
            """INSERT INTO market_stats
               (make, model, year, mileage_band, avg_price, median_price,
                min_price, max_price, sample_count)
               VALUES (:make, :model, :year, :mileage_band, :avg_price,
                       :median_price, :min_price, :max_price, :sample_count)""",
            stats,
        )


def get_market_stats(
    make: str, model: str, year: int | None = None, mileage_band: str | None = None
) -> list[dict]:
    """Get market stats for a make/model."""
    conditions = ["LOWER(make) = LOWER(?)", "LOWER(model) = LOWER(?)"]
    params: list[Any] = [make, model]
    if year:
        conditions.append("year = ?")
        params.append(year)
    if mileage_band:
        conditions.append("mileage_band = ?")
        params.append(mileage_band)

    where = " AND ".join(conditions)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM market_stats WHERE {where} ORDER BY year, mileage_band",
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def get_all_listings_for_scoring(make: str | None = None, model: str | None = None):
    """Get all listings that have been detail-scraped, for scoring."""
    conditions = ["detail_scraped = 1"]
    params: list[Any] = []
    if make:
        conditions.append("LOWER(make) = LOWER(?)")
        params.append(make)
    if model:
        conditions.append("LOWER(model) = LOWER(?)")
        params.append(model)
    where = " AND ".join(conditions)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM listings WHERE {where}", params
        ).fetchall()
        return [_row_to_dict(row) for row in rows]


def update_listing_scores(scores: list[dict]):
    """Batch update deal scores for listings."""
    with get_db() as conn:
        for s in scores:
            conn.execute(
                "UPDATE listings SET deal_score = ?, deal_explanation = ? WHERE id = ?",
                (s["deal_score"], s["deal_explanation"], s["id"]),
            )


def update_listing_normalised_features(listing_id: str, features: list[str]):
    """Update the normalised features for a listing."""
    with get_db() as conn:
        conn.execute(
            "UPDATE listings SET features_normalised = ? WHERE id = ?",
            (json.dumps(features), listing_id),
        )


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a Row to a dict, deserialising JSON fields."""
    d = dict(row)
    for field in ("features_raw", "features_normalised"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
    # Deserialise MOT data if present
    if isinstance(d.get("mot_data"), str):
        try:
            d["mot_data"] = json.loads(d["mot_data"])
        except (json.JSONDecodeError, TypeError):
            d["mot_data"] = None
    return d

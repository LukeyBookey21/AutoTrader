"""FastAPI web application with full API for the SPA frontend."""

import csv
import io
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from autotrader.monitoring import (
    delete_watch,
    get_alerts,
    list_watches,
    mark_alerts_read,
    save_watch,
)
from autotrader.processing.normaliser import FEATURE_DISPLAY_NAMES
from autotrader.processing.price_history import (
    get_market_price_trend,
    get_price_drops,
    get_price_history,
)
from autotrader.storage.database import (
    add_to_shortlist,
    find_similar_listings,
    get_db,
    get_freshness_data,
    get_listing,
    get_listing_images,
    get_new_listings,
    get_shortlist,
    get_top_deals,
    init_db,
    is_shortlisted,
    remove_from_shortlist,
    search_listings,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="AutoTrader Deal Finder", version="2.0.0")

_web_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(_web_dir / "static")), name="static")


@app.on_event("startup")
async def startup():
    init_db()


# ---------- SPA entry point ----------

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the SPA."""
    return FileResponse(str(_web_dir / "static" / "index.html"))


# ---------- API: Listings ----------

def _parse_listing_params(
    make, model, year_from, year_to, price_from, price_to,
    mileage_max, fuel_type, transmission, features, sort_by, sort_order, limit,
):
    return search_listings(
        make=make or None,
        model=model or None,
        year_from=year_from,
        year_to=year_to,
        price_from=price_from,
        price_to=price_to,
        mileage_max=mileage_max,
        fuel_type=fuel_type or None,
        transmission=transmission or None,
        features=features or None,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
    )


@app.get("/api/listings")
async def api_listings(
    make: str = Query(default=""),
    model: str = Query(default=""),
    year_from: int | None = Query(default=None),
    year_to: int | None = Query(default=None),
    price_from: int | None = Query(default=None),
    price_to: int | None = Query(default=None),
    mileage_max: int | None = Query(default=None),
    fuel_type: str = Query(default=""),
    transmission: str = Query(default=""),
    features: list[str] = Query(default=[]),
    sort_by: str = Query(default="deal_score"),
    sort_order: str = Query(default="DESC"),
    limit: int = Query(default=200),
):
    """JSON API endpoint for listings."""
    listings = _parse_listing_params(
        make, model, year_from, year_to, price_from, price_to,
        mileage_max, fuel_type, transmission, features, sort_by, sort_order, limit,
    )
    return {"count": len(listings), "listings": listings}


@app.get("/api/listing/{listing_id}")
async def api_listing_detail(listing_id: str):
    """Get a single listing with full detail."""
    listing = get_listing(listing_id)
    if not listing:
        return {"error": "Listing not found"}, 404
    return listing


@app.get("/api/features")
async def api_features():
    """Get the list of available canonical features."""
    return FEATURE_DISPLAY_NAMES


@app.get("/api/stats")
async def api_stats():
    """Get database statistics."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        detailed = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE detail_scraped = 1"
        ).fetchone()[0]
        scored = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE deal_score IS NOT NULL"
        ).fetchone()[0]
        searches = conn.execute("SELECT COUNT(*) FROM search_history").fetchone()[0]

        makes = conn.execute(
            "SELECT make, COUNT(*) as cnt FROM listings "
            "WHERE make IS NOT NULL AND make != '' "
            "GROUP BY make ORDER BY cnt DESC LIMIT 20"
        ).fetchall()

        score_dist = conn.execute(
            """SELECT
                SUM(CASE WHEN deal_score >= 80 THEN 1 ELSE 0 END) as exceptional,
                SUM(CASE WHEN deal_score >= 65 AND deal_score < 80 THEN 1 ELSE 0 END) as great,
                SUM(CASE WHEN deal_score >= 50 AND deal_score < 65 THEN 1 ELSE 0 END) as good,
                SUM(CASE WHEN deal_score >= 35 AND deal_score < 50 THEN 1 ELSE 0 END) as fair,
                SUM(CASE WHEN deal_score < 35 THEN 1 ELSE 0 END) as below
               FROM listings WHERE deal_score IS NOT NULL"""
        ).fetchone()

    return {
        "total_listings": total,
        "detail_scraped": detailed,
        "scored": scored,
        "searches_run": searches,
        "makes": [{"make": row[0], "count": row[1]} for row in makes],
        "score_distribution": {
            "exceptional": score_dist[0] or 0,
            "great": score_dist[1] or 0,
            "good": score_dist[2] or 0,
            "fair": score_dist[3] or 0,
            "below": score_dist[4] or 0,
        },
    }


# ---------- API: Price History ----------

@app.get("/api/price-history/{listing_id}")
async def api_price_history(listing_id: str):
    """Get price history for a specific listing."""
    history = get_price_history(listing_id)
    return {"listing_id": listing_id, "history": history}


@app.get("/api/price-drops")
async def api_price_drops(
    min_drop: int = Query(default=200),
    limit: int = Query(default=50),
):
    """Get listings with the biggest price drops."""
    drops = get_price_drops(min_drop=min_drop, limit=limit)
    return {"drops": drops}


@app.get("/api/market-trend")
async def api_market_trend(
    make: str = Query(required=True),
    model: str = Query(required=True),
    year: int | None = Query(default=None),
):
    """Get average price trend for a make/model over time."""
    trend = get_market_price_trend(make, model, year)
    return {"make": make, "model": model, "year": year, "trend": trend}


# ---------- API: Watches & Alerts ----------

@app.get("/api/watches")
async def api_list_watches():
    """List all saved watches."""
    return {"watches": list_watches()}


@app.post("/api/watches")
async def api_create_watch(request: Request):
    """Create a new watch."""
    body = await request.json()
    save_watch(
        name=body.get("name", "Unnamed Watch"),
        search_params=body.get("search_params", {}),
        min_score=body.get("min_score"),
        max_price=body.get("max_price"),
        required_features=body.get("required_features"),
    )
    return {"status": "created"}


@app.delete("/api/watches/{watch_id}")
async def api_delete_watch(watch_id: int):
    """Delete a watch."""
    delete_watch(watch_id)
    return {"status": "deleted"}


@app.get("/api/alerts")
async def api_list_alerts(
    limit: int = Query(default=50),
    unread_only: bool = Query(default=False),
):
    """Get alerts."""
    alerts = get_alerts(limit=limit, unread_only=unread_only)
    return {"alerts": alerts}


@app.post("/api/alerts/read")
async def api_mark_alerts_read(request: Request):
    """Mark alerts as read."""
    body = await request.json()
    mark_alerts_read(body.get("ids"))
    return {"status": "ok"}


# ---------- API: Compare ----------

@app.get("/api/compare")
async def api_compare(ids: list[str] = Query(default=[])):
    """Get multiple listings for side-by-side comparison."""
    listings = []
    for lid in ids[:5]:  # Max 5 comparisons
        listing = get_listing(lid)
        if listing:
            listings.append(listing)
    return {"listings": listings}


# ---------- API: Dashboard ----------

@app.get("/api/dashboard")
async def api_dashboard():
    """Get dashboard data - top deals, recent listings, freshness, price drops."""
    from autotrader.processing.price_history import get_price_drops

    freshness = get_freshness_data()
    top_deals = get_top_deals(limit=10)
    new_listings = get_new_listings(hours=48, limit=10)
    drops = get_price_drops(min_drop=100, limit=10)
    unread_alerts = get_alerts(limit=100, unread_only=True)

    return {
        "freshness": freshness,
        "top_deals": top_deals,
        "new_listings": new_listings,
        "price_drops": drops,
        "unread_alert_count": len(unread_alerts),
    }


# ---------- API: Shortlist ----------

@app.get("/api/shortlist")
async def api_get_shortlist():
    """Get all shortlisted listings."""
    return {"listings": get_shortlist()}


@app.post("/api/shortlist/{listing_id}")
async def api_add_shortlist(listing_id: str, request: Request):
    """Add a listing to the shortlist."""
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    add_to_shortlist(listing_id, body.get("notes", ""))
    return {"status": "added"}


@app.delete("/api/shortlist/{listing_id}")
async def api_remove_shortlist(listing_id: str):
    """Remove a listing from the shortlist."""
    remove_from_shortlist(listing_id)
    return {"status": "removed"}


# ---------- API: Images ----------

@app.get("/api/images/{listing_id}")
async def api_listing_images(listing_id: str):
    """Get image URLs for a listing."""
    images = get_listing_images(listing_id)
    return {"listing_id": listing_id, "images": images}


# ---------- API: Similar Listings ----------

@app.get("/api/similar/{listing_id}")
async def api_similar(listing_id: str, limit: int = Query(default=10)):
    """Find similar but cheaper listings."""
    similar = find_similar_listings(listing_id, limit=limit)
    return {"listing_id": listing_id, "similar": similar}


# ---------- API: Valuation ----------

@app.get("/api/valuate")
async def api_valuate(
    make: str = Query(required=True),
    model: str = Query(required=True),
    year: int = Query(required=True),
    mileage: int = Query(required=True),
    seller_type: str = Query(default="trade"),
):
    """Calculate market valuation from scraped data."""
    from autotrader.processing.valuation import calculate_valuation
    result = calculate_valuation(make, model, year, mileage, seller_type=seller_type)
    return result


# ---------- API: Depreciation ----------

@app.get("/api/depreciation/{listing_id}")
async def api_depreciation(listing_id: str):
    """Get depreciation prediction for a listing."""
    from autotrader.processing.depreciation import predict_depreciation
    result = predict_depreciation(listing_id=listing_id)
    return result


@app.get("/api/depreciation")
async def api_depreciation_manual(
    make: str = Query(required=True),
    model: str = Query(required=True),
    year: int = Query(required=True),
    price: int = Query(required=True),
    mileage: int | None = Query(default=None),
):
    """Get depreciation prediction from manual input."""
    from autotrader.processing.depreciation import predict_depreciation
    result = predict_depreciation(
        current_price=price, make=make, model=model,
        year=year, mileage=mileage,
    )
    return result


# ---------- Export ----------

@app.get("/export/csv")
async def export_csv(
    make: str = Query(default=""),
    model: str = Query(default=""),
    year_from: int | None = Query(default=None),
    year_to: int | None = Query(default=None),
    price_from: int | None = Query(default=None),
    price_to: int | None = Query(default=None),
    mileage_max: int | None = Query(default=None),
    fuel_type: str = Query(default=""),
    transmission: str = Query(default=""),
    features: list[str] = Query(default=[]),
    sort_by: str = Query(default="deal_score"),
    sort_order: str = Query(default="DESC"),
):
    """Export filtered results as CSV."""
    listings = _parse_listing_params(
        make, model, year_from, year_to, price_from, price_to,
        mileage_max, fuel_type, transmission, features, sort_by, sort_order, 500,
    )

    csv_fields = [
        "id", "title", "price", "year", "mileage", "fuel_type", "transmission",
        "body_type", "colour", "seller_type", "seller_name", "location",
        "at_deal_rating", "deal_score", "deal_explanation", "days_on_market",
        "price_dropped", "price_drop_amount", "features_normalised", "url",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=csv_fields, extrasaction="ignore")
    writer.writeheader()
    for listing in listings:
        row = {k: listing.get(k, "") for k in csv_fields}
        if isinstance(row.get("features_normalised"), list):
            row["features_normalised"] = ", ".join(row["features_normalised"])
        writer.writerow(row)

    output.seek(0)
    filename = f"autotrader_deals_{make or 'all'}_{model or 'all'}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/export/json")
async def export_json(
    make: str = Query(default=""),
    model: str = Query(default=""),
    year_from: int | None = Query(default=None),
    year_to: int | None = Query(default=None),
    price_from: int | None = Query(default=None),
    price_to: int | None = Query(default=None),
    mileage_max: int | None = Query(default=None),
    fuel_type: str = Query(default=""),
    transmission: str = Query(default=""),
    features: list[str] = Query(default=[]),
    sort_by: str = Query(default="deal_score"),
    sort_order: str = Query(default="DESC"),
):
    """Export filtered results as JSON."""
    listings = _parse_listing_params(
        make, model, year_from, year_to, price_from, price_to,
        mileage_max, fuel_type, transmission, features, sort_by, sort_order, 500,
    )

    filename = f"autotrader_deals_{make or 'all'}_{model or 'all'}.json"
    content = json.dumps(listings, indent=2, default=str)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

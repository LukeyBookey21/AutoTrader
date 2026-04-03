"""FastAPI web application for browsing and filtering scraped listings."""

import csv
import io
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from autotrader.processing.normaliser import FEATURE_DISPLAY_NAMES
from autotrader.storage.database import get_listing, init_db, search_listings

logger = logging.getLogger(__name__)

app = FastAPI(title="AutoTrader Deal Finder", version="1.0.0")

# Static files and templates
_web_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(_web_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(_web_dir / "templates"))


@app.on_event("startup")
async def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Search form page."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "features": FEATURE_DISPLAY_NAMES,
        },
    )


@app.get("/results", response_class=HTMLResponse)
async def results(
    request: Request,
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
    """Results page with filtering and sorting."""
    listings = search_listings(
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
    )

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "listings": listings,
            "count": len(listings),
            "features_available": FEATURE_DISPLAY_NAMES,
            "selected_features": features,
            # Pass search params back for the form
            "params": {
                "make": make,
                "model": model,
                "year_from": year_from,
                "year_to": year_to,
                "price_from": price_from,
                "price_to": price_to,
                "mileage_max": mileage_max,
                "fuel_type": fuel_type,
                "transmission": transmission,
                "sort_by": sort_by,
                "sort_order": sort_order,
            },
        },
    )


@app.get("/listing/{listing_id}", response_class=HTMLResponse)
async def listing_detail(request: Request, listing_id: str):
    """Detail view for a single listing."""
    listing = get_listing(listing_id)
    if not listing:
        return HTMLResponse(content="Listing not found", status_code=404)

    return templates.TemplateResponse(
        "detail.html",
        {
            "request": request,
            "listing": listing,
            "features": FEATURE_DISPLAY_NAMES,
        },
    )


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
    listings = search_listings(
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
        # Convert lists to strings for CSV
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
    listings = search_listings(
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
    )

    filename = f"autotrader_deals_{make or 'all'}_{model or 'all'}.json"
    content = json.dumps(listings, indent=2, default=str)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
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
):
    """JSON API endpoint for listings."""
    listings = search_listings(
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
    )
    return {"count": len(listings), "listings": listings}

"""Search results scraper - scrapes AutoTrader search pages for listing summaries."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from autotrader.config import BASE_URL, MAX_PAGES, SEARCH_URL
from autotrader.scraper.browser import close_browser, extract_next_data, fetch_page
from autotrader.storage.database import save_search_history, upsert_listings

logger = logging.getLogger(__name__)


def build_search_url(params: dict[str, Any]) -> str:
    """Build an AutoTrader search URL from parameters."""
    url_params = {}

    param_mapping = {
        "postcode": "postcode",
        "make": "make",
        "model": "model",
        "year_from": "year-from",
        "year_to": "year-to",
        "price_from": "price-from",
        "price_to": "price-to",
        "mileage_max": "maximum-mileage",
        "fuel_type": "fuel-type",
        "transmission": "transmission",
        "body_type": "body-type",
        "colour": "colour",
        "doors": "doors",
        "seller_type": "seller-type",
        "sort": "sort",
        "radius": "radius",
    }

    for py_key, url_key in param_mapping.items():
        if params.get(py_key):
            url_params[url_key] = params[py_key]

    # Default sort by relevance
    if "sort" not in url_params:
        url_params["sort"] = "relevance"

    return f"{SEARCH_URL}?{urlencode(url_params)}"


def _parse_search_results_from_next_data(data: dict) -> list[dict]:
    """Extract listing summaries from __NEXT_DATA__ JSON."""
    listings = []

    try:
        # Navigate the Next.js data structure
        page_props = data.get("props", {}).get("pageProps", {})

        # Try different known paths for search results
        search_results = (
            page_props.get("results", [])
            or page_props.get("searchResults", [])
            or page_props.get("listings", [])
        )

        # If results are nested under a data key
        if not search_results and "data" in page_props:
            search_results = page_props["data"].get("results", [])

        # Try the Apollo/GraphQL cache pattern
        if not search_results:
            for key, value in page_props.items():
                if isinstance(value, dict) and "results" in value:
                    search_results = value["results"]
                    break

        for item in search_results:
            listing = _parse_single_search_result(item)
            if listing:
                listings.append(listing)

    except Exception as e:
        logger.error(f"Error parsing __NEXT_DATA__ search results: {e}")

    return listings


def _parse_single_search_result(item: dict) -> dict | None:
    """Parse a single search result item into our listing format."""
    try:
        listing_id = str(
            item.get("id", "")
            or item.get("advertId", "")
            or item.get("advertisementId", "")
        )
        if not listing_id:
            return None

        # Price extraction - handle nested structures
        price = item.get("price")
        if isinstance(price, dict):
            price = price.get("amountGBP") or price.get("amount")
        if isinstance(price, str):
            price = int(re.sub(r"[^\d]", "", price)) if price else None

        # Mileage extraction
        mileage = item.get("mileage")
        if isinstance(mileage, dict):
            mileage = mileage.get("mileage") or mileage.get("value")
        if isinstance(mileage, str):
            mileage = int(re.sub(r"[^\d]", "", mileage)) if mileage else None

        # Year extraction
        year = item.get("year") or item.get("registrationYear")
        if isinstance(year, str) and year.isdigit():
            year = int(year)

        # Deal rating
        deal_rating = (
            item.get("priceIndicatorRating")
            or item.get("price_indicator_rating")
            or item.get("dealRating")
        )
        if isinstance(deal_rating, dict):
            deal_rating = deal_rating.get("rating") or deal_rating.get("label")

        # Seller info
        seller = item.get("seller", {})
        if isinstance(seller, str):
            seller_name = seller
            seller_type = "unknown"
        else:
            seller_name = seller.get("name", "")
            seller_type = "trade" if seller.get("isDealer", True) else "private"

        # Location
        location = item.get("location") or item.get("sellerLocation", "")
        if isinstance(location, dict):
            location = location.get("town", "") or location.get("area", "")

        # Distance
        distance = item.get("distance")
        if isinstance(distance, dict):
            distance = distance.get("value")

        now = datetime.now(timezone.utc).isoformat()

        return {
            "id": listing_id,
            "url": f"{BASE_URL}/car-details/{listing_id}",
            "title": item.get("title", ""),
            "price": price,
            "make": item.get("make", ""),
            "model": item.get("model", ""),
            "variant": item.get("trim", "") or item.get("variant", ""),
            "year": year,
            "mileage": mileage,
            "fuel_type": item.get("fuelType", "") or item.get("fuel_type", ""),
            "transmission": item.get("transmission", "") or item.get("gearbox", ""),
            "body_type": item.get("bodyType", "") or item.get("body_type", ""),
            "engine_size": item.get("engineSize") or item.get("engine_size"),
            "colour": item.get("colour", ""),
            "seller_type": seller_type,
            "seller_name": seller_name,
            "location": location,
            "distance": distance,
            "images_count": len(item.get("images", []) or item.get("imageUrls", [])),
            "at_deal_rating": deal_rating,
            "scraped_at": now,
            "first_seen": now,
        }
    except Exception as e:
        logger.error(f"Error parsing search result: {e}")
        return None


def _parse_search_results_from_html(html: str) -> list[dict]:
    """Fallback: parse search results from HTML if __NEXT_DATA__ is unavailable."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    listings = []

    # Look for listing cards by common patterns
    cards = soup.select("[data-testid='trader-seller-listing']") or \
            soup.select("article[data-standout-type]") or \
            soup.select(".search-page__result")

    for card in cards:
        try:
            # Extract listing URL/ID
            link = card.select_one("a[href*='/car-details/']")
            if not link:
                continue
            href = link.get("href", "")
            listing_id_match = re.search(r"/car-details/(\d+)", href)
            if not listing_id_match:
                continue
            listing_id = listing_id_match.group(1)

            # Title
            title_el = card.select_one("h3") or card.select_one(".product-card-details__title")
            title = title_el.get_text(strip=True) if title_el else ""

            # Price
            price_el = card.select_one("[data-testid='search-listing-price']") or \
                       card.select_one(".product-card-pricing__price")
            price_text = price_el.get_text(strip=True) if price_el else ""
            price = int(re.sub(r"[^\d]", "", price_text)) if price_text else None

            # Key specs text
            specs_text = ""
            specs_el = card.select_one(".product-card-details__specs-list") or \
                       card.select("li")
            if specs_el:
                if hasattr(specs_el, "get_text"):
                    specs_text = specs_el.get_text(" ", strip=True)
                else:
                    specs_text = " ".join(li.get_text(strip=True) for li in specs_el)

            # Try to extract year and mileage from specs
            year_match = re.search(r"(20\d{2})", title + " " + specs_text)
            mileage_match = re.search(r"([\d,]+)\s*miles", specs_text, re.I)

            # Deal rating
            deal_el = card.select_one("[data-testid='price-indicator']") or \
                      card.select_one(".deal-rating")
            deal_rating = deal_el.get_text(strip=True) if deal_el else None

            now = datetime.now(timezone.utc).isoformat()

            listings.append({
                "id": listing_id,
                "url": f"{BASE_URL}/car-details/{listing_id}",
                "title": title,
                "price": price,
                "year": int(year_match.group(1)) if year_match else None,
                "mileage": int(mileage_match.group(1).replace(",", ""))
                    if mileage_match else None,
                "at_deal_rating": deal_rating,
                "scraped_at": now,
                "first_seen": now,
            })
        except Exception as e:
            logger.debug(f"Error parsing HTML card: {e}")
            continue

    return listings


def _get_total_pages(data: dict) -> int:
    """Extract total page count from __NEXT_DATA__."""
    try:
        page_props = data.get("props", {}).get("pageProps", {})

        # Try various paths
        pagination = (
            page_props.get("pagination", {})
            or page_props.get("paginationOutput", {})
        )
        if isinstance(pagination, dict):
            total = pagination.get("totalPages") or pagination.get("lastPage")
            if total:
                return min(int(total), MAX_PAGES)

        # Try from result count
        total_results = page_props.get("totalResults") or page_props.get("resultCount")
        if total_results:
            per_page = page_props.get("pageSize", 10)
            return min((int(total_results) + per_page - 1) // per_page, MAX_PAGES)

    except Exception as e:
        logger.debug(f"Could not determine total pages: {e}")

    return 1


async def scrape_search(params: dict[str, Any], max_pages: int | None = None) -> list[dict]:
    """Scrape AutoTrader search results for the given parameters.

    Args:
        params: Search parameters (postcode, make, model, etc.)
        max_pages: Override maximum pages to scrape (None = scrape all)

    Returns:
        List of listing dicts with basic data.
    """
    base_url = build_search_url(params)
    all_listings = []
    total_pages = 1

    try:
        for page_num in range(1, (max_pages or MAX_PAGES) + 1):
            url = f"{base_url}&page={page_num}"
            logger.info(f"Scraping search page {page_num}/{total_pages}: {url}")

            page = await fetch_page(url)
            if not page:
                logger.warning(f"Failed to load page {page_num}, stopping pagination")
                break

            try:
                # Try __NEXT_DATA__ first (preferred)
                next_data = await extract_next_data(page)
                if next_data:
                    page_listings = _parse_search_results_from_next_data(next_data)
                    if page_num == 1:
                        total_pages = min(
                            _get_total_pages(next_data),
                            max_pages or MAX_PAGES,
                        )
                        logger.info(f"Total pages to scrape: {total_pages}")
                else:
                    # Fallback to HTML parsing
                    logger.info("No __NEXT_DATA__ found, falling back to HTML parsing")
                    html = await page.content()
                    page_listings = _parse_search_results_from_html(html)

                if not page_listings:
                    logger.info(f"No listings found on page {page_num}, stopping")
                    break

                logger.info(f"Found {len(page_listings)} listings on page {page_num}")
                all_listings.extend(page_listings)

            finally:
                await page.close()

            if page_num >= total_pages:
                break

    finally:
        pass  # Don't close browser here - let caller manage lifecycle

    # Deduplicate by ID
    seen = set()
    unique_listings = []
    for listing in all_listings:
        if listing["id"] not in seen:
            seen.add(listing["id"])
            unique_listings.append(listing)

    # Save to database and record price snapshots
    if unique_listings:
        upsert_listings(unique_listings)
        save_search_history(params, len(unique_listings))

        # Record price snapshots for history tracking
        from autotrader.processing.price_history import record_price_snapshots_batch
        record_price_snapshots_batch(unique_listings)

    logger.info(f"Search complete: {len(unique_listings)} unique listings found")
    return unique_listings

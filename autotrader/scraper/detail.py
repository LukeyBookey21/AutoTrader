"""Listing detail scraper - scrapes individual listing pages for full specs."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from autotrader.config import BASE_URL
from autotrader.scraper.browser import extract_next_data, fetch_page
from autotrader.storage.database import (
    get_db,
    listing_needs_detail_scrape,
    upsert_listing,
)

logger = logging.getLogger(__name__)


def _parse_detail_from_next_data(data: dict) -> dict | None:
    """Extract full listing details from __NEXT_DATA__ JSON."""
    try:
        page_props = data.get("props", {}).get("pageProps", {})

        # The advert data may be at various paths
        advert = (
            page_props.get("advert", {})
            or page_props.get("listing", {})
            or page_props.get("vehicle", {})
            or page_props
        )

        if not advert:
            return None

        # Vehicle spec data
        vehicle = advert.get("vehicle", advert)
        spec = vehicle.get("specification", vehicle)

        # Features/equipment list
        features_raw = []

        # Try structured features
        features_section = (
            advert.get("features", [])
            or advert.get("keyFeatures", [])
            or vehicle.get("features", [])
            or spec.get("features", [])
        )

        if isinstance(features_section, list):
            for item in features_section:
                if isinstance(item, str):
                    features_raw.append(item)
                elif isinstance(item, dict):
                    # Features may be grouped by category
                    name = item.get("name", "") or item.get("feature", "")
                    if name:
                        features_raw.append(name)
                    # Also check for sub-features
                    sub_features = item.get("features", []) or item.get("items", [])
                    for sub in sub_features:
                        if isinstance(sub, str):
                            features_raw.append(sub)
                        elif isinstance(sub, dict):
                            features_raw.append(sub.get("name", "") or sub.get("feature", ""))

        # Also try the tech specs / standard equipment sections
        for key in ("techSpecs", "standardEquipment", "equipment", "specs"):
            section = advert.get(key, []) or vehicle.get(key, [])
            if isinstance(section, list):
                for item in section:
                    if isinstance(item, str):
                        features_raw.append(item)
                    elif isinstance(item, dict):
                        for sub in item.get("features", []) or item.get("items", []):
                            if isinstance(sub, str):
                                features_raw.append(sub)
                            elif isinstance(sub, dict):
                                features_raw.append(sub.get("name", ""))

        # Clean up features
        features_raw = [f.strip() for f in features_raw if f and f.strip()]

        # Description
        description = (
            advert.get("description", "")
            or advert.get("attentionGrabber", "")
            or ""
        )
        if isinstance(description, dict):
            description = description.get("text", "")

        # Price info
        price = advert.get("price")
        if isinstance(price, dict):
            price_val = price.get("amountGBP") or price.get("amount")
        else:
            price_val = price
        if isinstance(price_val, str):
            price_val = int(re.sub(r"[^\d]", "", price_val)) if price_val else None

        # Deal rating
        deal_rating = (
            advert.get("priceIndicatorRating")
            or advert.get("price_indicator_rating")
            or advert.get("priceIndicator", {}).get("rating")
        )
        if isinstance(deal_rating, dict):
            deal_rating = deal_rating.get("rating") or deal_rating.get("label")

        # Price history / drops
        price_history = advert.get("priceHistory", []) or advert.get("price_history", [])
        price_dropped = False
        price_drop_amount = None
        if isinstance(price_history, list) and len(price_history) > 1:
            try:
                prices = [
                    p.get("price", 0) or p.get("amount", 0)
                    for p in price_history
                    if isinstance(p, dict)
                ]
                prices = [int(re.sub(r"[^\d]", "", str(p))) for p in prices if p]
                if len(prices) >= 2 and prices[0] < prices[-1]:
                    price_dropped = True
                    price_drop_amount = prices[-1] - prices[0]
            except (ValueError, TypeError):
                pass

        # Days on market
        date_listed = advert.get("dateOfRegistration") or advert.get("dateListed")
        days_on_market = None
        if date_listed:
            try:
                listed_date = datetime.fromisoformat(str(date_listed).replace("Z", "+00:00"))
                days_on_market = (datetime.now(timezone.utc) - listed_date).days
            except (ValueError, TypeError):
                pass

        # Seller info
        seller = advert.get("seller", {})
        if not isinstance(seller, dict):
            seller = {}

        # Images
        images = advert.get("images", []) or advert.get("imageUrls", [])

        # Mileage
        mileage = (
            spec.get("mileage")
            or vehicle.get("mileage")
            or advert.get("mileage")
        )
        if isinstance(mileage, dict):
            mileage = mileage.get("mileage") or mileage.get("value")
        if isinstance(mileage, str):
            mileage = int(re.sub(r"[^\d]", "", mileage)) if mileage else None

        return {
            "title": advert.get("title", ""),
            "price": price_val,
            "make": spec.get("make", "") or vehicle.get("make", ""),
            "model": spec.get("model", "") or vehicle.get("model", ""),
            "variant": spec.get("trim", "") or spec.get("variant", "") or vehicle.get("trim", ""),
            "year": spec.get("year") or vehicle.get("year") or advert.get("year"),
            "mileage": mileage,
            "fuel_type": spec.get("fuelType", "") or vehicle.get("fuelType", ""),
            "transmission": spec.get("transmission", "") or vehicle.get("transmission", ""),
            "body_type": spec.get("bodyType", "") or vehicle.get("bodyType", ""),
            "engine_size": spec.get("engineSize") or vehicle.get("engineSize"),
            "doors": spec.get("doors") or vehicle.get("doors"),
            "colour": spec.get("colour", "") or vehicle.get("colour", ""),
            "seller_type": "trade" if seller.get("isDealer", True) else "private",
            "seller_name": seller.get("name", ""),
            "location": seller.get("location", {}).get("town", "") if isinstance(seller.get("location"), dict) else str(seller.get("location", "")),
            "images_count": len(images) if isinstance(images, list) else 0,
            "description": description,
            "at_deal_rating": deal_rating,
            "days_on_market": days_on_market,
            "price_dropped": 1 if price_dropped else 0,
            "price_drop_amount": price_drop_amount,
            "features_raw": features_raw,
            "detail_scraped": 1,
        }
    except Exception as e:
        logger.error(f"Error parsing detail __NEXT_DATA__: {e}")
        return None


def _parse_detail_from_html(html: str) -> dict | None:
    """Fallback: parse listing details from HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    result = {}

    try:
        # Title
        title_el = soup.select_one("h1")
        if title_el:
            result["title"] = title_el.get_text(strip=True)

        # Price
        price_el = (
            soup.select_one("[data-testid='advert-price']")
            or soup.select_one(".advert-heading__price")
        )
        if price_el:
            price_text = price_el.get_text(strip=True)
            price_match = re.search(r"[\d,]+", price_text)
            if price_match:
                result["price"] = int(price_match.group().replace(",", ""))

        # Key specs
        spec_items = soup.select("[data-testid='key-spec-item']") or \
                     soup.select(".key-specifications li")
        for item in spec_items:
            text = item.get_text(strip=True).lower()
            if "mile" in text:
                m = re.search(r"([\d,]+)", text)
                if m:
                    result["mileage"] = int(m.group(1).replace(",", ""))
            elif any(f in text for f in ("petrol", "diesel", "electric", "hybrid")):
                result["fuel_type"] = item.get_text(strip=True)
            elif any(t in text for t in ("automatic", "manual")):
                result["transmission"] = item.get_text(strip=True)

        # Features list
        features_raw = []
        feature_sections = soup.select("[data-testid='feature-item']") or \
                           soup.select(".feature-list li")
        for feat in feature_sections:
            text = feat.get_text(strip=True)
            if text:
                features_raw.append(text)

        result["features_raw"] = features_raw

        # Deal rating
        deal_el = soup.select_one("[data-testid='price-indicator-label']") or \
                  soup.select_one(".price-indicator__label")
        if deal_el:
            result["at_deal_rating"] = deal_el.get_text(strip=True)

        # Description
        desc_el = soup.select_one("[data-testid='advert-description']") or \
                  soup.select_one(".advert-description")
        if desc_el:
            result["description"] = desc_el.get_text(strip=True)

        result["detail_scraped"] = 1
        return result if len(result) > 2 else None

    except Exception as e:
        logger.error(f"Error parsing HTML detail page: {e}")
        return None


async def scrape_listing_detail(listing_id: str) -> dict | None:
    """Scrape full details for a single listing.

    Args:
        listing_id: The AutoTrader listing ID.

    Returns:
        Dict of listing detail fields, or None if failed.
    """
    if not listing_needs_detail_scrape(listing_id):
        logger.debug(f"Listing {listing_id} is cached, skipping detail scrape")
        return None

    url = f"{BASE_URL}/car-details/{listing_id}"
    page = await fetch_page(url)
    if not page:
        return None

    try:
        detail = None

        # Try __NEXT_DATA__ first
        next_data = await extract_next_data(page)
        if next_data:
            detail = _parse_detail_from_next_data(next_data)

        # Fallback to HTML
        if not detail:
            html = await page.content()
            detail = _parse_detail_from_html(html)

        if detail:
            detail["id"] = listing_id
            detail["url"] = url
            detail["scraped_at"] = datetime.now(timezone.utc).isoformat()

            # Save to database
            with get_db() as conn:
                upsert_listing(conn, detail)

            logger.info(f"Scraped detail for listing {listing_id}: "
                        f"{len(detail.get('features_raw', []))} features found")
            return detail

        logger.warning(f"Could not extract details for listing {listing_id}")
        return None

    finally:
        await page.close()


async def scrape_listing_details_batch(
    listing_ids: list[str],
    max_listings: int | None = None,
) -> list[dict]:
    """Scrape details for multiple listings.

    Args:
        listing_ids: List of listing IDs to scrape.
        max_listings: Optional cap on how many to scrape.

    Returns:
        List of detail dicts for successfully scraped listings.
    """
    results = []
    ids_to_scrape = listing_ids[:max_listings] if max_listings else listing_ids

    # Filter to only those needing scraping
    ids_needing_scrape = [
        lid for lid in ids_to_scrape if listing_needs_detail_scrape(lid)
    ]

    logger.info(
        f"Detail scraping: {len(ids_needing_scrape)} of {len(ids_to_scrape)} "
        f"listings need updating"
    )

    for i, listing_id in enumerate(ids_needing_scrape):
        logger.info(
            f"Scraping detail {i + 1}/{len(ids_needing_scrape)}: {listing_id}"
        )
        detail = await scrape_listing_detail(listing_id)
        if detail:
            results.append(detail)

    logger.info(f"Detail scraping complete: {len(results)} listings enriched")
    return results

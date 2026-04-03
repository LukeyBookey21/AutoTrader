"""MOT history integration using the DVLA MOT History API.

The DVLA provides a free public API for MOT test history at:
https://dvsa.github.io/mot-history-api-documentation/

Requires a free API key from https://dvsa.github.io/mot-history-api-documentation/
Set the key via environment variable: DVLA_MOT_API_KEY
"""

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from autotrader.storage.database import get_db

logger = logging.getLogger(__name__)

MOT_API_BASE = "https://beta.check-mot.service.gov.uk"
MOT_API_KEY = os.environ.get("DVLA_MOT_API_KEY", "")


def _extract_registration(title: str, description: str = "") -> str | None:
    """Try to extract a UK registration number from title or description."""
    combined = f"{title} {description}"
    # UK reg patterns: AB12 CDE, AB12CDE, A123 BCD, etc.
    patterns = [
        r"\b([A-Z]{2}\d{2}\s?[A-Z]{3})\b",  # New style: AB12 CDE
        r"\b([A-Z]\d{3}\s?[A-Z]{3})\b",      # Prefix style: A123 BCD
        r"\b([A-Z]{3}\s?\d{3}[A-Z])\b",       # Suffix style: ABC 123D
    ]
    for pattern in patterns:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            return match.group(1).upper().replace(" ", "")
    return None


async def fetch_mot_history(registration: str) -> dict[str, Any] | None:
    """Fetch MOT history for a vehicle from the DVLA API.

    Args:
        registration: UK vehicle registration number (e.g. "AB12CDE").

    Returns:
        Dict with MOT summary data, or None if unavailable.
    """
    if not MOT_API_KEY:
        logger.debug("No DVLA_MOT_API_KEY set, skipping MOT check")
        return None

    url = f"{MOT_API_BASE}/trade/vehicles/mot-tests"
    headers = {
        "Accept": "application/json+v6",
        "x-api-key": MOT_API_KEY,
    }
    params = {"registration": registration.replace(" ", "")}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers, params=params)

        if response.status_code == 404:
            logger.debug(f"No MOT data found for {registration}")
            return None

        if response.status_code != 200:
            logger.warning(f"MOT API returned {response.status_code} for {registration}")
            return None

        data = response.json()
        if not data:
            return None

        # The API returns a list; take the first (most recent) vehicle record
        vehicle = data[0] if isinstance(data, list) else data
        return _summarise_mot_history(vehicle)

    except Exception as e:
        logger.error(f"Error fetching MOT history for {registration}: {e}")
        return None


def _summarise_mot_history(vehicle: dict) -> dict[str, Any]:
    """Summarise MOT history into a useful scoring-ready format."""
    mot_tests = vehicle.get("motTests", [])

    total_tests = len(mot_tests)
    passes = sum(1 for t in mot_tests if t.get("testResult") == "PASSED")
    failures = total_tests - passes

    # Collect all advisories and failure items
    all_advisories = []
    all_failures = []
    for test in mot_tests:
        for defect in test.get("defects", []) or test.get("rfrAndComments", []):
            text = defect.get("text", "") or defect.get("comment", "")
            dtype = defect.get("type", "").upper()
            if "ADVISORY" in dtype or "ADVISORY" in text.upper():
                all_advisories.append(text)
            elif "FAIL" in dtype or "MAJOR" in dtype or "DANGEROUS" in dtype:
                all_failures.append(text)
            else:
                all_advisories.append(text)

    # Mileage history from MOT tests (useful for verifying listed mileage)
    mileage_readings = []
    for test in mot_tests:
        odometer = test.get("odometerValue")
        test_date = test.get("completedDate", "")
        if odometer and str(odometer).isdigit():
            mileage_readings.append({
                "mileage": int(odometer),
                "date": test_date,
            })

    # Check for mileage discrepancies (rollback)
    mileage_consistent = True
    if len(mileage_readings) >= 2:
        for i in range(len(mileage_readings) - 1):
            if mileage_readings[i]["mileage"] < mileage_readings[i + 1]["mileage"] - 1000:
                # Current reading less than previous (allowing small tolerance)
                mileage_consistent = False
                break

    # Most recent test
    latest_test = mot_tests[0] if mot_tests else None
    latest_result = latest_test.get("testResult", "") if latest_test else ""
    expiry_date = latest_test.get("expiryDate", "") if latest_test else ""

    return {
        "registration": vehicle.get("registration", ""),
        "make": vehicle.get("make", ""),
        "model": vehicle.get("model", ""),
        "first_used_date": vehicle.get("firstUsedDate", ""),
        "fuel_type": vehicle.get("fuelType", ""),
        "colour": vehicle.get("primaryColour", ""),
        "total_mot_tests": total_tests,
        "mot_passes": passes,
        "mot_failures": failures,
        "mot_pass_rate": round(passes / total_tests * 100, 1) if total_tests > 0 else None,
        "latest_result": latest_result,
        "mot_expiry": expiry_date,
        "total_advisories": len(all_advisories),
        "total_failure_items": len(all_failures),
        "recent_advisories": all_advisories[:10],
        "mileage_readings": mileage_readings[:10],
        "mileage_consistent": mileage_consistent,
    }


def save_mot_data(listing_id: str, mot_data: dict):
    """Save MOT data to the listing record."""
    import json
    with get_db() as conn:
        conn.execute(
            "UPDATE listings SET mot_data = ? WHERE id = ?",
            (json.dumps(mot_data), listing_id),
        )


async def check_mot_for_listing(listing: dict) -> dict | None:
    """Try to check MOT history for a listing.

    Attempts to extract registration from listing title/description,
    then fetches MOT history.
    """
    reg = _extract_registration(
        listing.get("title", ""),
        listing.get("description", ""),
    )
    if not reg:
        return None

    mot_data = await fetch_mot_history(reg)
    if mot_data:
        save_mot_data(listing["id"], mot_data)
    return mot_data

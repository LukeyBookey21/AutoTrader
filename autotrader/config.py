"""Configuration constants for the AutoTrader scraper."""

import os
from pathlib import Path

# Base URLs
BASE_URL = "https://www.autotrader.co.uk"
SEARCH_URL = f"{BASE_URL}/car-search"
DETAIL_URL = f"{BASE_URL}/car-details"

# Database
DB_PATH = os.environ.get(
    "AUTOTRADER_DB_PATH",
    str(Path(__file__).parent.parent / "data" / "autotrader.db"),
)

# Scraping settings
REQUEST_DELAY_SECONDS = float(os.environ.get("AUTOTRADER_DELAY", "3.0"))
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5  # seconds, exponential backoff: 5, 15, 45
CACHE_TTL_HOURS = 24  # skip re-scraping listings newer than this
SEARCH_CACHE_TTL_HOURS = 1
MAX_PAGES = 50  # safety cap on pagination
HEADLESS = os.environ.get("AUTOTRADER_HEADLESS", "true").lower() == "true"

# Web UI
WEB_HOST = os.environ.get("AUTOTRADER_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("AUTOTRADER_PORT", "8000"))

# Deal scoring - spec uplift values in GBP (how much the feature adds to fair value)
SPEC_UPLIFT = {
    "panoramic_roof": 800,
    "sunroof": 500,
    "heated_seats_front": 300,
    "heated_seats_rear": 200,
    "ventilated_seats": 300,
    "leather_interior": 500,
    "adaptive_cruise_control": 400,
    "parking_camera": 300,
    "parking_sensors_front_rear": 200,
    "parking_sensors_rear": 100,
    "keyless_entry": 200,
    "apple_carplay": 200,
    "android_auto": 150,
    "heads_up_display": 400,
    "harman_kardon_audio": 300,
    "bose_audio": 300,
    "bang_olufsen_audio": 400,
    "meridian_audio": 350,
    "electric_tailgate": 200,
    "heated_steering_wheel": 150,
    "digital_cockpit": 200,
    "matrix_led_headlights": 250,
    "ambient_lighting": 100,
    "wireless_charging": 100,
    "four_wheel_drive": 500,
    "air_suspension": 600,
    "360_camera": 400,
    "blind_spot_monitoring": 200,
    "lane_assist": 150,
    "auto_parking": 250,
}

# Proxy settings
# Comma-separated list of proxy URLs, e.g. "http://proxy1:8080,http://proxy2:8080"
# Or a single proxy URL. Supports http, https, socks5 protocols.
PROXY_LIST = [
    p.strip() for p in os.environ.get("AUTOTRADER_PROXIES", "").split(",") if p.strip()
]
PROXY_USERNAME = os.environ.get("AUTOTRADER_PROXY_USER", "")
PROXY_PASSWORD = os.environ.get("AUTOTRADER_PROXY_PASS", "")

# Average annual mileage for UK cars (used in scoring)
AVERAGE_ANNUAL_MILEAGE = 8000

# Mileage bands for market stats
MILEAGE_BANDS = [
    (0, 10000, "0-10k"),
    (10000, 20000, "10k-20k"),
    (20000, 40000, "20k-40k"),
    (40000, 60000, "40k-60k"),
    (60000, 80000, "60k-80k"),
    (80000, 100000, "80k-100k"),
    (100000, 150000, "100k-150k"),
    (150000, 999999, "150k+"),
]


def get_mileage_band(mileage: int) -> str:
    """Return the mileage band label for a given mileage."""
    for low, high, label in MILEAGE_BANDS:
        if low <= mileage < high:
            return label
    return "150k+"

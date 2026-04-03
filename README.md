# AutoTrader Deal Finder

A Python application that scrapes AutoTrader UK listings, normalises vehicle spec data, and scores deals using a proprietary algorithm. Filter by features that AutoTrader's own search doesn't support (e.g. heated seats, panoramic roof, specific audio systems).

**For personal, non-commercial use only.**

## Features

- **Search scraper** - Scrape AutoTrader search results with full parameter support
- **Detail scraper** - Extract full specs, features, and deal ratings from listing pages
- **Spec normalisation** - Map inconsistent feature names to canonical keys (e.g. "Heated front seats" / "Front seat heating" -> `heated_seats_front`)
- **Deal scoring** - 0-100 score based on price vs market, mileage value, spec uplift, and market signals
- **Web UI** - Local web interface with sortable tables, feature filtering, and export
- **CLI** - Full command-line interface for all operations
- **Export** - CSV and JSON export of filtered results

## Quick Start

### 1. Install

```bash
# Clone and install
cd AutoTrader
pip install -e .

# Install Playwright browser (required)
playwright install chromium
```

### 2. Run a Search

```bash
# Basic search
autotrader search --postcode SW1A1AA --make BMW --model "3 Series" --year-from 2019 --price-to 25000

# With more filters
autotrader search \
  --postcode M11AA \
  --make Audi \
  --model A4 \
  --year-from 2020 \
  --year-to 2023 \
  --fuel-type Diesel \
  --transmission Automatic \
  --mileage-max 50000 \
  --max-pages 5
```

### 3. Process & Score

```bash
# Normalise features, compute market stats, and score deals
autotrader process

# Or filter to specific make/model
autotrader process --make BMW --model "3 Series"
```

### 4. View Results

```bash
# Table view (top 20 deals)
autotrader results --make BMW --min-score 60

# With feature filter
autotrader results --make BMW --features heated_seats_front --features panoramic_roof

# JSON output
autotrader results --make BMW --format json

# CSV output
autotrader results --format csv > deals.csv
```

### 5. Web UI

```bash
# Start the local web server
autotrader web

# Then open http://127.0.0.1:8000 in your browser
```

### 6. Database Stats

```bash
autotrader stats
```

## Architecture

```
autotrader/
├── scraper/
│   ├── browser.py      # Playwright browser with stealth & rate limiting
│   ├── search.py       # Search results scraper
│   └── detail.py       # Listing detail scraper
├── processing/
│   ├── normaliser.py   # Feature name normalisation
│   ├── market.py       # Market statistics computation
│   └── scorer.py       # Deal scoring engine (0-100)
├── storage/
│   └── database.py     # SQLite operations
├── web/
│   ├── app.py          # FastAPI web application
│   ├── templates/      # Jinja2 HTML templates
│   └── static/         # CSS
├── cli.py              # Click CLI entry point
└── config.py           # Configuration constants
```

## Deal Scoring Algorithm

Each listing is scored 0-100 across four components:

| Component | Points | What It Measures |
|-----------|--------|-----------------|
| Price vs Market | 0-50 | How the price compares to median for same make/model/year/mileage |
| Mileage Value | 0-15 | Whether mileage is below/above average for the car's age |
| Spec Uplift | 0-15 | Value of premium features relative to price |
| Market Signals | 0-20 | Price drops, days listed, seller type, AutoTrader rating |

### Score Ranges
- **80+** Exceptional Deal
- **65-79** Great Deal
- **50-64** Good Deal
- **35-49** Fair Deal
- **0-34** Below Average

## Filterable Features

The normaliser maps dozens of naming variations to these canonical keys:

| Key | Feature |
|-----|---------|
| `panoramic_roof` | Panoramic Roof |
| `heated_seats_front` | Heated Front Seats |
| `heated_seats_rear` | Heated Rear Seats |
| `leather_interior` | Leather Interior |
| `adaptive_cruise_control` | Adaptive Cruise Control |
| `parking_camera` | Parking Camera |
| `360_camera` | 360 Camera |
| `apple_carplay` | Apple CarPlay |
| `keyless_entry` | Keyless Entry |
| `heads_up_display` | Heads-Up Display |
| `harman_kardon_audio` | Harman Kardon Audio |
| `electric_tailgate` | Electric Tailgate |
| ... | [See normaliser.py for full list] |

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTOTRADER_DB_PATH` | `data/autotrader.db` | SQLite database path |
| `AUTOTRADER_DELAY` | `3.0` | Seconds between requests |
| `AUTOTRADER_HEADLESS` | `true` | Run browser headless |
| `AUTOTRADER_HOST` | `127.0.0.1` | Web UI host |
| `AUTOTRADER_PORT` | `8000` | Web UI port |

Spec uplift values and scoring parameters can be adjusted in `autotrader/config.py`.

## Legal Disclaimer

This tool is provided for **personal, educational use only**. Scraping AutoTrader may violate their Terms of Service. The authors accept no liability for misuse. Users should:

- Use responsibly with conservative rate limits
- Not redistribute scraped data
- Not use for commercial purposes
- Verify all data directly on AutoTrader before making purchasing decisions
- Respect robots.txt and rate limits

# AutoTrader Deal Finder

A Python application that scrapes AutoTrader UK listings, normalises vehicle spec data, and scores deals using a proprietary algorithm. Filter by features that AutoTrader's own search doesn't support.

**For personal, non-commercial use only.**

## Features

- **Search scraper** - Scrape AutoTrader search results with full parameter support
- **Detail scraper** - Extract full specs, features, and deal ratings from listing pages
- **Spec normalisation** - Maps inconsistent feature names to canonical keys using:
  - Structured feature list parsing
  - **Description text mining** - Extracts features from free-text seller descriptions
  - **Trim-level inference** - Infers standard features from trim names (e.g. "M Sport" implies leather, sat nav, etc.)
- **Deal scoring** - 0-100 score based on price vs market, mileage value, spec uplift, and market signals
- **Modern SPA web UI** - Alpine.js + Tailwind CSS with:
  - Interactive sortable/filterable results table
  - Side-by-side listing comparison (2-5 cars)
  - Chart.js score distribution and market charts
  - Feature checkbox filtering
  - Export to CSV/JSON
  - Mobile-responsive design
- **Price monitoring & alerts** - Save searches as watches, get alerts for new listings and price drops
- **Price history tracking** - Records price snapshots over time, detects drops
- **MOT history integration** - Free DVLA API check for MOT pass rates, advisories, mileage consistency
- **Proxy rotation** - Configurable proxy list with automatic rotation
- **CLI** - Full command-line interface for all operations
- **Docker** - One-command deployment with docker-compose

## Quick Start

### Option 1: pip install

```bash
cd AutoTrader
pip install -e .
playwright install chromium
```

### Option 2: Docker

```bash
docker-compose up --build
# Web UI at http://localhost:8000

# Run scrapes inside the container:
docker-compose exec autotrader autotrader search --postcode SW1A1AA --make BMW --model "3 Series"
docker-compose exec autotrader autotrader process
```

## Usage

### 1. Scrape Listings

```bash
autotrader search --postcode SW1A1AA --make BMW --model "3 Series" --year-from 2019 --price-to 25000

# More filters
autotrader search \
  --postcode M11AA \
  --make Audi --model A4 \
  --year-from 2020 --year-to 2023 \
  --fuel-type Diesel --transmission Automatic \
  --mileage-max 50000 --max-pages 5
```

### 2. Process & Score

```bash
autotrader process                          # All listings
autotrader process --make BMW               # Filter by make
autotrader process --make Audi --model A4   # Filter by make+model
```

Processing now includes text mining + trim-level feature inference.

### 3. View Results

```bash
autotrader results --min-score 60
autotrader results --features panoramic_roof --features heated_seats_front
autotrader results --format csv > deals.csv
autotrader results --format json
```

### 4. Web UI

```bash
autotrader web
# Open http://127.0.0.1:8000
```

Features: interactive table, feature filters, comparison mode, score charts, price drop tracking, watch management.

### 5. Price Monitoring

```bash
# Save a watch
autotrader watch --name "BMW 3 Series deals" --make BMW --model "3 Series" --min-score 50

# List watches
autotrader watches

# Start monitoring (checks every 30 min)
autotrader monitor --interval 30
```

### 6. MOT History Check

```bash
# Set your free DVLA API key
export DVLA_MOT_API_KEY=your_key_here

# Check MOT for scraped listings
autotrader mot-check --make BMW --max-checks 20
```

Get a free API key at: https://dvsa.github.io/mot-history-api-documentation/

### 7. Database Stats

```bash
autotrader stats
```

## Architecture

```
autotrader/
├── scraper/
│   ├── browser.py      # Playwright + stealth + proxy rotation
│   ├── search.py       # Search results scraper
│   └── detail.py       # Listing detail scraper
├── processing/
│   ├── normaliser.py   # Feature normalisation (structured + text mining)
│   ├── trim_features.py # Trim-level feature inference database
│   ├── market.py       # Market statistics
│   ├── scorer.py       # Deal scoring engine (0-100)
│   ├── mot.py          # MOT history (DVLA API)
│   └── price_history.py # Price snapshot tracking
├── storage/
│   └── database.py     # SQLite with all tables
├── web/
│   ├── app.py          # FastAPI with full REST API
│   └── static/
│       ├── index.html  # SPA (Alpine.js + Tailwind + Chart.js)
│       └── style.css   # Legacy styles
├── monitoring.py       # Watch & alert system
├── cli.py              # CLI (search, process, results, web, watch, monitor, mot-check, stats)
└── config.py           # Configuration
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTOTRADER_DB_PATH` | `data/autotrader.db` | SQLite database path |
| `AUTOTRADER_DELAY` | `3.0` | Seconds between requests |
| `AUTOTRADER_HEADLESS` | `true` | Run browser headless |
| `AUTOTRADER_HOST` | `127.0.0.1` | Web UI host |
| `AUTOTRADER_PORT` | `8000` | Web UI port |
| `AUTOTRADER_PROXIES` | `` | Comma-separated proxy URLs |
| `AUTOTRADER_PROXY_USER` | `` | Proxy username |
| `AUTOTRADER_PROXY_PASS` | `` | Proxy password |
| `DVLA_MOT_API_KEY` | `` | Free DVLA MOT API key |

## Legal Disclaimer

This tool is for **personal, educational use only**. Scraping AutoTrader may violate their Terms of Service. Users should:

- Use responsibly with conservative rate limits
- Not redistribute scraped data
- Not use for commercial purposes
- Verify all data directly on AutoTrader before making purchasing decisions

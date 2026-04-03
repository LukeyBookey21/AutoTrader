# Phase 2: Architecture Plan

## System Overview

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│   CLI /      │────>│  Search      │────>│  Detail         │────>│  Spec        │
│   Web UI     │     │  Scraper     │     │  Scraper        │     │  Normaliser  │
└─────────────┘     └──────────────┘     └─────────────────┘     └──────────────┘
       │                                                                 │
       │            ┌──────────────┐     ┌─────────────────┐            │
       └───────────>│  Deal        │<────│  Market         │<───────────┘
                    │  Scorer      │     │  Analyser       │
                    └──────────────┘     └─────────────────┘
                           │
                    ┌──────────────┐
                    │  SQLite DB   │
                    └──────────────┘
```

## Tech Stack

- **Python 3.11+**
- **Playwright** (async) + playwright-stealth for browser automation
- **BeautifulSoup4** for HTML parsing fallback
- **FastAPI** + **Jinja2** for web UI
- **Click** for CLI
- **SQLite** for data storage
- **uvicorn** for ASGI server

## Data Model

### `listings` table
| Field | Type | Description |
|-------|------|-------------|
| id | TEXT PK | AutoTrader listing ID |
| url | TEXT | Full listing URL |
| title | TEXT | Listing title (e.g., "2020 BMW 3 Series 320d M Sport") |
| price | INTEGER | Asking price in GBP |
| make | TEXT | Manufacturer |
| model | TEXT | Model name |
| variant | TEXT | Trim/variant (e.g., "M Sport", "SE") |
| year | INTEGER | Registration year |
| mileage | INTEGER | Mileage in miles |
| fuel_type | TEXT | Petrol/Diesel/Electric/Hybrid |
| transmission | TEXT | Automatic/Manual |
| body_type | TEXT | Hatchback/Saloon/SUV/Estate/etc. |
| engine_size | REAL | Engine size in litres |
| doors | INTEGER | Number of doors |
| colour | TEXT | Body colour |
| seller_type | TEXT | trade/private |
| seller_name | TEXT | Dealer or seller name |
| location | TEXT | Location/town |
| distance | REAL | Distance from search postcode |
| images_count | INTEGER | Number of images |
| description | TEXT | Free-text description |
| at_deal_rating | TEXT | AutoTrader's deal rating (great/good/fair/higher) |
| deal_score | REAL | Our proprietary score (0-100) |
| deal_explanation | TEXT | Plain-English scoring explanation |
| price_when_new | INTEGER | New price if available |
| days_on_market | INTEGER | Days listed |
| price_dropped | BOOLEAN | Whether price has been reduced |
| price_drop_amount | INTEGER | Amount of price drop |
| features_raw | TEXT | JSON array of raw feature strings |
| features_normalised | TEXT | JSON array of normalised feature keys |
| scraped_at | TIMESTAMP | When this listing was last scraped |
| first_seen | TIMESTAMP | When we first found this listing |

### `search_history` table
| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER PK | Auto-increment |
| params_json | TEXT | Search parameters as JSON |
| result_count | INTEGER | Number of results found |
| searched_at | TIMESTAMP | When search was run |

### `market_stats` table
| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER PK | Auto-increment |
| make | TEXT | |
| model | TEXT | |
| year | INTEGER | |
| mileage_band | TEXT | e.g., "20k-40k" |
| avg_price | REAL | |
| median_price | REAL | |
| min_price | REAL | |
| max_price | REAL | |
| sample_count | INTEGER | |
| computed_at | TIMESTAMP | |

## Scraping Pipeline

### Step 1: Search
1. User provides search parameters via CLI or Web UI
2. Build AutoTrader search URL from parameters
3. Use Playwright to load page 1, extract `__NEXT_DATA__` JSON
4. Parse listing summaries (ID, title, price, basic info, deal rating)
5. Paginate through all result pages (respect rate limits)
6. Store basic listing data in SQLite

### Step 2: Detail Enrichment
1. For each new/stale listing, load the detail page
2. Extract `__NEXT_DATA__` JSON from detail page
3. Parse full spec data, features list, description, seller info
4. Store enriched data in SQLite

### Step 3: Spec Normalisation
1. Load raw features from each listing
2. Apply normalisation rules (fuzzy matching + canonical mapping)
3. Store normalised feature keys

### Step 4: Market Analysis
1. Aggregate listings by make/model/year/mileage band
2. Compute market statistics (avg, median, min, max prices)
3. Store in market_stats table

### Step 5: Deal Scoring
1. For each listing, compare price to market stats for its segment
2. Apply spec uplift adjustments
3. Factor in seller type, days on market, price drops
4. Compute 0-100 score with explanation

## Rate Limiting & Caching Strategy

- **Rate limit**: 1 request per 3 seconds (configurable)
- **Max concurrent pages**: 1 (sequential scraping)
- **Cache TTL**: 24 hours for listing details, 1 hour for search results
- **Deduplication**: Skip detail scraping if listing was scraped within TTL
- **Retry**: Up to 3 retries with exponential backoff (5s, 15s, 45s)
- **Session management**: Reuse browser context across requests

## Deal Scoring Algorithm

### Score Components (0-100 total)
1. **Price vs Market** (0-50 points): How far below/above market average
   - 20%+ below median = 50 points
   - 10-20% below = 40 points
   - 0-10% below = 30 points
   - 0-10% above = 15 points
   - 10%+ above = 0 points

2. **Mileage Value** (0-15 points): Mileage relative to average for age
   - Below average mileage = more points

3. **Spec Uplift** (0-15 points): Premium features present
   - Each premium feature adds configurable points
   - Capped at 15

4. **Market Signals** (0-20 points):
   - Price recently dropped: +5
   - Listed 30+ days (motivated seller): +5
   - Private seller (usually cheaper): +5
   - Low image count (hidden gem or red flag): +/- 2
   - AutoTrader rates as "great": +3

### Spec Uplift Values (configurable defaults)
```python
SPEC_UPLIFT = {
    "panoramic_roof": 800,
    "heated_seats_front": 300,
    "heated_seats_rear": 200,
    "leather_interior": 500,
    "adaptive_cruise_control": 400,
    "parking_camera": 300,
    "parking_sensors_front_rear": 200,
    "keyless_entry": 200,
    "apple_carplay": 200,
    "android_auto": 150,
    "sunroof": 500,
    "heads_up_display": 400,
    "harman_kardon_audio": 300,
    "electric_tailgate": 200,
    "heated_steering_wheel": 150,
    "ventilated_seats": 300,
    "digital_cockpit": 200,
    "matrix_led_headlights": 250,
}
```

## Project Structure
```
autotrader/
├── __init__.py
├── scraper/
│   ├── __init__.py
│   ├── search.py          # Search results scraper
│   ├── detail.py          # Listing detail scraper
│   └── browser.py         # Playwright browser management
├── processing/
│   ├── __init__.py
│   ├── normaliser.py      # Spec normalisation
│   ├── market.py          # Market statistics computation
│   └── scorer.py          # Deal scoring engine
├── storage/
│   ├── __init__.py
│   └── database.py        # SQLite operations
├── web/
│   ├── __init__.py
│   ├── app.py             # FastAPI application
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html     # Search form
│   │   └── results.html   # Results table
│   └── static/
│       └── style.css
├── cli.py                 # CLI entry point
└── config.py              # Configuration constants
```

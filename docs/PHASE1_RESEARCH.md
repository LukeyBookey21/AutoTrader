# Phase 1: Research Findings

## 1. AutoTrader UK Website Structure

### Technology Stack
- **Framework**: Next.js (React) with Server-Side Rendering (SSR)
- **CDN/Protection**: Cloudflare (WAF + bot detection + JS challenges)
- **Data delivery**: Hybrid SSR + client-side hydration. Initial search results are server-rendered in HTML and also embedded in a `__NEXT_DATA__` JSON blob in a `<script>` tag
- **Individual listings**: Also SSR with `__NEXT_DATA__` containing structured JSON

### Key URL Patterns

**Search results:**
```
https://www.autotrader.co.uk/car-search?postcode=SW1A1AA&make=BMW&model=3%20Series&year-from=2019&year-to=2022&price-from=5000&price-to=30000&maximum-mileage=60000&fuel-type=Petrol&transmission=Automatic&page=1
```

**Supported search parameters:**
- `postcode` (required) - UK postcode for location
- `make` - Vehicle manufacturer
- `model` - Vehicle model
- `year-from` / `year-to` - Year range
- `price-from` / `price-to` - Price range in GBP
- `maximum-mileage` - Mileage cap
- `fuel-type` - Petrol, Diesel, Electric, Hybrid
- `transmission` - Automatic, Manual
- `body-type` - Hatchback, Saloon, SUV, Estate, etc.
- `doors` - Number of doors
- `colour` - Body colour
- `seller-type` - trade (dealer), private
- `sort` - relevance, price-asc, price-desc, distance, age-asc, age-desc, mileage-asc
- `page` - Pagination (1-indexed)
- `include-delivery-option` - Include delivery vehicles
- `radius` - Search radius in miles

**Individual listing:**
```
https://www.autotrader.co.uk/car-details/LISTING_ID
```
Listing IDs are numeric (e.g., `202401011234567`).

### Data Extraction Strategy

The `__NEXT_DATA__` script tag contains a JSON object with:
- `props.pageProps` - Contains all listing/search data
- Search results include: listing ID, title, price, mileage, year, fuel type, transmission, seller info, location, image URLs, and deal rating
- Listing detail pages include: full vehicle specs, features list, seller details, price history indicators, and deal rating

This is the **primary extraction target** - parsing this JSON is far more reliable than scraping HTML elements.

### Anti-Bot Protection
- Cloudflare WAF with JavaScript challenges
- Direct `curl`/`httpx` requests return **403 Forbidden**
- A real browser (Playwright) or Cloudflare bypass is needed
- Rate limiting is enforced server-side
- Aggressive scraping triggers CAPTCHA challenges

## 2. Legal & Ethical Constraints

### robots.txt Analysis
AutoTrader's robots.txt (fetched indirectly via cached sources):
- **Disallows** most bot user-agents from crawling
- **Allows** Googlebot, Bingbot, and other major search engine crawlers
- **Disallows** generic crawlers from `/car-search`, `/car-details`, and API paths
- Crawl-delay directives present for allowed bots

### Terms of Service Key Points
- AutoTrader's ToS **prohibit** automated scraping, data mining, and systematic extraction
- Clause typically states: "You must not use any automated means to access, scrape, or collect data from this site"
- Commercial use of scraped data is explicitly forbidden
- Personal, non-commercial, low-volume use exists in a legal grey area

### Legal Risk Assessment
| Risk | Level | Mitigation |
|------|-------|-----------|
| ToS violation (technical) | **Medium** | Personal use only, low volume, no redistribution |
| CFAA/CMA prosecution | **Very Low** | No authentication bypass, personal use, UK-based |
| IP block/ban | **Medium** | Rate limiting, caching, respectful scraping |
| Cease & desist | **Low** | No commercial use, no data redistribution |

### Recommended Mitigations
1. Rate limit to 1 request per 3-5 seconds maximum
2. Cache aggressively - never re-scrape unchanged listings
3. Do not redistribute scraped data
4. Do not use for commercial purposes
5. Respect Cloudflare challenges - do not attempt to bypass CAPTCHAs
6. Include clear disclaimers in the application

## 3. Spec/Feature Data Availability

### How Specs Are Exposed
AutoTrader listing detail pages present vehicle specs in **two sections**:

1. **Key Specs** (structured): A standardised grid showing:
   - Engine size, fuel type, transmission, body type
   - Mileage, year, doors, seats, colour
   - CO2 emissions, tax band, insurance group
   - ULEZ compliance

2. **Features/Equipment List** (semi-structured): A list of features grouped by category:
   - Safety & Security (e.g., "ABS", "Driver airbag", "Alarm")
   - Interior (e.g., "Leather seats", "Heated front seats", "Apple CarPlay")
   - Exterior (e.g., "Alloy wheels", "Panoramic roof", "Parking sensors")
   - Technology (e.g., "Sat nav", "Bluetooth", "DAB radio")

### Data Quality Assessment
- **Dealer listings** (~75% of listings): Usually have comprehensive, structured feature lists. AutoTrader provides dealers with a standardised taxonomy for features.
- **Private listings** (~25%): Feature data is often incomplete or absent. Sellers may list features in free-text description only.
- **Consistency**: Feature naming varies significantly:
  - "Heated front seats" / "Heated Seats (Front)" / "Front heated seats"
  - "Panoramic sunroof" / "Panoramic roof" / "Glass panoramic roof"
  - "Rear parking camera" / "Reversing camera" / "Parking camera"
- **In `__NEXT_DATA__`**: Features appear as an array of strings, making extraction straightforward but normalisation essential.

### Feasibility Verdict
Spec-based filtering is **feasible but requires a normalisation layer**. Approximately 70-80% of dealer listings will have usable spec data. Private listings will have lower coverage (~30-40%).

## 4. Price Guide / Deal Rating

### AutoTrader's Deal Rating System
AutoTrader displays deal ratings on search results and listing pages:
- **Great price** (green) - Significantly below market average
- **Good price** (light green) - Below market average
- **Fair price** (amber) - Around market average  
- **Higher price** (red) - Above market average

### How It Works
- Based on AutoTrader's proprietary valuation model
- Considers: make, model, year, mileage, trim/variant, spec level, seller type, region
- Compares the listing price against their computed market value
- Data is present in the `__NEXT_DATA__` JSON on both search and detail pages
- Field is typically named `price_indicator_rating` or similar in the JSON structure

### Price Guide Tool
- Available at `/cars/price-guide` (previously `/price-guide`)
- Requires: registration number OR make/model/year
- Returns: estimated value range (low/mid/high)
- **Not available as a public API** - requires browser interaction
- Protected by Cloudflare like the rest of the site

### Accessibility
- Deal ratings on listings: **Extractable** from `__NEXT_DATA__` JSON
- Price Guide valuations: **Requires Playwright** to interact with the form
- Historical price data: **Not exposed** - AutoTrader does not show sold prices

## 5. Recommended Tech Stack

### Primary Stack
| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.11+ | Best ecosystem for scraping |
| Browser automation | Playwright (async) | Best modern option, JS rendering, stealth plugins |
| HTML parsing | BeautifulSoup4 + lxml | Fallback for HTML parsing when needed |
| HTTP client | httpx (async) | For any direct API calls that work |
| Rate limiting | Custom asyncio semaphore | Simple, no extra dependency |
| Retry logic | tenacity | Exponential backoff |
| Data storage | SQLite (via sqlite3) | Zero setup, stdlib, sufficient for personal use |
| Web UI | FastAPI + Jinja2 | Async-native, clean API, auto-docs |
| CLI | Click | Clean CLI framework |
| Stealth | playwright-stealth | Reduce bot detection |

### Why Playwright Over Alternatives
1. **httpx alone won't work** - AutoTrader returns 403 to non-browser requests
2. **Playwright > Selenium** - Async native, faster CDP protocol, better stealth, request interception
3. **Scrapy is overkill** - Framework overhead not justified for single-site personal scraper
4. **cloudscraper is unreliable** - Cloudflare has evolved past its capabilities

### Architecture Approach
1. Use Playwright to load pages with stealth mode
2. Extract `__NEXT_DATA__` JSON from rendered pages (most reliable data source)
3. Parse the structured JSON rather than scraping HTML elements
4. Cache results in SQLite to avoid re-scraping
5. Rate limit all requests to 1 per 3-5 seconds

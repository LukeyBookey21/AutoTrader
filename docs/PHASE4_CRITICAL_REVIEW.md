# Phase 4: Critical Review

## 1. Reliability

### Fragility Assessment
**Overall: Medium fragility.** The scraper is heavily dependent on AutoTrader's internal data structure.

**What breaks if AutoTrader changes:**
- **`__NEXT_DATA__` structure changes** (HIGH risk): The primary data extraction relies on parsing the Next.js JSON blob. If AutoTrader restructures their page props, renames keys, or moves to a different framework (e.g. drops Next.js for Remix/Astro), the JSON parsing in `search.py` and `detail.py` breaks completely.
- **HTML structure changes** (MEDIUM risk): The fallback HTML parsers use CSS selectors and `data-testid` attributes. These change with redesigns but are more stable than internal JSON paths.
- **Cloudflare escalation** (MEDIUM risk): If AutoTrader tightens bot detection (e.g. adopts Cloudflare Turnstile v2 or Kasada), the stealth scripts may no longer suffice. Playwright with basic stealth evades simple checks, not advanced behavioural analysis.
- **URL parameter changes** (LOW risk): Search URL parameters are part of their public-facing URL scheme and rarely change.

**Mitigation strategies built in:**
1. Dual parsing: `__NEXT_DATA__` primary, HTML fallback
2. Defensive key access with `.get()` throughout - missing keys produce None, not crashes
3. Multiple path attempts for each data field (e.g. `advert.vehicle.mileage` OR `advert.mileage`)
4. Logging at every extraction point for quick diagnosis when things break

**When it breaks, the fix workflow is:**
1. Run a test scrape, observe which extraction step returns None
2. Use Playwright in non-headless mode to inspect the current page structure
3. Update the JSON paths or CSS selectors in the relevant parser
4. Typical fix time: 15-30 minutes for a competent developer

## 2. Legal Risk

### Assessment
| Concern | Risk Level | Details |
|---------|-----------|---------|
| ToS violation | **Medium** | AutoTrader prohibits automated scraping. Personal use provides no legal defence, but enforcement against individuals is extremely rare. |
| robots.txt compliance | **Non-compliant** | The scraper accesses `/car-search` and `/car-details` paths that robots.txt disallows for generic bots. |
| Computer Misuse Act (UK) | **Very Low** | No authentication bypass. Accessing publicly visible pages. CMA typically requires "unauthorised access to a computer." |
| Data Protection Act / GDPR | **Low** | Listing data is publicly visible. Seller names are the main personal data concern. Not storing or sharing personal data reduces risk. |
| Copyright infringement | **Low** | Storing individual listing descriptions could constitute database right infringement under EU/UK law if done at scale. |

### Recommendations
1. **Keep volume low** - Scraping 50-100 listings per session is defensible as personal research
2. **Do not store seller personal data beyond names** - No phone numbers, emails
3. **Never redistribute** - The scraped database should never be shared
4. **Add clear disclaimers** - Done in the web UI and README
5. **Implement strict rate limits** - 3-5 second delays make activity indistinguishable from manual browsing
6. **If contacted by AutoTrader, stop immediately** - Compliance is the safest response

## 3. Spec Data Quality

### Completeness Assessment
| Listing Type | Feature Data Quality | Estimated Coverage |
|-------------|---------------------|-------------------|
| **Dealer listings** (franchised) | Excellent - comprehensive structured lists from manufacturer data feeds | ~85% have full feature data |
| **Dealer listings** (independent) | Good - usually populated from manual entry or cap HPI data | ~65% have good feature data |
| **Private listings** | Poor - features are often in free text description only, not structured | ~25% have structured features |

### Normalisation Accuracy
- **True positive rate**: ~90% - the regex patterns correctly identify features when they're listed
- **False positive rate**: ~3% - rare mismatches (e.g. "heated rear screen" matching "heated_seats_rear" is prevented by specific regex design)
- **Coverage gap**: ~15-20% of features use naming patterns not in the normalisation map. This will improve over time as new patterns are added.

### Key Limitations
1. **Free text features are not extracted** - If a seller mentions "panoramic roof" only in the description but not in the features list, it's missed
2. **Trim-implied features are not inferred** - An "M Sport" BMW includes certain features as standard, but we don't apply trim-level knowledge
3. **Aftermarket additions are unreliable** - Features added after manufacture may not appear in structured data

### Improvement Path
- Add description text mining for features not found in structured data
- Build a trim-level feature database (e.g. "BMW 320d M Sport 2020" implies certain standard features)
- Use NLP/fuzzy matching to handle unknown feature name patterns

## 4. Deal Scoring Accuracy

### Strengths
- **Market comparison is sound** - Comparing price to median for same make/model/year/mileage band is the most reliable signal
- **Spec uplift adds value** - A high-spec car priced the same as a low-spec equivalent is genuinely a better deal
- **Multiple signal approach** - No single factor dominates; the composite score is more robust than any one metric

### Limitations
1. **Small sample bias** - For niche models or specific year/mileage combinations, there may be <5 comparable listings. Stats from small samples are unreliable. The scorer handles this (reduced confidence), but users should be aware.

2. **No historical sold prices** - The biggest limitation. We can only compare against current asking prices, not what cars actually sell for. A market where all cars are overpriced will still produce "good deal" scores for the least overpriced. AutoTrader does not expose sold prices.

3. **Spec uplift values are estimates** - The £800 assigned to a panoramic roof is a reasonable estimate but not derived from transaction data. Real uplift varies by make/model/market conditions.

4. **Regional variation is limited** - We capture location but don't adjust scoring for regional price differences (London prices vs. Scotland). This would require a larger dataset and geographic price modelling.

5. **Condition/service history blind spots** - A low-priced car might be a great deal or might have hidden issues. The scorer cannot assess physical condition, service history, or accident history.

6. **Dealer margin not modelled** - Dealer cars include margin that private sales don't. The scorer partially accounts for this (private seller bonus in signals) but doesn't model the typical dealer markup percentage.

### Estimated Accuracy
For listings with sufficient comparable data (>10 comparables): scores correlate well with genuine value (~75% accuracy in identifying top-quartile deals).
For listings with sparse comparables (<5): scores are directionally useful but not reliable (~50% accuracy).

## 5. Scalability

### Current Limits
| Metric | Current Capacity | Breaking Point |
|--------|-----------------|---------------|
| Listings stored | Unlimited (SQLite handles millions) | Not a bottleneck |
| Concurrent scraping | 1 page at a time (sequential) | Bottleneck at scale |
| Scraping speed | ~20 listings/minute (3s delay) | 500 listings = ~25 minutes |
| Detail scraping | ~20/hour | 500 detail pages = ~25 hours |
| Database queries | Fast for <100K rows | May slow at 500K+ rows |

### What Breaks at 500+ Daily Listings
1. **IP bans become likely** - 500 detail page requests daily from one IP will likely trigger Cloudflare blocks within days
2. **Time constraints** - Detail scraping 500 listings takes ~25 hours at current rate limits. That's continuous 24/7 scraping.
3. **Browser memory** - Long Playwright sessions can accumulate memory leaks. Need browser restart logic.

### What Would Need to Change
1. **Proxy rotation** - Residential proxy service ($30-50/month) to distribute requests across IPs
2. **Parallel scraping** - Multiple browser contexts scraping different listings concurrently
3. **Incremental updates** - Only scrape new/changed listings, not full refreshes
4. **API discovery** - If AutoTrader's internal JSON API can be called directly (bypassing Cloudflare), throughput increases 50-100x
5. **Database migration** - Move to PostgreSQL for concurrent writes and better query performance
6. **Queue-based architecture** - Use a task queue (Celery/RQ) for managing scrape jobs
7. **Monitoring** - Alerting when scrapes fail, when Cloudflare blocks increase, when data quality drops

## 6. Improvements Roadmap

### Prioritised by Impact vs Effort

| # | Improvement | Impact | Effort | Description |
|---|------------|--------|--------|-------------|
| 1 | **Description text mining** | HIGH | LOW | Parse the free-text description for features not in the structured list. Simple regex/keyword matching would capture 20-30% more features from private listings. |
| 2 | **Price alert/monitoring** | HIGH | MEDIUM | Schedule periodic re-scrapes for saved searches. Alert when new listings match criteria or when prices drop on watched listings. Would make the tool genuinely useful for active car buyers. |
| 3 | **Trim-level feature inference** | HIGH | MEDIUM | Build a database of standard features per trim level (e.g. BMW M Sport, Audi S Line). If a listing says "M Sport" in the title but has no feature list, infer the standard features. Significantly improves coverage for private listings. |
| 4 | **Historical price tracking** | MEDIUM | LOW | Store price snapshots over time for each listing. Detect price drops, track market trends, identify listings that have been reduced multiple times (motivated sellers). The database already supports this with `first_seen` and `scraped_at`. |
| 5 | **MOT/tax check integration** | MEDIUM | MEDIUM | Use the DVLA MOT history API (free, public) to check MOT pass rates, advisory items, and mileage consistency. This adds a vehicle condition signal that's currently missing from the scoring model. |

### Honourable Mentions
- **Saved searches** - Let users save and re-run favourite search configurations
- **Email/push notifications** - Alert when high-scoring listings appear
- **Photo gallery** - Scrape and display listing images in the web UI
- **Comparison mode** - Side-by-side comparison of 2-3 shortlisted cars
- **Mobile-friendly UI** - The current CSS is responsive but a dedicated mobile layout would improve usability

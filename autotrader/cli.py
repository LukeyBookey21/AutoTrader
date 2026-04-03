"""CLI interface for the AutoTrader scraper and deal finder."""

import asyncio
import json
import logging
import sys

import click

from autotrader.config import WEB_HOST, WEB_PORT
from autotrader.storage.database import init_db


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def cli(verbose):
    """AutoTrader Deal Finder - scrape, analyse, and find great car deals."""
    setup_logging(verbose)
    init_db()


@cli.command()
@click.option("--postcode", required=True, help="UK postcode for search location.")
@click.option("--make", required=True, help="Vehicle make (e.g. BMW, Audi).")
@click.option("--model", default=None, help="Vehicle model (e.g. 3 Series, A4).")
@click.option("--year-from", type=int, default=None, help="Minimum year.")
@click.option("--year-to", type=int, default=None, help="Maximum year.")
@click.option("--price-from", type=int, default=None, help="Minimum price (GBP).")
@click.option("--price-to", type=int, default=None, help="Maximum price (GBP).")
@click.option("--mileage-max", type=int, default=None, help="Maximum mileage.")
@click.option("--fuel-type", default=None, help="Fuel type (Petrol/Diesel/Electric/Hybrid).")
@click.option("--transmission", default=None, help="Transmission (Automatic/Manual).")
@click.option("--body-type", default=None, help="Body type (Hatchback/Saloon/SUV/Estate).")
@click.option("--seller-type", default=None, help="Seller type (trade/private).")
@click.option("--radius", default=None, help="Search radius in miles.")
@click.option("--sort", default="relevance", help="Sort order (relevance/price-asc/price-desc/distance).")
@click.option("--max-pages", type=int, default=None, help="Max search result pages to scrape.")
@click.option("--scrape-details/--no-details", default=True, help="Also scrape detail pages.")
@click.option("--max-details", type=int, default=None, help="Max listings to detail-scrape.")
def search(postcode, make, model, year_from, year_to, price_from, price_to,
           mileage_max, fuel_type, transmission, body_type, seller_type,
           radius, sort, max_pages, scrape_details, max_details):
    """Run a search on AutoTrader and scrape results."""
    params = {
        "postcode": postcode,
        "make": make,
        "model": model,
        "year_from": year_from,
        "year_to": year_to,
        "price_from": price_from,
        "price_to": price_to,
        "mileage_max": mileage_max,
        "fuel_type": fuel_type,
        "transmission": transmission,
        "body_type": body_type,
        "seller_type": seller_type,
        "radius": radius,
        "sort": sort,
    }
    # Remove None values
    params = {k: v for k, v in params.items() if v is not None}

    async def _run():
        from autotrader.scraper.browser import close_browser
        from autotrader.scraper.detail import scrape_listing_details_batch
        from autotrader.scraper.search import scrape_search

        try:
            click.echo(f"Searching AutoTrader for {make} {model or ''}...")
            listings = await scrape_search(params, max_pages=max_pages)
            click.echo(f"Found {len(listings)} listings from search.")

            if scrape_details and listings:
                listing_ids = [l["id"] for l in listings]
                click.echo(f"Scraping details for up to {max_details or len(listing_ids)} listings...")
                details = await scrape_listing_details_batch(listing_ids, max_listings=max_details)
                click.echo(f"Scraped details for {len(details)} listings.")

            click.echo("Done. Run 'autotrader process' to normalise features and score deals.")

        finally:
            await close_browser()

    asyncio.run(_run())


@cli.command()
@click.option("--make", default=None, help="Filter by make.")
@click.option("--model", default=None, help="Filter by model.")
def process(make, model):
    """Normalise features, compute market stats, and score all listings."""
    from autotrader.processing.market import compute_market_stats
    from autotrader.processing.normaliser import normalise_all_listings
    from autotrader.processing.scorer import score_all_listings

    click.echo("Step 1/3: Normalising features...")
    n = normalise_all_listings(make, model)
    click.echo(f"  Normalised features for {n} listings.")

    click.echo("Step 2/3: Computing market statistics...")
    stats = compute_market_stats(make, model)
    click.echo(f"  Computed stats for {len(stats)} market segments.")

    click.echo("Step 3/3: Scoring deals...")
    scored = score_all_listings(make, model)
    click.echo(f"  Scored {scored} listings.")

    click.echo("Processing complete!")


@cli.command()
@click.option("--make", default=None, help="Filter by make.")
@click.option("--model", default=None, help="Filter by model.")
@click.option("--min-score", type=int, default=None, help="Minimum deal score.")
@click.option("--features", multiple=True, help="Required features (normalised key).")
@click.option("--limit", type=int, default=20, help="Max results to show.")
@click.option("--sort", default="deal_score", help="Sort field.")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "csv"]), default="table")
def results(make, model, min_score, features, limit, sort, fmt):
    """View scored results from the database."""
    from autotrader.storage.database import search_listings

    listings = search_listings(
        make=make,
        model=model,
        features=list(features) if features else None,
        sort_by=sort,
        sort_order="DESC",
        limit=limit,
    )

    if min_score:
        listings = [l for l in listings if l.get("deal_score") and l["deal_score"] >= min_score]

    if not listings:
        click.echo("No listings found matching your criteria.")
        return

    if fmt == "json":
        click.echo(json.dumps(listings, indent=2, default=str))
        return

    if fmt == "csv":
        import csv
        import io
        fields = ["id", "title", "price", "year", "mileage", "deal_score", "at_deal_rating", "url"]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for l in listings:
            writer.writerow({k: l.get(k, "") for k in fields})
        click.echo(output.getvalue())
        return

    # Table format
    click.echo(f"\n{'Score':>5} | {'Price':>8} | {'Year':>4} | {'Mileage':>8} | {'AT Rating':>12} | Title")
    click.echo("-" * 90)
    for l in listings:
        score = f"{l['deal_score']:.0f}" if l.get("deal_score") else "--"
        price = f"£{l['price']:,}" if l.get("price") else "POA"
        year = str(l.get("year", "--"))
        mileage = f"{l['mileage']:,}" if l.get("mileage") else "--"
        at_rating = l.get("at_deal_rating", "--") or "--"
        title = (l.get("title") or "Untitled")[:40]
        click.echo(f"{score:>5} | {price:>8} | {year:>4} | {mileage:>8} | {at_rating:>12} | {title}")

    click.echo(f"\n{len(listings)} results shown. Use --format json for full data.")


@cli.command()
@click.option("--host", default=WEB_HOST, help="Host to bind to.")
@click.option("--port", type=int, default=WEB_PORT, help="Port to listen on.")
def web(host, port):
    """Start the web UI server."""
    import uvicorn
    click.echo(f"Starting web UI at http://{host}:{port}")
    uvicorn.run("autotrader.web.app:app", host=host, port=port, reload=False)


@cli.command()
def stats():
    """Show database statistics."""
    from autotrader.storage.database import get_db

    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        detailed = conn.execute("SELECT COUNT(*) FROM listings WHERE detail_scraped = 1").fetchone()[0]
        scored = conn.execute("SELECT COUNT(*) FROM listings WHERE deal_score IS NOT NULL").fetchone()[0]
        searches = conn.execute("SELECT COUNT(*) FROM search_history").fetchone()[0]
        segments = conn.execute("SELECT COUNT(*) FROM market_stats").fetchone()[0]

        makes = conn.execute(
            "SELECT make, COUNT(*) as cnt FROM listings GROUP BY make ORDER BY cnt DESC LIMIT 10"
        ).fetchall()

    click.echo(f"\nDatabase Statistics:")
    click.echo(f"  Total listings: {total}")
    click.echo(f"  Detail-scraped: {detailed}")
    click.echo(f"  Scored:         {scored}")
    click.echo(f"  Searches run:   {searches}")
    click.echo(f"  Market segments: {segments}")

    if makes:
        click.echo(f"\nTop makes:")
        for row in makes:
            click.echo(f"  {row[0] or 'Unknown'}: {row[1]} listings")


def main():
    cli()


if __name__ == "__main__":
    main()

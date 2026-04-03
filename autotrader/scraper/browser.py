"""Playwright browser management with stealth and rate limiting."""

import asyncio
import logging
import random
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from autotrader.config import HEADLESS, REQUEST_DELAY_SECONDS

logger = logging.getLogger(__name__)

# Singleton browser state
_playwright = None
_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_last_request_time: float = 0


async def get_browser_context() -> BrowserContext:
    """Get or create a shared browser context with stealth settings."""
    global _playwright, _browser, _context

    if _context is not None:
        return _context

    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(
        headless=HEADLESS,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
    )

    _context = await _browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="en-GB",
        timezone_id="Europe/London",
        java_script_enabled=True,
    )

    # Apply stealth scripts to evade basic bot detection
    await _context.add_init_script("""
        // Override navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

        // Override chrome runtime
        window.chrome = { runtime: {} };

        // Override permissions query
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);

        // Override plugins to look like a real browser
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });

        // Override languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-GB', 'en-US', 'en'],
        });
    """)

    return _context


async def rate_limit():
    """Enforce rate limiting between requests."""
    global _last_request_time
    now = asyncio.get_event_loop().time()
    elapsed = now - _last_request_time
    # Add jitter to look more human
    delay = REQUEST_DELAY_SECONDS + random.uniform(0.5, 1.5)
    if elapsed < delay:
        wait_time = delay - elapsed
        logger.debug(f"Rate limiting: waiting {wait_time:.1f}s")
        await asyncio.sleep(wait_time)
    _last_request_time = asyncio.get_event_loop().time()


async def fetch_page(url: str, retries: int = 3) -> Optional[Page]:
    """Navigate to a URL with rate limiting and retries. Returns the Page object."""
    context = await get_browser_context()

    for attempt in range(retries):
        await rate_limit()
        page = await context.new_page()
        try:
            # Block unnecessary resources to speed up loading
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,eot}",
                lambda route: route.abort(),
            )
            await page.route("**/analytics**", lambda route: route.abort())
            await page.route("**/tracking**", lambda route: route.abort())

            logger.info(f"Fetching: {url} (attempt {attempt + 1}/{retries})")
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            if response and response.status == 200:
                # Wait a moment for any JS hydration
                await page.wait_for_timeout(2000)
                return page

            if response and response.status == 403:
                logger.warning(f"Got 403 on attempt {attempt + 1}. "
                               "May need to handle Cloudflare challenge.")
                # Try waiting longer for Cloudflare challenge to resolve
                await page.wait_for_timeout(5000)
                # Check if page loaded after challenge
                content = await page.content()
                if "__NEXT_DATA__" in content or "search-results" in content.lower():
                    return page

            if response:
                logger.warning(f"Got status {response.status} on attempt {attempt + 1}")

        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")

        await page.close()

        if attempt < retries - 1:
            backoff = (attempt + 1) * 5 + random.uniform(1, 3)
            logger.info(f"Retrying in {backoff:.1f}s...")
            await asyncio.sleep(backoff)

    logger.error(f"Failed to fetch {url} after {retries} attempts")
    return None


async def extract_next_data(page: Page) -> dict | None:
    """Extract the __NEXT_DATA__ JSON from a page."""
    try:
        element = await page.query_selector("script#__NEXT_DATA__")
        if element:
            text = await element.inner_text()
            import json
            return json.loads(text)
    except Exception as e:
        logger.debug(f"No __NEXT_DATA__ found: {e}")

    # Fallback: try to find it in page source
    try:
        content = await page.content()
        import json
        import re
        match = re.search(
            r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
            content,
            re.DOTALL,
        )
        if match:
            return json.loads(match.group(1))
    except Exception as e:
        logger.debug(f"Fallback __NEXT_DATA__ extraction failed: {e}")

    return None


async def close_browser():
    """Clean up browser resources."""
    global _playwright, _browser, _context
    if _context:
        await _context.close()
        _context = None
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None

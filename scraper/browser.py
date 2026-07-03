"""
browser.py — Playwright browser lifecycle management.

Provides a context manager that yields a shared Browser instance.
Each worker creates its own BrowserContext + Page for isolation.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

logger = logging.getLogger(__name__)

# Realistic desktop user-agent to avoid trivial bot detection
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


@asynccontextmanager
async def launch_browser(headless: bool = True) -> AsyncGenerator[Browser, None]:
    """
    Context manager that launches a Chromium browser and closes it on exit.

    Usage:
        async with launch_browser(headless=True) as browser:
            # use browser
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        logger.info("Browser launched (headless=%s)", headless)
        try:
            yield browser
        finally:
            await browser.close()
            logger.info("Browser closed")


async def new_context(browser: Browser, timeout_ms: int = 30_000) -> BrowserContext:
    """
    Create a new isolated BrowserContext with realistic headers.
    Each async worker should use its own context.
    """
    ctx = await browser.new_context(
        user_agent=_USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        timezone_id="Europe/London",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
        },
    )
    ctx.set_default_timeout(timeout_ms)
    return ctx


async def new_page(context: BrowserContext) -> Page:
    """Open a new page in the given context."""
    page = await context.new_page()
    return page


async def load_page(
    page: Page,
    url: str,
    wait_selector: str = "main",
    timeout_ms: int = 30_000,
) -> str:
    """
    Navigate to `url`, wait for `wait_selector` to appear, and return
    the fully-rendered HTML of the page.
    """
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    # Wait for the React tree to hydrate and render the main content
    try:
        await page.wait_for_selector(wait_selector, timeout=timeout_ms)
    except Exception:
        logger.warning("Selector '%s' not found on %s — returning what we have", wait_selector, url)
    return await page.content()

"""
list_scraper.py — Discover all FC 26 player URLs from the FIFAIndex players list.

Iterates through paginated list pages (/players/?page=N) and extracts:
  - Player profile URL
  - Player ID (from URL)

Returns a list of (player_id, absolute_url) tuples.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page

from .browser import load_page, new_context, new_page
from .utils import build_list_url, ensure_absolute, extract_player_id, polite_sleep

logger = logging.getLogger(__name__)

BASE_URL = "https://www.fifaindex.com"
PLAYER_URL_PATTERN = re.compile(r"/players/\d+-[^/]+/?$")


async def discover_all_players(
    browser: Browser,
    base_url: str,
    list_path: str,
    page_delay_ms: int = 1200,
    timeout_ms: int = 30_000,
    max_pages: Optional[int] = None,
) -> List[Tuple[int, str]]:
    """
    Crawl all paginated player list pages and return a deduplicated list of
    (player_id, player_profile_url) tuples.

    Args:
        browser:       Shared Playwright Browser instance.
        base_url:      e.g. "https://www.fifaindex.com"
        list_path:     e.g. "/players/"
        page_delay_ms: Polite delay between list page requests.
        timeout_ms:    Per-page navigation timeout.
        max_pages:     Stop after this many list pages (None = scrape all).

    Returns:
        Deduplicated list of (player_id, absolute_url).
    """
    results: List[Tuple[int, str]] = []
    seen_ids: set[int] = set()

    # ── Determine total page count ──────────────────────────────────────
    first_url = build_list_url(base_url, list_path, 1)
    logger.info("Loading first list page: %s", first_url)
    
    ctx = await new_context(browser, timeout_ms)
    try:
        page = await new_page(ctx)
        try:
            html = await load_page(page, first_url, wait_selector="table, [role='table'], main", timeout_ms=timeout_ms)
            total_pages = _detect_last_page(html)
            logger.info("Total list pages detected: %s", total_pages if total_pages else "unknown")

            if max_pages:
                total_pages = min(total_pages or max_pages, max_pages)
                logger.info("Capped to %d pages by --max-pages flag", total_pages)

            _extract_from_html(html, base_url, results, seen_ids)
            logger.info("Page 1/%s — %d players found so far", total_pages or "?", len(results))
        finally:
            await page.close()
    finally:
        await ctx.close()

    # ── Iterate remaining pages ─────────────────────────────────────────
    page_num = 2
    while True:
        if total_pages and page_num > total_pages:
            break
        if max_pages and page_num > max_pages:
            break

        await polite_sleep(page_delay_ms)
        url = build_list_url(base_url, list_path, page_num)

        ctx = await new_context(browser, timeout_ms)
        try:
            page = await new_page(ctx)
            try:
                html = await load_page(page, url, wait_selector="table, [role='table'], main", timeout_ms=timeout_ms)
            except Exception as exc:
                logger.warning("Failed to load list page %d: %s", page_num, exc)
                break
            finally:
                await page.close()

            count_before = len(results)
            _extract_from_html(html, base_url, results, seen_ids)
            new_count = len(results) - count_before

            if new_count == 0:
                logger.info("Page %d returned no new players — stopping discovery.", page_num)
                break

            logger.info(
                "Page %d/%s — %d new players (+%d total)",
                page_num,
                total_pages or "?",
                new_count,
                len(results),
            )
            page_num += 1
        finally:
            await ctx.close()

    logger.info("Discovery complete: %d unique players found", len(results))
    return results


def _extract_from_html(
    html: str,
    base_url: str,
    results: List[Tuple[int, str]],
    seen_ids: set,
) -> None:
    """Parse one list page HTML and append new (id, url) entries to results."""
    soup = BeautifulSoup(html, "html.parser")

    # FIFAIndex renders player rows as <tr> or <div> rows with an <a> link
    # The player link matches /players/{id}-{slug}/
    for a_tag in soup.find_all("a", href=PLAYER_URL_PATTERN):
        href = a_tag["href"]
        player_id = extract_player_id(href)
        if player_id is None:
            continue
        if player_id in seen_ids:
            continue
        absolute_url = ensure_absolute(base_url, href)
        seen_ids.add(player_id)
        results.append((player_id, absolute_url))


def _detect_last_page(html: str) -> Optional[int]:
    """
    Try to find the last page number from pagination controls.
    Returns None if unable to determine.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Strategy 1: look for pagination links with the highest page number
    max_page = None
    for a in soup.find_all("a", href=re.compile(r"\?page=\d+")):
        m = re.search(r"\?page=(\d+)", a["href"])
        if m:
            p = int(m.group(1))
            if max_page is None or p > max_page:
                max_page = p

    if max_page:
        return max_page

    # Strategy 2: look for text like "24551 players" and compute pages
    total_m = re.search(r"(\d[\d,]+)\s+players?", soup.get_text())
    if total_m:
        total = int(total_m.group(1).replace(",", ""))
        # FIFAIndex shows ~50 players per page
        return (total + 49) // 50

    return None

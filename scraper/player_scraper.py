"""
player_scraper.py — Async orchestrator for scraping individual player pages.

Uses a semaphore to cap concurrency and processes players from a queue.
Each worker has its own BrowserContext + Page for isolation.
Retry logic wraps the entire scrape+parse cycle per player.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Tuple

from playwright.async_api import Browser

from .browser import load_page, new_context, new_page
from .models import PlayerData
from .parser import parse_player
from .utils import polite_sleep, with_retry
from .writer import OutputWriter

logger = logging.getLogger(__name__)


async def scrape_all_players(
    browser: Browser,
    player_urls: List[Tuple[int, str]],
    writer: OutputWriter,
    concurrency: int = 3,
    page_delay_ms: int = 1200,
    timeout_ms: int = 30_000,
    retry_attempts: int = 4,
    retry_wait_secs: float = 8.0,
) -> None:
    """
    Scrape all players in `player_urls` concurrently up to `concurrency` workers.

    Args:
        browser:          Shared Playwright Browser.
        player_urls:      List of (player_id, url) from list_scraper.
        writer:           OutputWriter instance (handles JSONL/CSV/checkpoint).
        concurrency:      Max simultaneous page contexts.
        page_delay_ms:    Polite sleep between requests per worker.
        timeout_ms:       Per-page navigation timeout.
        retry_attempts:   Max retries on failure.
        retry_wait_secs:  Base wait between retries.
    """
    semaphore = asyncio.Semaphore(concurrency)
    total = len(player_urls)
    completed = 0
    failed: List[Tuple[int, str]] = []

    # Simple progress tracking without tqdm for thread-safety
    lock = asyncio.Lock()

    async def process_one(player_id: int, url: str) -> None:
        nonlocal completed
        async with semaphore:
            try:
                player = await with_retry(
                    lambda: _scrape_single(browser, url, timeout_ms, page_delay_ms),
                    attempts=retry_attempts,
                    wait_secs=retry_wait_secs,
                )
                if player:
                    async with lock:
                        writer.write(player)
            except Exception as exc:
                logger.error("FAILED player %d (%s): %s", player_id, url, exc)
                async with lock:
                    failed.append((player_id, url))

            async with lock:
                completed += 1
                if completed % 50 == 0 or completed == total:
                    pct = completed / total * 100
                    logger.info(
                        "Progress: %d/%d (%.1f%%) | Failed: %d",
                        completed, total, pct, len(failed),
                    )

    tasks = [
        asyncio.create_task(process_one(pid, url))
        for pid, url in player_urls
    ]
    await asyncio.gather(*tasks)

    if failed:
        logger.warning("%d players failed to scrape:", len(failed))
        for pid, url in failed:
            logger.warning("  ID=%d  URL=%s", pid, url)

    logger.info(
        "Scraping complete: %d/%d succeeded, %d failed",
        total - len(failed), total, len(failed),
    )


async def _scrape_single(
    browser: Browser,
    url: str,
    timeout_ms: int,
    page_delay_ms: int,
) -> Optional[PlayerData]:
    """
    Open a new browser context, load the player page, parse it, and return PlayerData.
    Context is closed after use.
    """
    ctx = await new_context(browser, timeout_ms)
    try:
        page = await new_page(ctx)
        html = await load_page(
            page,
            url,
            wait_selector="main",
            timeout_ms=timeout_ms,
        )
        await polite_sleep(page_delay_ms)

        player = parse_player(html, url)

        # Basic sanity check: if no name was parsed, consider it failed
        if not player.name:
            logger.warning("Empty name for %s — may be a parse failure", url)

        return player
    finally:
        await ctx.close()

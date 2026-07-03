"""
utils.py — Shared helpers: URL parsing, retry decorator, rate-limit sleep.
"""
from __future__ import annotations

import asyncio
import logging
import re
from functools import wraps
from typing import Optional

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# ── URL helpers ──────────────────────────────────────────────────────────────

def extract_player_id(url: str) -> Optional[int]:
    """
    Extract numeric player ID from a FIFAIndex player URL.

    Examples:
        /players/231747-kylian-mbappe/  → 231747
        https://www.fifaindex.com/players/231747-kylian-mbappe/ → 231747
    """
    match = re.search(r"/players/(\d+)-", url)
    if match:
        return int(match.group(1))
    return None


def build_list_url(base_url: str, path: str, page: int) -> str:
    """Build the paginated players list URL."""
    base = base_url.rstrip("/")
    p = path.rstrip("/")
    if "?" in p:
        return f"{base}{p}&page={page}"
    return f"{base}{p}/?page={page}"


def ensure_absolute(base_url: str, url: str) -> str:
    """Make a relative URL absolute."""
    if url.startswith("http"):
        return url
    return base_url.rstrip("/") + "/" + url.lstrip("/")


# ── Star rating helpers ───────────────────────────────────────────────────────

def count_stars(text: str) -> Optional[int]:
    """
    Count star rating from a text string.
    Handles '★★★★☆' style, digit-only strings, or 'X stars' format.
    """
    if not text:
        return None
    text = text.strip()
    # Plain number
    if text.isdigit():
        return int(text)
    # '4 stars' or '4 star'
    m = re.match(r"^(\d+)\s*stars?$", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Count filled star characters
    filled = text.count("★") or text.count("⭐")
    if filled:
        return filled
    return None


# ── Numeric value helpers ─────────────────────────────────────────────────────

def parse_int(text: str) -> Optional[int]:
    """Parse a stripped integer from a text node, return None on failure."""
    if not text:
        return None
    text = text.strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        return None


def parse_height(text: str) -> Optional[int]:
    """
    Parse height into centimetres.
    Handles '182 cm', '182cm', "6'0\"", '180'.
    """
    if not text:
        return None
    text = text.strip()
    m = re.match(r"(\d+)\s*cm", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Feet/inches
    m = re.match(r"""(\d+)'(\d+)"?""", text)
    if m:
        return round(int(m.group(1)) * 30.48 + int(m.group(2)) * 2.54)
    m = re.match(r"^(\d+)$", text)
    if m:
        return int(m.group(1))
    return None


def parse_weight(text: str) -> Optional[int]:
    """
    Parse weight into kilograms.
    Handles '81 kg', '81kg', '179lbs'.
    """
    if not text:
        return None
    text = text.strip()
    m = re.match(r"(\d+)\s*kg", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.match(r"(\d+)\s*lbs?", text, re.IGNORECASE)
    if m:
        return round(int(m.group(1)) * 0.453592)
    m = re.match(r"^(\d+)$", text)
    if m:
        return int(m.group(1))
    return None


# ── Async retry wrapper ───────────────────────────────────────────────────────

async def with_retry(coro_fn, attempts: int = 4, wait_secs: float = 8.0):
    """
    Execute an async callable with exponential-backoff retries.

    Usage:
        result = await with_retry(lambda: my_async_fn(args))
    """
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=wait_secs, max=60),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    ):
        with attempt:
            return await coro_fn()


# ── Polite delay ──────────────────────────────────────────────────────────────

async def polite_sleep(ms: int) -> None:
    """Sleep for `ms` milliseconds."""
    await asyncio.sleep(ms / 1000)

"""
main.py — CLI entrypoint for the FIFAIndex FC 26 player scraper.

Usage:
    python -m scraper.main                          # Full scrape
    python -m scraper.main --max-pages 5            # Test: first 5 list pages
    python -m scraper.main --player-url URL         # Single player (parser test)
    python -m scraper.main --resume                 # Skip already-scraped IDs
    python -m scraper.main --rebuild-csv            # Rebuild CSV from existing JSONL
    python -m scraper.main --output-dir ./my_data   # Custom output directory
    python -m scraper.main --no-headless            # Show browser window
    python -m scraper.main --concurrency 5          # Override concurrency
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import yaml

from .browser import launch_browser
from .list_scraper import discover_all_players
from .models import PlayerData
from .parser import parse_player
from .player_scraper import scrape_all_players
from .writer import OutputWriter

# ── Logging setup ─────────────────────────────────────────────────────────────

def _setup_logging(output_dir: str) -> None:
    log_dir = Path(output_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "scraper.log"

    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


# ── Config loading ─────────────────────────────────────────────────────────────

def _load_config(path: str = "config.yaml") -> dict:
    config_path = Path(path)
    if not config_path.exists():
        # Return defaults if no config file
        return {
            "base_url": "https://www.fifaindex.com",
            "players_list_path": "/players/",
            "concurrency": 3,
            "page_delay_ms": 1200,
            "retry_attempts": 4,
            "retry_wait_seconds": 8,
            "output_dir": "./output",
            "output_jsonl": "players.jsonl",
            "output_csv": "players.csv",
            "headless": True,
            "browser_timeout_ms": 30000,
            "max_pages": None,
            "resume": True,
            "checkpoint_file": "./output/scraped_ids.txt",
        }
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Argument parsing ──────────────────────────────────────────────────────────

def _parse_args(config: dict) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FIFAIndex FC 26 Player Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--player-url",
        metavar="URL",
        help="Scrape a single player URL (for testing the parser)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=config.get("max_pages"),
        metavar="N",
        help="Limit to the first N list pages (default: all)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=config.get("concurrency", 3),
        help="Number of simultaneous browser contexts (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        default=config.get("output_dir", "./output"),
        help="Output directory (default: %(default)s)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Show the browser window (useful for debugging)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=config.get("resume", True),
        help="Skip player IDs already in the checkpoint file",
    )
    parser.add_argument(
        "--rebuild-csv",
        action="store_true",
        help="Rebuild the CSV from the existing JSONL file and exit",
    )
    return parser.parse_args()


# ── Main async entrypoint ─────────────────────────────────────────────────────

async def _async_main() -> None:
    config = _load_config()
    args = _parse_args(config)

    headless = not args.no_headless and config.get("headless", True)
    output_dir = args.output_dir
    _setup_logging(output_dir)

    logger = logging.getLogger(__name__)
    logger.info("FIFAIndex FC 26 Scraper starting")
    logger.info("Config: concurrency=%d, headless=%s, output=%s", args.concurrency, headless, output_dir)

    writer = OutputWriter(
        output_dir=output_dir,
        jsonl_name=config.get("output_jsonl", "players.jsonl"),
        csv_name=config.get("output_csv", "players.csv"),
        checkpoint_file=config.get("checkpoint_file", "./output/scraped_ids.txt"),
    )

    # ── Mode: Rebuild CSV only ──────────────────────────────────────────────
    if args.rebuild_csv:
        logger.info("Rebuilding CSV from JSONL…")
        writer.rebuild_csv()
        writer.close()
        logger.info("Done.")
        return

    # ── Mode: Single player (parser test) ─────────────────────────────────
    if args.player_url:
        logger.info("Single player mode: %s", args.player_url)
        async with launch_browser(headless=headless) as browser:
            from .browser import load_page, new_context, new_page
            ctx = await new_context(browser, config.get("browser_timeout_ms", 30000))
            page = await new_page(ctx)
            html = await load_page(page, args.player_url, wait_selector="main")
            await ctx.close()

        player = parse_player(html, args.player_url)
        # Write JSON to stdout with UTF-8 to avoid Windows console encoding issues
        sys.stdout.buffer.write(
            json.dumps(player.to_dict(), indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        )
        writer.write(player)
        writer.close()
        logger.info("Player saved to %s", output_dir)
        return

    # ── Mode: Full scrape ──────────────────────────────────────────────────
    async with launch_browser(headless=headless) as browser:
        # Phase 1: Discover player URLs
        logger.info("Phase 1: Discovering player URLs…")
        all_players = await discover_all_players(
            browser=browser,
            base_url=config["base_url"],
            list_path=config["players_list_path"],
            page_delay_ms=config.get("page_delay_ms", 1200),
            timeout_ms=config.get("browser_timeout_ms", 30000),
            max_pages=args.max_pages,
        )
        logger.info("Discovered %d players total", len(all_players))

        # Phase 2: Filter already-scraped
        if args.resume:
            to_scrape = [(pid, url) for pid, url in all_players if not writer.already_scraped(pid)]
            skipped = len(all_players) - len(to_scrape)
            if skipped:
                logger.info("Resuming: skipping %d already-scraped players (%d remaining)", skipped, len(to_scrape))
        else:
            to_scrape = all_players

        if not to_scrape:
            logger.info("All players already scraped. Use --rebuild-csv if needed.")
            writer.close()
            return

        # Phase 3: Scrape player detail pages
        logger.info("Phase 3: Scraping %d player detail pages…", len(to_scrape))
        await scrape_all_players(
            browser=browser,
            player_urls=to_scrape,
            writer=writer,
            concurrency=args.concurrency,
            page_delay_ms=config.get("page_delay_ms", 1200),
            timeout_ms=config.get("browser_timeout_ms", 30000),
            retry_attempts=config.get("retry_attempts", 4),
            retry_wait_secs=float(config.get("retry_wait_seconds", 8)),
        )

    # Post-run: rebuild CSV for a clean, consistent file
    logger.info("Post-processing: rebuilding CSV…")
    writer.rebuild_csv()
    writer.close()
    logger.info("All done! Output in: %s", output_dir)


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()

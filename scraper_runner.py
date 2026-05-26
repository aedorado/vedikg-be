#!/usr/bin/env python3
"""
Scraper runner - Start scraping Vedabase verses

Examples:
  python scraper_runner.py --canto 9 --chapters 7
  python scraper_runner.py --canto 9 --chapters 7,8,9
  python scraper_runner.py --canto 9 --chapters all
  python scraper_runner.py --canto 1-3 --chapters all
  python scraper_runner.py --sample
"""

import asyncio
import logging
import argparse
from app.scraper.vedabase import VedabaseScraper
from app.db.base import SessionLocal

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Authoritative chapter counts per SB canto (vedabase.io)
SB_CHAPTERS_PER_CANTO = {
    1: 19, 2: 10, 3: 33, 4: 31, 5: 26,
    6: 19, 7: 15, 8: 24, 9: 24, 10: 90,
    11: 31, 12: 13,
}


def _parse_canto(value: str) -> list[int]:
    """Parse '9', '1-3', or '1,3,5' → list of canto ints."""
    cantos = []
    for part in value.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-', 1)
            cantos.extend(range(int(start), int(end) + 1))
        else:
            cantos.append(int(part))
    return cantos


def _parse_chapters(value: str, canto: int) -> list[int]:
    """Parse 'all', '7', '7,8', or '7-9' → list of chapter ints."""
    if value.lower() == 'all':
        total = SB_CHAPTERS_PER_CANTO.get(canto)
        if not total:
            raise ValueError(f"Unknown canto {canto}")
        return list(range(1, total + 1))
    chapters = []
    for part in value.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-', 1)
            chapters.extend(range(int(start), int(end) + 1))
        else:
            chapters.append(int(part))
    return chapters


async def main():
    parser = argparse.ArgumentParser(
        description='Scrape Vedabase verses',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--canto', type=str, default='1',
                        help='Canto(s): single "9", range "1-3", or list "1,3"')
    parser.add_argument('--chapters', type=str, default='1',
                        help='Chapters: "all", single "7", range "7-9", or list "7,8"')
    parser.add_argument('--sample', action='store_true',
                        help='Quick sample: SB 1.1-5')

    args = parser.parse_args()

    scraper = VedabaseScraper()
    db = SessionLocal()

    try:
        if args.sample:
            logger.info("🚀 Starting sample scrape: SB 1.1-5 (~250 verses)")
            await scraper.scrape_sample()
        else:
            cantos = _parse_canto(args.canto)
            for canto in cantos:
                chapters = _parse_chapters(args.chapters, canto)
                logger.info(f"🚀 Scraping SB {canto} — chapters {chapters[0]}–{chapters[-1]} ({len(chapters)} total)")
                await scraper.scrape_chapters(canto, chapters, db)

        logger.info("✅ Scraping completed!")

    except KeyboardInterrupt:
        logger.info("⏸ Scraping interrupted by user")
    except Exception as e:
        logger.error(f"❌ Scraping failed: {e}", exc_info=True)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())

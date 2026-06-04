#!/usr/bin/env python3
import sys, os
from dotenv import load_dotenv
load_dotenv()
_pg = os.getenv("POSTGRES_URL", "")
print(f"🐍 Python: {sys.executable}")
print(f"🗄️  DB: {'Supabase (' + _pg.split('@')[-1][:40] + ')' if _pg else '❌ POSTGRES_URL not set — aborting'}")
if not _pg:
    sys.exit(1)
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
from app.models.models import Book, Canto, Chapter, Verse

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


def _find_incomplete_chapters(canto: int, chapters: list[int]) -> list[int]:
    """Return chapters whose verse count in DB doesn't match the chapter index page count."""
    db = SessionLocal()
    try:
        sb_book = db.query(Book).filter_by(code='SB').first()
        if not sb_book:
            return chapters
        canto_row = db.query(Canto).filter_by(book_id=sb_book.id, number=canto).first()
        if not canto_row:
            return chapters
        incomplete = []
        for ch_num in chapters:
            ch = db.query(Chapter).filter_by(canto_id=canto_row.id, chapter_number=ch_num).first()
            if not ch:
                incomplete.append(ch_num)
                continue
            # Re-fetch chapter index to see how many verse links exist
            # We proxy this by checking if verse count seems suspiciously low.
            # A chapter with 0 verses is definitely incomplete.
            count = db.query(Verse).filter_by(chapter_id=ch.id).count()
            if count == 0:
                incomplete.append(ch_num)
        return incomplete
    finally:
        db.close()


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
    parser.add_argument('--concurrency', type=int, default=5,
                        help='Number of chapters to scrape in parallel (default: 5)')
    parser.add_argument('--sample', action='store_true',
                        help='Quick sample: SB 1.1-5')
    parser.add_argument('--retries', type=int, default=3,
                        help='Gap-fill retry passes after initial scrape (default: 3)')

    args = parser.parse_args()

    scraper = VedabaseScraper()

    try:
        if args.sample:
            logger.info("🚀 Starting sample scrape: SB 1.1-5 (~250 verses)")
            await scraper.scrape_chapters(1, [1, 2, 3, 4, 5], concurrency=args.concurrency)
        else:
            cantos = _parse_canto(args.canto)
            for canto in cantos:
                chapters = _parse_chapters(args.chapters, canto)
                logger.info(f"🚀 Scraping SB {canto} — chapters {chapters[0]}–{chapters[-1]} ({len(chapters)} total)")
                await scraper.scrape_chapters(canto, chapters, concurrency=args.concurrency)

                # Gap-fill: retry any chapters that ended up with 0 verses
                for attempt in range(1, args.retries + 1):
                    missing = _find_incomplete_chapters(canto, chapters)
                    if not missing:
                        break
                    logger.info(f"🔁 Gap-fill pass {attempt}/{args.retries}: {len(missing)} incomplete chapters {missing}")
                    await asyncio.sleep(5)  # brief pause before retry
                    await scraper.scrape_chapters(canto, missing, concurrency=max(1, args.concurrency // 2))

                remaining = _find_incomplete_chapters(canto, chapters)
                if remaining:
                    logger.warning(f"⚠️  Still incomplete after {args.retries} retries — chapters: {remaining}")
                else:
                    logger.info(f"✅ SB {canto} complete — all chapters have verses")

        logger.info("✅ Scraping completed!")

    except KeyboardInterrupt:
        logger.info("⏸ Scraping interrupted by user")
    except Exception as e:
        logger.error(f"❌ Scraping failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())

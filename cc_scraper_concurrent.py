#!/usr/bin/env python3
"""Multi-threaded CC scraper - scrapes each chapter in parallel."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from cc_scraper_runner import scrape_cc

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SECTIONS = {
    'adi': list(range(1, 18)),      # 17 chapters
    'madhya': list(range(1, 26)),   # 25 chapters
    'antya': list(range(1, 21)),    # 20 chapters
}

def scrape_chapter(section: str, chapter: int):
    """Scrape a single chapter in a thread."""
    try:
        logger.info(f"[{section.upper()} ch.{chapter}] Starting...")
        asyncio.run(scrape_cc(section, [chapter]))
        logger.info(f"[{section.upper()} ch.{chapter}] Done")
        return True
    except Exception as e:
        logger.error(f"[{section.upper()} ch.{chapter}] Failed: {e}")
        return False

def main():
    logger.info("Starting multi-threaded CC scrape...")
    total_chapters = sum(len(chapters) for chapters in SECTIONS.values())
    completed = 0
    failed = 0
    
    with ThreadPoolExecutor(max_workers=6) as executor:
        # Submit all tasks
        futures = {}
        for section, chapters in SECTIONS.items():
            for chapter in chapters:
                future = executor.submit(scrape_chapter, section, chapter)
                futures[future] = (section, chapter)
        
        # Process results as they complete
        for future in as_completed(futures):
            section, chapter = futures[future]
            try:
                success = future.result()
                if success:
                    completed += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"[{section.upper()} ch.{chapter}] Exception: {e}")
                failed += 1
            
            logger.info(f"Progress: {completed + failed}/{total_chapters} ({completed} OK, {failed} failed)")
    
    logger.info(f"\nFinal: {completed} completed, {failed} failed")

if __name__ == "__main__":
    main()

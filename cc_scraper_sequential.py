#!/usr/bin/env python3
"""Sequential CC scraper - scrapes all chapters one by one."""

import asyncio
import logging
from cc_scraper_runner import scrape_cc

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHAPTERS = {
    'adi': list(range(1, 18)),      # 17 chapters
    'madhya': list(range(1, 26)),   # 25 chapters
    'antya': list(range(1, 21)),    # 20 chapters
}

def main():
    total_chapters = sum(len(chapters) for chapters in CHAPTERS.values())
    completed = 0
    failed_chapters = []
    
    logger.info(f"Starting sequential CC scrape ({total_chapters} chapters)...")
    
    for section, chapters in CHAPTERS.items():
        for chapter in chapters:
            try:
                logger.info(f"[{completed+1}/{total_chapters}] Scraping {section.upper()} ch.{chapter}...")
                asyncio.run(scrape_cc(section, [chapter]))
                completed += 1
                logger.info(f"✓ Completed {section.upper()} ch.{chapter}")
            except Exception as e:
                failed_chapters.append(f"{section.upper()} ch.{chapter}")
                logger.error(f"✗ Failed {section.upper()} ch.{chapter}: {e}")
    
    logger.info(f"\n=== FINAL RESULTS ===")
    logger.info(f"Completed: {completed}/{total_chapters}")
    if failed_chapters:
        logger.info(f"Failed chapters: {', '.join(failed_chapters)}")
    else:
        logger.info("All chapters scraped successfully!")

if __name__ == "__main__":
    main()

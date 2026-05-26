#!/usr/bin/env python3
"""
Caitanya Bhagavata EPUB Scraper
================================
Processes all 7 CB EPUB volumes and stores them in the database with correct
chapter numbering.

The EPUBs carry chapter numbers that continue across volumes within each khanda.
We apply an offset per volume to normalise them to the real book chapter numbers:

  Ādi Khanda
    Part 1  (ch 1–8)   : EPUB chapters 9–16   → offset -8
    Part 2  (ch 9–17)  : EPUB chapters 10–18  → offset -1

  Madhya Khanda
    Part 1  (ch 1–7)   : EPUB chapters  8–14  → offset -7
    Part 2  (ch 8–17)  : EPUB chapters 11–20  → offset -3
    Part 3  (ch 18–28) : EPUB chapters 12–22  → offset +6

  Antya Khanda
    Part 1  (ch 1–4)   : EPUB chapters  5–8   → offset -4
    Part 2  (ch 5–10)  : EPUB chapters  7–12  → offset -2
"""

import sys
import os
import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── Path setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
os.chdir(SCRIPT_DIR)
sys.path.insert(0, str(SCRIPT_DIR))

from app.models.models import Base, Book, Canto, Chapter, Verse
from app.services.epub_parser import EPUBParser

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Database ─────────────────────────────────────────────────────────────────
# Using PostgreSQL via db.py wrapper
from db import get_conn

# ── EPUB manifest ─────────────────────────────────────────────────────────────
# (khanda_slug, display_name, section_label, canto_number, epub_filename, chapter_offset)
EPUB_VOLUMES = [
    ("adi",    "Ādi Khanda",    "ADI",    1, "Sri Caitanya-bhagavata - Adi Khanda - 1.epub",    -8),
    ("adi",    "Ādi Khanda",    "ADI",    1, "Sri Caitanya-bhagavata - Adi Khanda - 2.epub",    -1),
    ("madhya", "Madhya Khanda", "MADHYA", 2, "Sri Caitanya-bhagavata - Madhya Khanda - 1.epub", -7),
    ("madhya", "Madhya Khanda", "MADHYA", 2, "Sri Caitanya-bhagavata - Madhya Khanda - 2.epub", -3),
    ("madhya", "Madhya Khanda", "MADHYA", 2, "Sri Caitanya-bhagavata - Madhya Khanda - 3.epub", +6),
    ("antya",  "Antya Khanda",  "ANTYA",  3, "Sri Caitanya-bhagavata - Antya Khanda - 1.epub",  -4),
    ("antya",  "Antya Khanda",  "ANTYA",  3, "Sri Caitanya-bhagavata - Antya Khanda - 2.epub",  -2),
]

EPUB_DIR = SCRIPT_DIR / "epub" / "cb"

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_or_create_book(session) -> Book:
    book = session.query(Book).filter_by(code="CB").first()
    if not book:
        book = Book(
            code="CB",
            title="Caitanya Bhagavata",
            author="Vṛndāvana dāsa Ṭhākura",
            translator="Bhūmipati Dāsa",
            commentary_name="Gauḍīya-bhāṣya",
            commentary_author="Bhaktisiddhānta Sarasvatī Gosvāmī Mahārāja",
        )
        session.add(book)
        session.commit()
        log.info("Created book record: Caitanya Bhagavata")
    return book


def get_or_create_canto(session, book: Book, canto_number: int,
                         title: str, slug: str, section_label: str) -> Canto:
    canto = session.query(Canto).filter_by(book_id=book.id, number=canto_number).first()
    if not canto:
        canto = Canto(
            book_id=book.id,
            number=canto_number,
            title=title,
            slug=slug,
            section_label=section_label,
            summary=f"{title} of Caitanya Bhagavata",
        )
        session.add(canto)
        session.commit()
        log.info(f"  Created canto: {title}")
    return canto


def get_or_create_chapter(session, canto: Canto, chapter_number: int,
                           title: str, summary: str) -> Chapter:
    chapter = session.query(Chapter).filter_by(
        canto_id=canto.id, chapter_number=chapter_number
    ).first()
    if not chapter:
        chapter = Chapter(
            canto_id=canto.id,
            chapter_number=chapter_number,
            title=title,
            slug=f"chapter-{chapter_number}",
            summary=summary,
        )
        session.add(chapter)
        session.commit()
    elif summary and chapter.summary != summary:
        chapter.summary = summary
        session.commit()
    return chapter


# ── Main processing ───────────────────────────────────────────────────────────

def process_volume(session, book: Book, volume: tuple) -> int:
    khanda_slug, display_name, section_label, canto_number, filename, offset = volume

    epub_path = EPUB_DIR / filename
    if not epub_path.exists():
        log.error(f"  File not found: {epub_path}")
        return 0

    log.info(f"  Parsing {filename}  (offset {offset:+d})")

    parser = EPUBParser(str(epub_path))
    raw_verses = parser.extract_all_verses()

    if not raw_verses:
        log.warning(f"  No verses extracted from {filename}")
        return 0

    canto = get_or_create_canto(session, book, canto_number,
                                 display_name, khanda_slug, section_label)

    stored = 0
    for vd in raw_verses:
        if not vd.get("sanskrit_text"):
            continue

        ch_num = vd["chapter_num"] + offset
        v_num  = vd["verse_num"]

        chapter = get_or_create_chapter(
            session, canto, ch_num,
            vd.get("chapter_title") or f"Chapter {ch_num}",
            vd.get("chapter_summary") or ""
        )

        ref = f"CB.{khanda_slug}.{ch_num}.{v_num}"
        if session.query(Verse).filter_by(full_reference=ref).first():
            continue  # already stored (shouldn't happen on fresh DB)

        session.add(Verse(
            chapter_id=chapter.id,
            book_id=book.id,
            verse_number=v_num,
            full_reference=ref,
            devanagari=vd["sanskrit_text"],
            transliteration="",
            translation=vd.get("translation", ""),
            purport_text=vd.get("purport", ""),
        ))
        stored += 1

    session.commit()
    log.info(f"    → {stored} verses stored")
    return stored


def main():
    log.info("=" * 60)
    log.info("Caitanya Bhagavata Scraper")
    log.info("=" * 60)

    Base.metadata.create_all(bind=engine)
    session = Session()

    try:
        book = get_or_create_book(session)
        total = 0

        current_khanda = None
        for volume in EPUB_VOLUMES:
            khanda = volume[0]
            if khanda != current_khanda:
                log.info(f"\n[ {volume[1]} ]")
                current_khanda = khanda
            total += process_volume(session, book, volume)

        log.info("\n" + "=" * 60)
        log.info(f"Done — {total} verses stored in total")
        log.info("=" * 60)

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()

"""
CC (Caitanya-caritāmṛta) scraper for vedabase.io.

Usage:
  cd backend
  venv/bin/python cc_scraper_runner.py --section adi --chapters all
  venv/bin/python cc_scraper_runner.py --section madhya --chapters 1-5
  venv/bin/python cc_scraper_runner.py --section antya --chapters 1
"""
import argparse, asyncio, logging, re, json
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.models import (
    Book, Author, Canto, Chapter, Verse, Purport,
    Entity, VerseEntity, Relationship, ScrapeJob,
)
from app.nlp.alias_resolver import resolve_alias, ALIAS_TO_ENTITY
from app.nlp.relationship_extractor import RelationshipExtractor
from app.nlp.chanda_detector import detect_chanda, detect_chanda_detail, detect_language
from app.scraper.vedabase import _infer_entity_type

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

rel_extractor = RelationshipExtractor()

# ── Entity type inference (reuse SB logic) ───────────────────────────────────
from app.scraper.vedabase import _infer_entity_type

# ── CC section metadata ───────────────────────────────────────────────────────
CC_SECTIONS = {
    "adi":    {"number": 1, "label": "Ādi-līlā",    "chapters": 17, "slug": "adi"},
    "madhya": {"number": 2, "label": "Madhya-līlā", "chapters": 25, "slug": "madhya"},
    "antya":  {"number": 3, "label": "Antya-līlā",  "chapters": 20, "slug": "antya"},
}

BASE_URL = "https://vedabase.io/en/library/cc"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SB-Viz-Bot/1.0)"}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_or_create_book(db: Session) -> Book:
    book = db.query(Book).filter_by(code="CC").first()
    if not book:
        book = Book(code="CC", title="Caitanya-caritāmṛta",
                    url_prefix="https://vedabase.io/en/library/cc/")
        db.add(book); db.flush()
    return book


def _get_prabhupada(db: Session) -> Author:
    author = db.query(Author).filter_by(slug="srila-prabhupada").first()
    if not author:
        author = Author(name="Śrīla Prabhupāda", slug="srila-prabhupada")
        db.add(author); db.flush()
    return author


def _get_or_create_canto(db: Session, book: Book, section_key: str) -> Canto:
    meta = CC_SECTIONS[section_key]
    canto = db.query(Canto).filter_by(book_id=book.id, number=meta["number"]).first()
    if not canto:
        canto = Canto(
            number=meta["number"],
            title=meta["label"],
            slug=f"cc-{section_key}",
            book_id=book.id,
            section_label=meta["label"],
        )
        db.add(canto); db.flush()
        logger.info(f"Created canto: CC {meta['label']}")
    return canto


def _get_or_create_chapter(db: Session, canto: Canto, chapter_num: int,
                            title: str, source_url: str) -> Chapter:
    chapter = db.query(Chapter).filter_by(
        canto_id=canto.id, chapter_number=chapter_num
    ).first()
    if not chapter:
        section_key = {1: "adi", 2: "madhya", 3: "antya"}[canto.number]
        chapter = Chapter(
            canto_id=canto.id,
            chapter_number=chapter_num,
            title=title or f"Chapter {chapter_num}",
            slug=f"cc-{section_key}-{chapter_num}",
            source_url=source_url,
        )
        db.add(chapter); db.flush()
    return chapter


# ── HTML parsing ──────────────────────────────────────────────────────────────

def _parse_chapter_index(html: str) -> tuple[str, list[tuple[int, str]]]:
    """Parse a CC chapter index page.

    Returns:
      summary  – prose paragraphs before verse links (chapter introduction)
      verses   – list of (verse_num, absolute_url) for each verse
    """
    soup = BeautifulSoup(html, "html.parser")

    summary_parts: list[str] = []
    verse_links: list[tuple[int, str]] = []

    # Verse link pattern: /en/library/cc/adi/1/7/  OR  /en/library/cc/adi/1/65-66/
    verse_href_re = re.compile(r"/en/library/cc/\w+/\d+/([\d]+(?:-\d+)?)/$")

    for div in soup.find_all("div", recursive=True):
        classes = " ".join(div.get("class", []))
        # Inner content divs on this page use either 's-justify' (prose) or
        # 'text-justify' (verse entry).  We want the outermost user-content divs
        # — those whose class string contains 'copy' and 'user-select-text'.
        if "copy" not in classes or "user-select-text" not in classes:
            continue

        # Check if this block contains a verse link
        anchor = div.find("a", href=verse_href_re)
        if anchor:
            m = verse_href_re.search(anchor["href"])
            if m:
                vnum_raw = m.group(1)
                # For ranges like "65-66", use the first number as verse_number
                # but keep the original URL (which has the range in the path)
                try:
                    vnum = int(vnum_raw.split("-")[0])
                except ValueError:
                    continue
                abs_url = "https://vedabase.io" + anchor["href"]
                verse_links.append((vnum, abs_url))
        else:
            # Prose paragraph — part of chapter summary
            text = div.get_text(" ", strip=True)
            if text and len(text) > 40:
                summary_parts.append(text)

    summary = "\n\n".join(summary_parts)
    return summary, verse_links


def _parse_verse_page(html: str, verse_num: int, section_key: str,
                      chapter_num: int, source_url: str) -> dict | None:
    """Parse an individual CC verse page using vedabase av-* CSS classes."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "header", "nav", "footer", "iframe"]):
        tag.decompose()

    def _section_text(div, sep="\n"):
        if not div:
            return ""
        for h2 in div.find_all("h2"):
            h2.decompose()
        return div.get_text(sep, strip=True)

    devanagari    = _section_text(soup.find(class_="av-devanagari"))
    transliteration = _section_text(soup.find(class_="av-verse_text"))
    synonyms      = _section_text(soup.find(class_="av-synonyms"), sep=" ")
    translation   = _section_text(soup.find(class_="av-translation"), sep=" ")

    purport_div  = soup.find(class_="av-purport")
    purport_html = purport_text = None
    if purport_div:
        import copy as _copy
        purport_div2 = _copy.copy(purport_div)
        for h2 in purport_div2.find_all("h2"):
            h2.decompose()
        purport_html = str(purport_div2)
        purport_text = purport_div2.get_text("\n", strip=True)

    # Fallback for pages without av-* classes
    if not translation:
        main = soup.find("main") or soup.find("article") or soup.body
        if main:
            full = main.get_text("\n", strip=True)
            if "Translation" in full:
                translation = full.split("Translation", 1)[1].split("Purport")[0].strip()
            if not purport_text and "Purport" in full:
                purport_text = full.split("Purport", 1)[1].strip()[:100_000]

    if not translation and not purport_text:
        return None

    meta = CC_SECTIONS[section_key]
    # Build reference: "CC Ādi 1.7"
    section_display = meta["label"].split("-")[0].strip()   # "Ādi", "Madhya", "Antya"
    full_ref = f"CC {section_display} {chapter_num}.{verse_num}"

    return {
        "verse_number": verse_num,
        "full_reference": full_ref,
        "source_url": source_url,
        "devanagari": devanagari or None,
        "transliteration": transliteration or None,
        "synonyms_raw": synonyms or None,
        "translation": translation or None,
        "purport_html": purport_html,
        "purport_text": purport_text,
    }


async def _fetch(client: httpx.AsyncClient, url: str) -> Optional[str]:
    try:
        r = await client.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.warning(f"Fetch failed {url}: {e}")
        return None


# ── Entity/relationship processing (reuses SB logic) ──────────────────────────

def _process_entities(db: Session, verse: Verse, translation: str, purport: str):
    combined = (translation or "") + " " + (purport or "")
    if not combined.strip():
        return
    try:
        entity_names = rel_extractor.extract_all_entities(combined)
        if entity_names:
            logger.info(f"Verse {verse.id}: extracted {len(entity_names)} entities")
        for entity_name in entity_names:
            try:
                entity = db.query(Entity).filter_by(normalized_name=entity_name.lower()).first()
                # CREATE new entity if it doesn't exist (matching SB scraper behavior)
                if not entity:
                    entity = Entity(
                        name=entity_name,
                        normalized_name=entity_name.lower(),
                        entity_type=_infer_entity_type(entity_name),
                    )
                    db.add(entity)
                    db.flush()
                    logger.info(f"Created entity: {entity_name}")
                
                # Find where the entity is mentioned
                verse_mention = translation and entity_name.lower() in translation.lower()
                purport_mention = purport and entity_name.lower() in purport.lower()
                
                if verse_mention or purport_mention:
                    location = "both" if (verse_mention and purport_mention) else ("verse_text" if verse_mention else "purport_text")
                    existing = db.query(VerseEntity).filter_by(
                        verse_id=verse.id, entity_id=entity.id
                    ).first()
                    if not existing:
                        db.add(VerseEntity(
                            verse_id=verse.id, entity_id=entity.id,
                            mention_location=location, confidence_score=0.9
                        ))
            except Exception as entity_err:
                # Log per-entity errors but continue processing other entities
                logger.warning(f"Failed to process entity '{entity_name}' for verse {verse.id}: {entity_err}")
                db.rollback()
                # Refetch the entity in case it exists but flush failed
                entity = db.query(Entity).filter_by(normalized_name=entity_name.lower()).first()
                if entity:
                    verse_mention = translation and entity_name.lower() in translation.lower()
                    purport_mention = purport and entity_name.lower() in purport.lower()
                    if verse_mention or purport_mention:
                        location = "both" if (verse_mention and purport_mention) else ("verse_text" if verse_mention else "purport_text")
                        existing = db.query(VerseEntity).filter_by(
                            verse_id=verse.id, entity_id=entity.id
                        ).first()
                        if not existing:
                            db.add(VerseEntity(
                                verse_id=verse.id, entity_id=entity.id,
                                mention_location=location, confidence_score=0.9
                            ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Entity extraction failed for verse {verse.id}: {e}", exc_info=True)



def _process_relationships(db: Session, verse: Verse, text: str):
    if not text:
        return
    try:
        rels = rel_extractor.extract_relationships(text)
        for src_name, rel_type, tgt_name in rels:
            src = db.query(Entity).filter_by(name=resolve_alias(src_name) or src_name).first()
            tgt = db.query(Entity).filter_by(name=resolve_alias(tgt_name) or tgt_name).first()
            if src and tgt and src.id != tgt.id:
                existing = db.query(Relationship).filter_by(
                    source_entity_id=src.id, target_entity_id=tgt.id,
                    relationship_type=rel_type, source_verse_id=verse.id
                ).first()
                if not existing:
                    db.add(Relationship(
                        source_entity_id=src.id, target_entity_id=tgt.id,
                        relationship_type=rel_type, source_verse_id=verse.id,
                        confidence_score=0.85
                    ))
    except Exception as e:
        logger.debug(f"Relationship extraction failed for verse {verse.id}: {e}")


# ── Main scrape logic ─────────────────────────────────────────────────────────

async def scrape_cc_chapter(section_key: str, chapter_num: int, db: Session):
    url = f"{BASE_URL}/{section_key}/{chapter_num}/"
    book = _get_or_create_book(db)
    author = _get_prabhupada(db)
    canto = _get_or_create_canto(db, book, section_key)

    async with httpx.AsyncClient() as client:
        # Phase 1: fetch chapter index page for title, summary, verse links
        html = await _fetch(client, url)
        if not html:
            logger.error(f"Could not fetch {url}")
            return 0

        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("h1") or soup.find("h2")
        title = title_tag.get_text(strip=True) if title_tag else f"Chapter {chapter_num}"

        summary, verse_links = _parse_chapter_index(html)
        if not verse_links:
            logger.warning(f"No verse links found on {url}")
            return 0
        logger.info(f"  Found {len(verse_links)} verses in CC {section_key} ch.{chapter_num}")

        chapter = _get_or_create_chapter(db, canto, chapter_num, title, url)
        if summary and not chapter.summary:
            chapter.summary = summary

        # Phase 2: fetch each individual verse page
        count = 0
        for vnum, verse_url in verse_links:
            existing = db.query(Verse).filter_by(
                chapter_id=chapter.id, verse_number=vnum
            ).first()
            if existing:
                continue

            verse_html = await _fetch(client, verse_url)
            if not verse_html:
                logger.warning(f"  Could not fetch verse {vnum}: {verse_url}")
                continue

            vd = _parse_verse_page(verse_html, vnum, section_key, chapter_num, verse_url)
            if not vd:
                logger.warning(f"  Could not parse verse {vnum} from {verse_url}")
                continue

            lang = detect_language(vd.get("transliteration") or "")

            chanda, chanda_json = None, None
            if lang == "sa" and vd.get("transliteration"):
                try:
                    chanda = detect_chanda(vd["transliteration"])
                    detail = detect_chanda_detail(vd["transliteration"])
                    chanda_json = json.dumps(detail, ensure_ascii=False) if detail else None
                except Exception:
                    pass

            verse = Verse(
                chapter_id=chapter.id,
                verse_number=vd["verse_number"],
                full_reference=vd["full_reference"],
                source_url=vd["source_url"],
                devanagari=vd.get("devanagari"),
                transliteration=vd.get("transliteration"),
                translation=vd.get("translation"),
                synonyms_raw=vd.get("synonyms_raw"),
                purport_html=vd.get("purport_html"),
                purport_text=vd.get("purport_text"),
                chanda=chanda,
                chanda_json=chanda_json,
                language=lang,
                book_id=book.id,
                scraped_at=datetime.utcnow(),
            )
            db.add(verse)
            db.flush()

            if vd.get("purport_text"):
                db.add(Purport(
                    verse_id=verse.id,
                    author_id=author.id,
                    body_html=vd.get("purport_html"),
                    body_text=vd.get("purport_text"),
                    language="en",
                ))

            _process_entities(db, verse, vd.get("translation"), vd.get("purport_text"))
            _process_relationships(db, verse, (vd.get("translation") or "") + " " + (vd.get("purport_text") or ""))

            count += 1
            logger.info(f"  Saved {vd['full_reference']}")

        db.commit()
        logger.info(f"CC {CC_SECTIONS[section_key]['label']} ch.{chapter_num}: {count} new verses")
        return count


async def scrape_cc(section_key: str, chapters: list[int]):
    db = SessionLocal()
    try:
        total = 0
        for ch in chapters:
            n = await scrape_cc_chapter(section_key, ch, db)
            total += n
        logger.info(f"Done. Total new verses: {total}")
    finally:
        db.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scrape Caitanya-caritāmṛta from vedabase.io")
    parser.add_argument("--section", choices=["adi", "madhya", "antya"], required=True)
    parser.add_argument("--chapters", default="all",
                        help="'all', single number, or range like '1-5'")
    args = parser.parse_args()

    meta = CC_SECTIONS[args.section]
    max_ch = meta["chapters"]

    if args.chapters == "all":
        chapters = list(range(1, max_ch + 1))
    elif "-" in args.chapters:
        a, b = args.chapters.split("-")
        chapters = list(range(int(a), int(b) + 1))
    else:
        chapters = [int(args.chapters)]

    asyncio.run(scrape_cc(args.section, chapters))


if __name__ == "__main__":
    main()

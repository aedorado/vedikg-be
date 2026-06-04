"""
BRS (Bhakti-rasāmṛta-sindhu) EPUB Scraper
==========================================
Processes two BRS EPUB volumes and stores them in the database.

Structure:
  Vol 1 → Eastern Section (4 waves) + Southern Section (5 waves)
  Vol 2 → Western Section (5 waves) + Northern Section (9 waves)

DB mapping:
  Section → Canto   (Eastern=1, Southern=2, Western=3, Northern=4)
  Wave    → Chapter
  Verse   → Verse + Purport rows (one per commentary author)

Usage:
  venv/bin/python scrape_brs.py                           # all sections
  venv/bin/python scrape_brs.py --section 1 --wave 1      # one wave only
  venv/bin/python scrape_brs.py --dry-run                 # parse, no DB writes
  venv/bin/python scrape_brs.py --revert                  # delete all BRS data
"""

import argparse
import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.models import Book, Canto, Chapter, Verse, Purport, Author

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

EPUB_DIR = Path(__file__).parent / "epub" / "brs"

# (section_number, epub_filename)
EPUB_VOLUMES = [
    (1, "Bhakti Rasamrita Sindhu - Vol 01, translated by Bhanu Swami.epub"),
    (2, "Bhakti Rasamrita Sindhu - Vol 01, translated by Bhanu Swami.epub"),
    (3, "Bhakti Rasamrita Sindhu - Vol 02, translated by Bhanu Swami.epub"),
    (4, "Bhakti Rasamrita Sindhu - Vol 02, translated by Bhanu Swami.epub"),
]

SECTION_META = {
    1: {"slug": "eastern",  "label": "Eastern Section: Types of Bhakti"},
    2: {"slug": "southern", "label": "Southern Section: Components of Rasa"},
    3: {"slug": "western",  "label": "Western Section: Primary Bhakti Rasas"},
    4: {"slug": "northern", "label": "Northern Section: Secondary Bhakti Rasas"},
}

# Instead of a fixed set, match dynamically in _para_classes helper below
COMMENTARY_CLASS_PREFIXES = ("msonormal", "msobodytext", "msobodytextindent", "msoheading",
                              "msolistparagraph", "versequote", "sloka", "quote")

# Matches both single  ||1.1.5||  and ranges  ||1.1.18-19||
VERSE_REF_RE = re.compile(r"\|\|(\d+)\.(\d+)\.(\d+)(?:-(\d+))?\|\|")

JIVA_LABEL       = "Jīva Gosvāmī’s Commentary"
VISVANATHA_LABEL = "Viśvanātha Cakravartī Ṭhākura’s Commentary"


@dataclass
class CommentaryBlock:
    author_label: str   # JIVA_LABEL or VISVANATHA_LABEL
    text: str
    html: str


@dataclass
class ParsedVerse:
    section: int
    wave: int
    verse: int
    full_ref: str
    sanskrit: str
    translation: str
    commentaries: list[CommentaryBlock] = field(default_factory=list)
    # {footnote_number → footnote_text} for footnotes referenced in this verse's commentaries
    footnotes: dict[str, str] = field(default_factory=dict)


# ── EPUB parsing ──────────────────────────────────────────────────────────────

def _ordered_html_files(zf: zipfile.ZipFile) -> list[str]:
    files = [f for f in zf.namelist() if re.match(r"text/part\d+.*\.html$", f)]
    return sorted(files)


def _para_classes(p) -> set:
    return set(p.get("class") or [])


def _para_text(p) -> str:
    return " ".join(p.get_text().split())


def _load_footnotes(zf: zipfile.ZipFile) -> dict[str, str]:
    """Build a footnote map {number_str → text} from the EPUB's footnote definition file.
    Vol 1: split_049.html  |  Vol 2: split_062.html
    """
    footnotes: dict[str, str] = {}
    files = sorted(f for f in zf.namelist() if re.match(r"text/part.*\.html$", f))
    # Footnote defs are always the last content file
    for fname in reversed(files):
        html = zf.read(fname).decode("utf-8")
        if 'id="_ftn1"' in html:
            soup = BeautifulSoup(html, "html.parser")
            for elem in soup.find_all(id=re.compile(r"^_ftn\d+$")):
                num_m = re.search(r"_ftn(\d+)$", elem["id"])
                if not num_m:
                    continue
                num = num_m.group(1)
                parent = elem.find_parent("p") or elem.find_parent("div") or elem
                # Strip the leading [n] from the footnote text itself
                text = " ".join(parent.get_text().split())
                text = re.sub(r"^\[\d+\]\s*", "", text)
                footnotes[num] = text
            break
    log.info("  Loaded %d footnotes", len(footnotes))
    return footnotes


def _strip_footnote_anchors(p) -> None:
    """Remove <a id="_ftnrefN"> footnote reference anchors from a tag in-place.
    Used for VERSE TEXT only — commentary keeps [n] markers for interactive display."""
    import copy as _copy
    for a in p.find_all("a", id=re.compile(r"_ftnref\d+")):
        a.decompose()


_BR = "\x00BR\x00"  # sentinel to mark real <br> line breaks

def _extract_lines(p) -> list[str]:
    """Replace <br> with a sentinel, then collapse HTML-source whitespace within
    each segment, returning a list of non-empty lines."""
    import copy
    para = copy.copy(p)
    for br in para.find_all("br"):
        br.replace_with(_BR)
    text = para.get_text()
    # Split only on explicit <br> sentinels; collapse all other whitespace
    segments = text.split(_BR)
    return [" ".join(seg.split()) for seg in segments]


def _sanskrit_text(p) -> str:
    """Extract Sanskrit verse text preserving only explicit <br> line breaks.
    - Keeps [n] footnote markers (rendered as interactive superscripts in the UI)
    - Keeps ||n|| inline verse-number markers (authentic Sanskrit formatting)
    - Only strips the outer vgversenos ref e.g. ||1.1.5|| handled at call site
    """
    lines = _extract_lines(p)
    return "\n".join(ln for ln in lines if ln)


def _clean_commentary_text(p) -> str:
    """Extract commentary paragraph text.
    - Preserves only explicit <br> line breaks (Sanskrit quotes inside commentary)
    - HTML source word-wrap newlines are collapsed to spaces
    - Keeps [n] footnote markers for interactive superscript rendering
    """
    lines = _extract_lines(p)
    return "\n".join(ln for ln in lines if ln)


def _find_section_file_ranges(zf: zipfile.ZipFile, target_section: int) -> list[str]:
    """Return ordered list of HTML filenames belonging to target_section."""
    nav = BeautifulSoup(zf.read("nav.xhtml").decode(), "html.parser")
    section_items = [li for li in nav.select("nav > ol > li") if li.find("ol")]

    epub_section_idx = (target_section - 1) % 2
    if epub_section_idx >= len(section_items):
        return []

    this_section = section_items[epub_section_idx]
    next_section = section_items[epub_section_idx + 1] if epub_section_idx + 1 < len(section_items) else None

    this_start = "text/" + this_section.find("a")["href"].replace("text/", "")
    next_start  = ("text/" + next_section.find("a")["href"].replace("text/", "")) if next_section else None

    all_files = _ordered_html_files(zf)
    in_range, result = False, []
    for f in all_files:
        if f == this_start:
            in_range = True
        if in_range:
            if next_start and f == next_start:
                break
            result.append(f)
    return result


def _parse_verses_from_soup(soup: BeautifulSoup, section: int,
                             wave_filter: Optional[int] = None) -> list[ParsedVerse]:
    verses: list[ParsedVerse] = []
    all_paras = soup.find_all("p")

    i = 0
    while i < len(all_paras):
        p = all_paras[i]
        if "vgversenos" not in _para_classes(p):
            i += 1
            continue

        text = _para_text(p)
        m = VERSE_REF_RE.match(text)
        if not m:
            i += 1
            continue

        sec, wave, verse_start = int(m.group(1)), int(m.group(2)), int(m.group(3))
        verse_end = int(m.group(4)) if m.group(4) else verse_start
        is_range = verse_end > verse_start
        # full_ref e.g. "BRS 1.1.18-19" or "BRS 1.1.5"
        full_ref = f"BRS {sec}.{wave}.{verse_start}" + (f"-{verse_end}" if is_range else "")

        if sec != section or (wave_filter is not None and wave != wave_filter):
            i += 1
            continue

        # Sanskrit — collect vgmainverse paragraphs.
        # For multi-verse blocks some continued verses may appear in msonormal class
        # (they contain inline ||n|| markers identifying each sub-verse).
        j = i + 1
        sanskrit_parts = []
        while j < len(all_paras):
            np = all_paras[j]
            np_cls = _para_classes(np)
            np_txt = _para_text(np)
            if "vgmainverse" in np_cls:
                sanskrit_parts.append(_sanskrit_text(np))
                j += 1
            elif is_range and np_cls & {"msonormal", "msonormal2"} and re.search(r"\|\|\d+\|\|", np_txt):
                # Continuation verse in a multi-verse block
                sanskrit_parts.append(_sanskrit_text(np))
                j += 1
            else:
                break

        # Translation(s) (vgtranslation)
        translation_parts = []
        while j < len(all_paras) and "vgtranslation" in _para_classes(all_paras[j]):
            t = re.sub(r"^Translation:\s*", "", _para_text(all_paras[j]))
            if t:
                translation_parts.append(t)
            j += 1

        # Commentary blocks — each block starts with a vgversenos label
        commentaries: list[CommentaryBlock] = []
        com_author: Optional[str] = None
        com_text: list[str] = []
        com_html: list[str] = []

        def _flush() -> None:
            if com_author and com_text:
                commentaries.append(CommentaryBlock(
                    author_label=com_author,
                    text="\n\n".join(com_text),
                    html="".join(com_html),
                ))

        while j < len(all_paras):
            np = all_paras[j]
            np_classes = _para_classes(np)
            np_text = _para_text(np)

            if "vgversenos" in np_classes:
                if VERSE_REF_RE.match(np_text):
                    break   # Next verse starts
                # Vol 1 style: commentary author label inside vgversenos
                _flush()
                com_author = np_text if np_text in (JIVA_LABEL, VISVANATHA_LABEL) else None
                com_text = []
                com_html = []
                j += 1
                continue

            if "vgcommheading" in np_classes:
                # Vol 2 style: commentary author label in its own class
                _flush()
                com_author = np_text if np_text in (JIVA_LABEL, VISVANATHA_LABEL) else None
                com_text = []
                com_html = []
                j += 1
                continue

            if any(cls.startswith(COMMENTARY_CLASS_PREFIXES) for cls in np_classes):
                cleaned = _clean_commentary_text(np)
                if cleaned:
                    com_text.append(cleaned)
                    com_html.append(str(np))
            j += 1

        _flush()

        if sanskrit_parts:
            # Collect footnote numbers referenced in this verse's commentary
            verse_footnotes: dict[str, str] = {}
            for com in commentaries:
                for num in re.findall(r"\[(\d+)\]", com.text):
                    verse_footnotes[num] = ""  # text filled in after epub footnotes loaded
            verses.append(ParsedVerse(
                section=sec,
                wave=wave,
                verse=verse_start,
                full_ref=full_ref,
                sanskrit="\n".join(sanskrit_parts),
                translation="\n\n".join(translation_parts),
                commentaries=commentaries,
                footnotes=verse_footnotes,
            ))
        i = j

    return verses


def parse_epub(epub_path: Path, section: int,
               wave_filter: Optional[int] = None) -> list[ParsedVerse]:
    with zipfile.ZipFile(epub_path) as zf:
        # Load all footnote definitions from this EPUB up front
        all_footnotes = _load_footnotes(zf)

        file_range = _find_section_file_ranges(zf, section)
        if not file_range:
            log.warning("Section %d not found in %s", section, epub_path.name)
            return []
        log.info("Section %d: %d HTML files", section, len(file_range))
        verses = []
        for fname in file_range:
            html = zf.read(fname).decode("utf-8")
            soup = BeautifulSoup(html, "html.parser")
            verses.extend(_parse_verses_from_soup(soup, section, wave_filter))

        # Resolve footnote texts now that we have the full map
        for v in verses:
            v.footnotes = {num: all_footnotes.get(num, "") for num in v.footnotes}

    return verses


def _wave_title(section_num: int, wave_num: int, epub_path: Path) -> str:
    try:
        with zipfile.ZipFile(epub_path) as zf:
            nav = BeautifulSoup(zf.read("nav.xhtml").decode(), "html.parser")
            section_items = [li for li in nav.select("nav > ol > li") if li.find("ol")]
            idx = (section_num - 1) % 2
            if idx < len(section_items):
                waves = section_items[idx].select("ol li a")
                # index 0 = section header link; wave 1 starts at index 1
                if wave_num < len(waves):
                    return waves[wave_num].get_text().strip()
    except Exception:
        pass
    return f"Wave {wave_num}"


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_or_create_book(db: Session) -> Book:
    book = db.query(Book).filter_by(code="BRS").first()
    if not book:
        book = Book(
            code="BRS",
            title="Bhakti-rasāmṛta-sindhu",
            author="Śrīla Rūpa Gosvāmī",
            translator="Bhānu Swāmī",
            commentary_name="Commentary",
            commentary_author="Jīva Gosvāmī & Viśvanātha Cakravartī Ṭhākura",
        )
        db.add(book)
        db.flush()
        log.info("Created Book: BRS")
    return book


def _get_or_create_author(db: Session, name: str, slug: str) -> Author:
    author = db.query(Author).filter_by(slug=slug).first()
    if not author:
        author = Author(name=name, slug=slug)
        db.add(author)
        db.flush()
    return author


def _get_or_create_canto(db: Session, book: Book, section_num: int) -> Canto:
    canto = db.query(Canto).filter_by(book_id=book.id, number=section_num).first()
    if not canto:
        meta = SECTION_META[section_num]
        canto = Canto(
            book_id=book.id,
            number=section_num,
            title=meta["label"],
            slug=f"brs-{meta['slug']}",
            section_label=meta["label"],
        )
        db.add(canto)
        db.flush()
        log.info("Created Canto: %s", meta["label"])
    return canto


def _get_or_create_chapter(db: Session, canto: Canto, wave_num: int, title: str) -> Chapter:
    chapter = db.query(Chapter).filter_by(canto_id=canto.id, chapter_number=wave_num).first()
    if not chapter:
        slug = f"brs-{SECTION_META[canto.number]['slug']}-wave-{wave_num}"
        try:
            chapter = Chapter(canto_id=canto.id, chapter_number=wave_num, title=title, slug=slug)
            db.add(chapter)
            db.flush()
            log.info("  Created Chapter: %s", title)
        except Exception:
            # Another process may have inserted concurrently — rollback and re-fetch
            db.rollback()
            chapter = db.query(Chapter).filter_by(canto_id=canto.id, chapter_number=wave_num).first()
    return chapter


# ── Revert ────────────────────────────────────────────────────────────────────

def revert(db: Session) -> None:
    """Delete all BRS data from the database (verses, purports, chapters, cantos, book)."""
    book = db.query(Book).filter_by(code="BRS").first()
    if not book:
        log.info("No BRS book found — nothing to revert.")
        return

    # Collect all verse IDs for this book
    verse_ids = [v.id for v in db.query(Verse.id).filter_by(book_id=book.id).all()]
    if verse_ids:
        deleted_purports = db.query(Purport).filter(Purport.verse_id.in_(verse_ids)).delete(synchronize_session=False)
        log.info("Deleted %d purport rows", deleted_purports)

    # Clear prev/next links before deleting verses (self-referential FKs)
    if verse_ids:
        db.query(Verse).filter(Verse.id.in_(verse_ids)).update(
            {"previous_verse_id": None, "next_verse_id": None},
            synchronize_session=False,
        )
        db.flush()
        deleted_verses = db.query(Verse).filter(Verse.id.in_(verse_ids)).delete(synchronize_session=False)
        log.info("Deleted %d verse rows", deleted_verses)

    # Delete chapters and cantos
    canto_ids = [c.id for c in db.query(Canto.id).filter_by(book_id=book.id).all()]
    if canto_ids:
        deleted_chapters = db.query(Chapter).filter(Chapter.canto_id.in_(canto_ids)).delete(synchronize_session=False)
        log.info("Deleted %d chapter rows", deleted_chapters)
        db.query(Canto).filter(Canto.id.in_(canto_ids)).delete(synchronize_session=False)
        log.info("Deleted %d canto rows", len(canto_ids))

    db.delete(book)
    db.commit()
    log.info("BRS book record deleted. Revert complete.")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(section_filter: Optional[int], wave_filter: Optional[int],
        dry_run: bool, repurport: bool = False) -> None:
    db = None if dry_run else SessionLocal()
    try:
        book = None if dry_run else _get_or_create_book(db)

        author_jiva = None if dry_run else _get_or_create_author(
            db, "Jīva Gosvāmī", "jiva-gosvami"
        )
        author_visva = None if dry_run else _get_or_create_author(
            db, "Viśvanātha Cakravartī Ṭhākura", "visvanatha-cakravarti-thakura"
        )

        author_map = {
            JIVA_LABEL:       author_jiva,
            VISVANATHA_LABEL: author_visva,
        }

        cantos: dict[int, Canto] = {}
        chapters: dict[tuple, Chapter] = {}
        total_new = 0
        prev_verse_obj: Optional[Verse] = None

        for section_num, epub_filename in EPUB_VOLUMES:
            if section_filter is not None and section_num != section_filter:
                continue

            epub_path = EPUB_DIR / epub_filename
            if not epub_path.exists():
                log.error("EPUB not found: %s", epub_path)
                continue

            log.info("Parsing section %d (%s)...", section_num, SECTION_META[section_num]["label"])
            verses = parse_epub(epub_path, section_num, wave_filter)

            if not verses:
                log.warning("No verses found for section %d wave %s", section_num, wave_filter)
                continue

            log.info("  %d verses parsed", len(verses))

            if dry_run:
                for v in verses[:3]:
                    coms = [(c.author_label[:20], c.text[:50]) for c in v.commentaries]
                    log.info("  [DRY] %s | %s... | commentaries: %s",
                             v.full_ref, v.sanskrit[:50], coms)
                log.info("  [DRY] ... and %d more", max(0, len(verses) - 3))
                total_new += len(verses)
                continue

            BATCH = 20  # commit every N verses

            if section_num not in cantos:
                cantos[section_num] = _get_or_create_canto(db, book, section_num)

            canto = cantos[section_num]

            # Pre-load all existing verse references for this section to avoid per-verse SELECTs
            existing_refs: set[str] = set(
                r[0] for r in db.query(Verse.full_reference)
                .filter(Verse.book_id == book.id)
                .all()
            )

            batch_count = 0
            for pv in verses:
                if pv.full_ref in existing_refs:
                    if repurport and pv.commentaries:
                        # Verse exists — just add missing purports
                        verse_obj = db.query(Verse).filter_by(
                            book_id=book.id, full_reference=pv.full_ref
                        ).first()
                        if verse_obj:
                            existing_authors = {p.author_id for p in db.query(Purport).filter_by(verse_id=verse_obj.id).all()}
                            for com in pv.commentaries:
                                author_obj = author_map.get(com.author_label)
                                if author_obj and author_obj.id not in existing_authors:
                                    db.add(Purport(
                                        verse_id=verse_obj.id,
                                        author_id=author_obj.id,
                                        body_text=com.text,
                                        body_html=com.html,
                                    ))
                                    total_new += 1
                            batch_count += 1
                            if batch_count % BATCH == 0:
                                db.commit()
                                log.info("    committed purport batch (%d so far)", batch_count)
                    continue

                key = (section_num, pv.wave)
                if key not in chapters:
                    title = _wave_title(section_num, pv.wave, epub_path)
                    chapters[key] = _get_or_create_chapter(db, canto, pv.wave, title)

                chapter = chapters[key]

                verse_obj = Verse(
                    chapter_id=chapter.id,
                    book_id=book.id,
                    verse_number=pv.verse,
                    full_reference=pv.full_ref,
                    transliteration=pv.sanskrit,
                    translation=pv.translation,
                    synonyms_raw=json.dumps(pv.footnotes, ensure_ascii=False) if pv.footnotes else None,
                )
                db.add(verse_obj)
                db.flush()  # get verse_obj.id

                for com in pv.commentaries:
                    author_obj = author_map.get(com.author_label)
                    if author_obj:
                        db.add(Purport(
                            verse_id=verse_obj.id,
                            author_id=author_obj.id,
                            body_text=com.text,
                            body_html=com.html,
                        ))

                if prev_verse_obj and prev_verse_obj.book_id == book.id:
                    prev_verse_obj.next_verse_id = verse_obj.id
                    verse_obj.previous_verse_id = prev_verse_obj.id

                prev_verse_obj = verse_obj
                existing_refs.add(pv.full_ref)
                total_new += 1
                batch_count += 1

                if batch_count % BATCH == 0:
                    db.commit()
                    log.info("    committed batch (%d so far this section)", batch_count)

            # Commit remainder
            db.commit()
            log.info("  Section %d done — %d items written", section_num, batch_count)

        if dry_run:
            log.info("DRY RUN complete — would insert %d verses.", total_new)
        else:
            log.info("Done. Inserted %d new verses.", total_new)

    finally:
        if db:
            db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BRS EPUB scraper")
    parser.add_argument("--section",   type=int, help="Only scrape this section (1-4)")
    parser.add_argument("--wave",      type=int, help="Only scrape this wave number")
    parser.add_argument("--dry-run",   action="store_true", help="Parse only, no DB writes")
    parser.add_argument("--revert",    action="store_true", help="Delete all BRS data from DB")
    parser.add_argument("--repurport", action="store_true",
                        help="For existing verses, insert any missing purport rows (use after fixing commentary parsing)")
    args = parser.parse_args()

    if args.revert:
        db = SessionLocal()
        try:
            revert(db)
        finally:
            db.close()
    else:
        run(
            section_filter=args.section,
            wave_filter=args.wave,
            dry_run=args.dry_run,
            repurport=args.repurport,
        )

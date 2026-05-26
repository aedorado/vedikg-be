from collections import defaultdict
import json as _json

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from app.db.base import get_db
from app.models.models import Verse, Chapter, Canto, Book, Purport, Author

# CC section slug → display label
CC_SECTIONS = {
    "adi":    (1, "Ādi-līlā"),
    "madhya": (2, "Madhya-līlā"),
    "antya":  (3, "Antya-līlā"),
}

def _reference_to_slug(full_reference: str) -> str:
    """Convert 'SB 1.1.3' → '1/1/3'  |  'CC Adi 1.1' → 'adi/1/1'"""
    if full_reference.startswith("CC "):
        # CC Adi 1.7 → adi/1/7
        rest = full_reference[3:]
        parts = rest.split(" ", 1)  # ['Adi', '1.7']
        if len(parts) == 2:
            section = parts[0].lower()
            nums = parts[1].replace(".", "/")
            return f"{section}/{nums}"
        return rest.replace(".", "/")
    return full_reference.replace("SB ", "").replace(".", "/")


def _slug_to_sb_reference(slug: str) -> str:
    """Convert '1/1/3' or '10/64/14-15' → 'SB 1.1.3'"""
    return "SB " + slug.replace("/", ".")


router = APIRouter(prefix="/api/verses", tags=["verses"])

@router.get("/")
def list_verses(skip: int = Query(0), limit: int = Query(20), db: Session = Depends(get_db)):
    verses = db.query(Verse).offset(skip).limit(limit).all()
    total = db.query(Verse).count()
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "verses": [
            {
                "id": v.id,
                "reference": v.full_reference,
                "verse_slug": _reference_to_slug(v.full_reference),
                "translation": v.translation,
            }
            for v in verses
        ],
    }

@router.get("/sb/{slug:path}")
def get_verse_by_slug(slug: str, db: Session = Depends(get_db)):
    """
    /api/verses/sb/9/7   → chapter listing (2 segments)
    /api/verses/sb/9/7/1 → verse detail  (3+ segments)
    """
    parts = slug.rstrip('/').split('/')
    sb_book = db.query(Book).filter_by(code='SB').first()
    if len(parts) == 2:
        try:
            canto_num, chapter_num = int(parts[0]), int(parts[1])
        except ValueError:
            return {"error": "Invalid chapter path"}
        canto = db.query(Canto).filter_by(book_id=sb_book.id if sb_book else None, number=canto_num).first() \
                or db.query(Canto).filter_by(number=canto_num).first()
        if not canto:
            return {"error": f"Canto {canto_num} not found"}
        chapter = db.query(Chapter).filter_by(canto_id=canto.id, chapter_number=chapter_num).first()
        if not chapter:
            return {"error": f"SB {canto_num}.{chapter_num} not found"}
        verses = db.query(Verse).filter_by(chapter_id=chapter.id).order_by(Verse.verse_number).all()
        return {
            "canto": canto_num,
            "chapter": chapter_num,
            "title": chapter.title,
            "total": len(verses),
            "verses": [
                {
                    "id": v.id,
                    "reference": v.full_reference,
                    "verse_slug": _reference_to_slug(v.full_reference),
                    "devanagari": v.devanagari,
                    "transliteration": v.transliteration,
                    "translation": v.translation,
                    "chanda": v.chanda,
                }
                for v in verses
            ],
        }
    full_reference = _slug_to_sb_reference(slug)
    verse = db.query(Verse).filter(Verse.full_reference == full_reference).first()
    if not verse:
        return {"error": f"Verse {full_reference} not found"}
    return _verse_response(verse, db)


@router.get("/cc/{section}")
def list_cc_chapters(section: str, db: Session = Depends(get_db)):
    """GET /api/verses/cc/adi  →  list of chapters with verse counts"""
    section = section.lower()
    if section not in CC_SECTIONS:
        raise HTTPException(404, f"Unknown CC section '{section}'")
    section_number, section_label = CC_SECTIONS[section]
    cc_book = db.query(Book).filter_by(code='CC').first()
    if not cc_book:
        raise HTTPException(404, "CC not scraped yet")
    canto = db.query(Canto).filter_by(book_id=cc_book.id, number=section_number).first()
    if not canto:
        return []
    chapters = (
        db.query(Chapter)
        .filter_by(canto_id=canto.id)
        .order_by(Chapter.chapter_number)
        .all()
    )
    return [
        {
            "chapter_number": ch.chapter_number,
            "title": ch.title,
            "summary": ch.summary[:300] if ch.summary else None,
            "verse_count": db.query(Verse).filter_by(chapter_id=ch.id).count(),
        }
        for ch in chapters
    ]


@router.get("/cc/{section}/{chapter_num:int}")
def get_cc_chapter(section: str, chapter_num: int, db: Session = Depends(get_db)):
    """GET /api/verses/cc/adi/1  →  All verses in CC Ādi-līlā 1"""
    section = section.lower()
    if section not in CC_SECTIONS:
        raise HTTPException(404, f"Unknown CC section '{section}'. Use: adi, madhya, antya")
    section_number, section_label = CC_SECTIONS[section]
    cc_book = db.query(Book).filter_by(code='CC').first()
    if not cc_book:
        raise HTTPException(404, "CC book not found in database")
    canto = db.query(Canto).filter_by(book_id=cc_book.id, number=section_number).first()
    if not canto:
        raise HTTPException(404, f"CC {section_label} not scraped yet")
    chapter = db.query(Chapter).filter_by(canto_id=canto.id, chapter_number=chapter_num).first()
    if not chapter:
        raise HTTPException(404, f"CC {section_label} chapter {chapter_num} not found")
    verses = (
        db.query(Verse)
        .filter_by(chapter_id=chapter.id)
        .order_by(Verse.verse_number)
        .all()
    )
    return {
        "section": section,
        "section_label": section_label,
        "chapter_number": chapter_num,
        "title": chapter.title,
        "summary": chapter.summary,
        "verses": [_verse_response(v, db) for v in verses],
    }


@router.get("/cc/{section}/{chapter_num:int}/{verse_num:int}")
def get_cc_verse(section: str, chapter_num: int, verse_num: int, db: Session = Depends(get_db)):
    """GET /api/verses/cc/adi/1/7  →  CC Ādi-līlā 1.7"""
    section = section.lower()
    if section not in CC_SECTIONS:
        raise HTTPException(404, f"Unknown CC section '{section}'. Use: adi, madhya, antya")
    section_number, section_label = CC_SECTIONS[section]
    cc_book = db.query(Book).filter_by(code='CC').first()
    if not cc_book:
        raise HTTPException(404, "CC book not found in database")
    canto = db.query(Canto).filter_by(book_id=cc_book.id, number=section_number).first()
    if not canto:
        raise HTTPException(404, f"CC {section_label} not scraped yet")
    chapter = db.query(Chapter).filter_by(canto_id=canto.id, chapter_number=chapter_num).first()
    if not chapter:
        raise HTTPException(404, f"CC {section_label} chapter {chapter_num} not found")
    verse = db.query(Verse).filter_by(chapter_id=chapter.id, verse_number=verse_num).first()
    if not verse:
        raise HTTPException(404, f"CC {section_label} {chapter_num}.{verse_num} not found")
    return _verse_response(verse, db)


# CB (Caitanya Bhagavata) endpoints
CB_KHANDAS = {
    "adi": (1, "Ādi-khaṇḍa"),
    "madhya": (2, "Madhya-khaṇḍa"),
    "antya": (3, "Antya-khaṇḍa"),
}

@router.get("/cb/{khanda}")
def list_cb_chapters(khanda: str, db: Session = Depends(get_db)):
    """GET /api/verses/cb/adi  →  list of chapters in Ādi-khaṇḍa"""
    khanda = khanda.lower()
    if khanda not in CB_KHANDAS:
        raise HTTPException(404, f"Unknown CB khanda '{khanda}'. Use: adi, madhya, antya")
    khanda_number, khanda_label = CB_KHANDAS[khanda]
    cb_book = db.query(Book).filter_by(code='CB').first()
    if not cb_book:
        raise HTTPException(404, "CB not scraped yet")
    canto = db.query(Canto).filter_by(book_id=cb_book.id, number=khanda_number).first()
    if not canto:
        return []
    chapters = (
        db.query(Chapter)
        .filter_by(canto_id=canto.id)
        .order_by(Chapter.chapter_number)
        .all()
    )
    return [
        {
            "chapter_number": ch.chapter_number,
            "title": ch.title,
            "summary": ch.summary[:300] if ch.summary else None,
            "verse_count": db.query(Verse).filter_by(chapter_id=ch.id).count(),
        }
        for ch in chapters
    ]


@router.get("/cb/{khanda}/{chapter_num:int}")
def get_cb_chapter(khanda: str, chapter_num: int, db: Session = Depends(get_db)):
    """GET /api/verses/cb/adi/9  →  All verses in CB Ādi-khaṇḍa chapter 9"""
    khanda = khanda.lower()
    if khanda not in CB_KHANDAS:
        raise HTTPException(404, f"Unknown CB khanda '{khanda}'. Use: adi, madhya, antya")
    khanda_number, khanda_label = CB_KHANDAS[khanda]
    cb_book = db.query(Book).filter_by(code='CB').first()
    if not cb_book:
        raise HTTPException(404, "CB book not found in database")
    canto = db.query(Canto).filter_by(book_id=cb_book.id, number=khanda_number).first()
    if not canto:
        raise HTTPException(404, f"CB {khanda_label} not scraped yet")
    chapter = db.query(Chapter).filter_by(canto_id=canto.id, chapter_number=chapter_num).first()
    if not chapter:
        raise HTTPException(404, f"CB {khanda_label} chapter {chapter_num} not found")
    verses = (
        db.query(Verse)
        .filter_by(chapter_id=chapter.id)
        .order_by(Verse.verse_number)
        .all()
    )
    return {
        "khanda": khanda,
        "khanda_label": khanda_label,
        "chapter_number": chapter_num,
        "title": chapter.title,
        "summary": chapter.summary,
        "verses": [_verse_response(v, db) for v in verses],
    }


@router.get("/cb/{khanda}/{chapter_num:int}/{verse_num:int}")
def get_cb_verse(khanda: str, chapter_num: int, verse_num: int, db: Session = Depends(get_db)):
    """GET /api/verses/cb/adi/9/7  →  CB Ādi-khaṇḍa 9.7"""
    khanda = khanda.lower()
    if khanda not in CB_KHANDAS:
        raise HTTPException(404, f"Unknown CB khanda '{khanda}'. Use: adi, madhya, antya")
    khanda_number, khanda_label = CB_KHANDAS[khanda]
    cb_book = db.query(Book).filter_by(code='CB').first()
    if not cb_book:
        raise HTTPException(404, "CB book not found in database")
    canto = db.query(Canto).filter_by(book_id=cb_book.id, number=khanda_number).first()
    if not canto:
        raise HTTPException(404, f"CB {khanda_label} not scraped yet")
    chapter = db.query(Chapter).filter_by(canto_id=canto.id, chapter_number=chapter_num).first()
    if not chapter:
        raise HTTPException(404, f"CB {khanda_label} chapter {chapter_num} not found")
    verse = db.query(Verse).filter_by(chapter_id=chapter.id, verse_number=verse_num).first()
    if not verse:
        raise HTTPException(404, f"CB {khanda_label} {chapter_num}.{verse_num} not found")
    return _verse_response(verse, db)

@router.get("/{verse_id}")
def get_verse(verse_id: int, db: Session = Depends(get_db)):
    verse = db.query(Verse).filter_by(id=verse_id).first()
    if not verse:
        return {"error": "Verse not found"}
    return _verse_response(verse, db)


def _verse_response(verse: Verse, db: Session):
    prev_verse = (
        db.query(Verse)
        .filter(Verse.id < verse.id)
        .order_by(Verse.id.desc())
        .first()
    )
    next_verse = (
        db.query(Verse)
        .filter(Verse.id > verse.id)
        .order_by(Verse.id.asc())
        .first()
    )
    # Purports with author info
    purport_data = [
        {
            "author": p.author.name if p.author else "Unknown",
            "author_slug": p.author.slug if p.author else None,
            "body_text": p.body_text,
            "body_html": p.body_html,
            "language": p.language,
        }
        for p in verse.purports
    ]
    return {
        "id": verse.id,
        "full_reference": verse.full_reference,
        "verse_slug": _reference_to_slug(verse.full_reference),
        "reference": verse.full_reference,
        "book": verse.book_id,
        "language": verse.language,
        "devanagari": verse.devanagari,
        "transliteration": verse.transliteration,
        "translation": verse.translation,
        "synonyms_raw": verse.synonyms_raw,
        # Legacy fields kept for backward compat
        "purport_text": verse.purport_text,
        "purport_html": verse.purport_html,
        # New structured purports
        "purports": purport_data,
        "chanda": verse.chanda,
        "chanda_detail": _json.loads(verse.chanda_json) if verse.chanda_json else None,
        "entities": [
            {"id": ve.entity.id, "name": ve.entity.name, "mention_location": ve.mention_location}
            for ve in verse.entities
        ],
        "prev_slug": _reference_to_slug(prev_verse.full_reference) if prev_verse else None,
        "next_slug": _reference_to_slug(next_verse.full_reference) if next_verse else None,
        "prev_reference": prev_verse.full_reference if prev_verse else None,
        "next_reference": next_verse.full_reference if next_verse else None,
    }

@router.get("/chapter/{chapter_id}")
def get_chapter_verses(chapter_id: int, db: Session = Depends(get_db)):
    verses = db.query(Verse).filter_by(chapter_id=chapter_id).all()
    return [
        {
            "id": v.id,
            "reference": v.full_reference,
            "verse_slug": _reference_to_slug(v.full_reference),
            "translation": v.translation,
        }
        for v in verses
    ]


@router.get("/word/{word:path}")
def get_word_usages(word: str, db: Session = Depends(get_db)):
    """
    Return all verses containing `word` in synonyms_raw, grouped by English meaning.
    e.g. GET /api/verses/word/uvāca
    → { word, groups: [{meaning, verses: [{ref, slug}]}] }
    """
    needle = word.lower()
    matches = (
        db.query(Verse)
        .filter(func.lower(Verse.synonyms_raw).contains(needle))
        .filter(Verse.synonyms_raw.isnot(None))
        .all()
    )

    meaning_map: dict[str, list[dict]] = defaultdict(list)
    for verse in matches:
        for entry in verse.synonyms_raw.split(" ; "):
            parts = entry.split(" — ", 1)
            if len(parts) != 2:
                continue
            word_part, meaning = parts[0].strip(), parts[1].strip()
            # Match if needle equals word_part OR appears as a whitespace-separated token
            tokens = [t.strip("-–") for t in word_part.lower().split()]
            if word_part.lower() != needle and needle not in tokens:
                continue
            ref = verse.full_reference
            meaning_map[meaning].append({
                "reference": ref,
                "slug": _reference_to_slug(ref),
            })

    groups = [
        {"meaning": m, "verses": refs}
        for m, refs in sorted(meaning_map.items())
    ]
    return {"word": word, "groups": groups}

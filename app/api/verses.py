from collections import defaultdict
import json as _json

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload, contains_eager
from app.db.base import get_db
from app.models.models import Verse, Chapter, Canto, Book, Purport, Author, VerseEntity, Entity

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

@router.get("/sb/chapters/{canto_num:int}")
def list_sb_chapters(canto_num: int, db: Session = Depends(get_db)):
    """GET /api/verses/sb/chapters/1  →  list of chapters in SB Canto 1"""
    sb_book = db.query(Book).filter_by(code='SB').first()
    if not sb_book:
        raise HTTPException(404, "SB not scraped yet")
    canto = db.query(Canto).filter_by(book_id=sb_book.id, number=canto_num).first()
    if not canto:
        raise HTTPException(404, f"SB Canto {canto_num} not found")

    # Single query: join chapters with verse counts
    from sqlalchemy import literal_column
    result = db.query(
        Chapter.id,
        Chapter.chapter_number,
        Chapter.title,
        Chapter.summary,
        func.count(Verse.id).label('verse_count')
    ).outerjoin(Verse, Verse.chapter_id == Chapter.id).filter(
        Chapter.canto_id == canto.id
    ).group_by(
        Chapter.id, Chapter.chapter_number, Chapter.title, Chapter.summary
    ).order_by(
        Chapter.chapter_number
    ).all()

    return [
        {
            "chapter_number": row[1],
            "title": row[2],
            "summary": row[3][:200] if row[3] else None,
            "verse_count": row[4],
        }
        for row in result
    ]


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
        if not sb_book:
            return {"error": "SB not scraped yet"}
        canto = db.query(Canto).filter_by(book_id=sb_book.id, number=canto_num).first()
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
    verse = (
        db.query(Verse)
        .filter(Verse.full_reference == full_reference)
        .options(selectinload(Verse.purports).selectinload(Purport.author), selectinload(Verse.entities).selectinload(VerseEntity.entity))
        .first()
    )
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
    chapter_ids = [ch.id for ch in chapters]
    counts = dict(
        db.query(Verse.chapter_id, func.count(Verse.id))
        .filter(Verse.chapter_id.in_(chapter_ids))
        .group_by(Verse.chapter_id)
        .all()
    ) if chapter_ids else {}
    return [
        {
            "chapter_number": ch.chapter_number,
            "title": ch.title,
            "summary": ch.summary[:300] if ch.summary else None,
            "verse_count": counts.get(ch.id, 0),
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
        .options(
            selectinload(Verse.purports).selectinload(Purport.author),
            selectinload(Verse.entities).selectinload(VerseEntity.entity),
        )
        .order_by(Verse.verse_number)
        .all()
    )
    return {
        "section": section,
        "section_label": section_label,
        "chapter_number": chapter_num,
        "title": chapter.title,
        "summary": chapter.summary,
        "verses": [_verse_response_no_nav(v) for v in verses],
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
    verse = (
        db.query(Verse)
        .filter_by(chapter_id=chapter.id, verse_number=verse_num)
        .options(selectinload(Verse.purports).selectinload(Purport.author), selectinload(Verse.entities).selectinload(VerseEntity.entity))
        .first()
    )
    if not verse:
        raise HTTPException(404, f"CC {section_label} {chapter_num}.{verse_num} not found")
    return _verse_response(verse, db)


# BRS (Bhakti-rasāmṛta-sindhu) endpoints
BRS_SECTIONS = {
    "eastern":  (1, "Eastern Section: Types of Bhakti"),
    "southern": (2, "Southern Section: Components of Rasa"),
    "western":  (3, "Western Section: Primary Bhakti Rasas"),
    "northern": (4, "Northern Section: Secondary Bhakti Rasas"),
}

@router.get("/brs/{section}")
def list_brs_waves(section: str, db: Session = Depends(get_db)):
    """GET /api/verses/brs/eastern  →  list of waves (chapters) with verse counts"""
    section = section.lower()
    if section not in BRS_SECTIONS:
        raise HTTPException(404, f"Unknown BRS section '{section}'. Use: eastern, southern, western, northern")
    section_number, section_label = BRS_SECTIONS[section]
    brs_book = db.query(Book).filter_by(code='BRS').first()
    if not brs_book:
        raise HTTPException(404, "BRS not scraped yet")
    canto = db.query(Canto).filter_by(book_id=brs_book.id, number=section_number).first()
    if not canto:
        return []
    chapters = (
        db.query(Chapter)
        .filter_by(canto_id=canto.id)
        .order_by(Chapter.chapter_number)
        .all()
    )
    chapter_ids = [ch.id for ch in chapters]
    counts = dict(
        db.query(Verse.chapter_id, func.count(Verse.id))
        .filter(Verse.chapter_id.in_(chapter_ids))
        .group_by(Verse.chapter_id)
        .all()
    ) if chapter_ids else {}
    return [
        {
            "wave_number": ch.chapter_number,
            "title": ch.title,
            "verse_count": counts.get(ch.id, 0),
        }
        for ch in chapters
    ]


@router.get("/brs/{section}/{wave_num:int}")
def get_brs_wave(section: str, wave_num: int, db: Session = Depends(get_db)):
    """GET /api/verses/brs/eastern/1  →  all verses in Eastern Wave 1"""
    section = section.lower()
    if section not in BRS_SECTIONS:
        raise HTTPException(404, f"Unknown BRS section '{section}'")
    section_number, section_label = BRS_SECTIONS[section]
    brs_book = db.query(Book).filter_by(code='BRS').first()
    if not brs_book:
        raise HTTPException(404, "BRS not scraped yet")
    canto = db.query(Canto).filter_by(book_id=brs_book.id, number=section_number).first()
    if not canto:
        raise HTTPException(404, f"BRS {section_label} not scraped yet")
    chapter = db.query(Chapter).filter_by(canto_id=canto.id, chapter_number=wave_num).first()
    if not chapter:
        raise HTTPException(404, f"BRS {section_label} Wave {wave_num} not found")
    # Skip purport loading for the wave listing — only need verse text
    verses = (
        db.query(Verse)
        .filter_by(chapter_id=chapter.id)
        .order_by(Verse.verse_number)
        .all()
    )
    return {
        "section": section,
        "section_label": section_label,
        "wave_number": wave_num,
        "title": chapter.title,
        # Minimal payload — full verse fetched individually on /brs/section/wave/verse
        "verses": [
            {
                "id": v.id,
                "full_reference": v.full_reference,
                "verse_number": v.verse_number,
                "transliteration": v.transliteration,
                "translation": (v.translation or "")[:200],
            }
            for v in verses
        ],
    }


@router.get("/brs/{section}/{wave_num:int}/{verse_num:int}")
def get_brs_verse(section: str, wave_num: int, verse_num: int, db: Session = Depends(get_db)):
    """GET /api/verses/brs/eastern/1/3  →  BRS 1.1.3"""
    section = section.lower()
    if section not in BRS_SECTIONS:
        raise HTTPException(404, f"Unknown BRS section '{section}'")
    section_number, section_label = BRS_SECTIONS[section]
    brs_book = db.query(Book).filter_by(code='BRS').first()
    if not brs_book:
        raise HTTPException(404, "BRS not scraped yet")
    canto = db.query(Canto).filter_by(book_id=brs_book.id, number=section_number).first()
    if not canto:
        raise HTTPException(404, f"BRS {section_label} not scraped yet")
    chapter = db.query(Chapter).filter_by(canto_id=canto.id, chapter_number=wave_num).first()
    if not chapter:
        raise HTTPException(404, f"BRS {section_label} Wave {wave_num} not found")
    verse = (
        db.query(Verse)
        .filter_by(chapter_id=chapter.id, verse_number=verse_num)
        .options(selectinload(Verse.purports).selectinload(Purport.author))
        .first()
    )
    if not verse:
        raise HTTPException(404, f"BRS {section_number}.{wave_num}.{verse_num} not found")
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
    chapter_ids = [ch.id for ch in chapters]
    counts = dict(
        db.query(Verse.chapter_id, func.count(Verse.id))
        .filter(Verse.chapter_id.in_(chapter_ids))
        .group_by(Verse.chapter_id)
        .all()
    ) if chapter_ids else {}
    return [
        {
            "chapter_number": ch.chapter_number,
            "title": ch.title,
            "summary": ch.summary[:300] if ch.summary else None,
            "verse_count": counts.get(ch.id, 0),
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
        .options(
            selectinload(Verse.purports).selectinload(Purport.author),
            selectinload(Verse.entities).selectinload(VerseEntity.entity),
        )
        .order_by(Verse.verse_number)
        .all()
    )
    return {
        "khanda": khanda,
        "khanda_label": khanda_label,
        "chapter_number": chapter_num,
        "title": chapter.title,
        "summary": chapter.summary,
        "verses": [_verse_response_no_nav(v) for v in verses],
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
    verse = (
        db.query(Verse)
        .filter_by(chapter_id=chapter.id, verse_number=verse_num)
        .options(selectinload(Verse.purports).selectinload(Purport.author), selectinload(Verse.entities).selectinload(VerseEntity.entity))
        .first()
    )
    if not verse:
        raise HTTPException(404, f"CB {khanda_label} {chapter_num}.{verse_num} not found")
    return _verse_response(verse, db)

@router.get("/{verse_id}")
def get_verse(verse_id: int, db: Session = Depends(get_db)):
    verse = (
        db.query(Verse)
        .filter_by(id=verse_id)
        .options(selectinload(Verse.purports).selectinload(Purport.author), selectinload(Verse.entities).selectinload(VerseEntity.entity))
        .first()
    )
    if not verse:
        return {"error": "Verse not found"}
    return _verse_response(verse, db)


def _purport_data(verse: Verse):
    return [
        {
            "author": p.author.name if p.author else "Unknown",
            "author_slug": p.author.slug if p.author else None,
            "body_text": p.body_text,
            "body_html": p.body_html,
            "language": p.language,
        }
        for p in verse.purports
    ]


def _verse_core(verse: Verse):
    """Fields shared by both response helpers."""
    # For BRS verses, synonyms_raw holds the footnote map JSON
    footnotes = None
    if verse.full_reference and verse.full_reference.startswith("BRS ") and verse.synonyms_raw:
        try:
            footnotes = _json.loads(verse.synonyms_raw)
        except Exception:
            pass

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
        "synonyms_raw": verse.synonyms_raw if not footnotes else None,
        "footnotes": footnotes,  # {number → text} for BRS, null for other books
        "purport_text": verse.purport_text,
        "purport_html": verse.purport_html,
        "purports": _purport_data(verse),
        "chanda": verse.chanda,
        "chanda_detail": _json.loads(verse.chanda_json) if verse.chanda_json else None,
        "entities": [
            {"id": ve.entity.id, "name": ve.entity.name, "mention_source": ve.mention_source}
            for ve in verse.entities
        ],
    }


def _verse_response_no_nav(verse: Verse):
    """Used when rendering a full chapter — skips prev/next nav queries."""
    return _verse_core(verse)


def _verse_response(verse: Verse, db: Session):
    # Use stored FK pointers when available; fall back to id-range queries
    prev_verse = None
    next_verse = None
    if verse.previous_verse_id:
        prev_verse = db.query(Verse.full_reference).filter_by(id=verse.previous_verse_id).scalar()
        prev_verse = type("_V", (), {"full_reference": prev_verse})() if prev_verse else None
    else:
        prev_verse = (
            db.query(Verse)
            .filter(Verse.id < verse.id)
            .order_by(Verse.id.desc())
            .first()
        )
    if verse.next_verse_id:
        next_ref = db.query(Verse.full_reference).filter_by(id=verse.next_verse_id).scalar()
        next_verse = type("_V", (), {"full_reference": next_ref})() if next_ref else None
    else:
        next_verse = (
            db.query(Verse)
            .filter(Verse.id > verse.id)
            .order_by(Verse.id.asc())
            .first()
        )
    data = _verse_core(verse)
    data.update({
        "prev_slug": _reference_to_slug(prev_verse.full_reference) if prev_verse else None,
        "next_slug": _reference_to_slug(next_verse.full_reference) if next_verse else None,
        "prev_reference": prev_verse.full_reference if prev_verse else None,
        "next_reference": next_verse.full_reference if next_verse else None,
    })
    return data

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

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, desc
from sqlalchemy.orm import Session
from typing import Optional
from app.db.base import get_db
from app.models.models import Verse, Chapter, Canto, Book

router = APIRouter(prefix="/api/chandas", tags=["chandas"])


@router.get("/")
def list_chandas(skip: int = Query(0), limit: int = Query(100), book: Optional[str] = Query(None), db: Session = Depends(get_db)):
    """List all unique chandas with verse counts, sorted by count descending"""
    
    query = db.query(
        Verse.chanda,
        func.count(Verse.id).label("verse_count")
    ).filter(
        Verse.chanda != None,
        Verse.chanda != ""
    )
    
    # Filter by book if specified
    if book:
        book_obj = db.query(Book).filter_by(code=book.upper()).first()
        if book_obj:
            query = query.filter(Verse.book_id == book_obj.id)
    
    chandas_query = query.group_by(
        Verse.chanda
    ).order_by(
        desc("verse_count")
    )
    
    total = chandas_query.count()
    chandas_data = chandas_query.offset(skip).limit(limit).all()
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "chandas": [
            {"name": name, "verse_count": count}
            for name, count in chandas_data
        ]
    }


@router.get("/{chanda_name}")
def get_chanda_verses(
    chanda_name: str,
    skip: int = Query(0),
    limit: int = Query(100),
    canto: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Get all verses for a specific chanda, sorted numerically by canto/chapter/verse"""
    import urllib.parse
    chanda_name = urllib.parse.unquote(chanda_name)

    base_q = (
        db.query(Verse)
        .join(Chapter, Verse.chapter_id == Chapter.id)
        .join(Canto, Chapter.canto_id == Canto.id)
        .filter(Verse.chanda == chanda_name)
    )
    if canto is not None:
        base_q = base_q.filter(Canto.number == canto)

    total = base_q.count()

    verses = (
        base_q
        .order_by(Canto.number, Chapter.chapter_number, Verse.verse_number)
        .offset(skip)
        .limit(limit)
        .all()
    )

    # Canto counts for filter pills
    canto_counts_q = (
        db.query(Canto.number, func.count(Verse.id).label("cnt"))
        .join(Chapter, Canto.id == Chapter.canto_id)
        .join(Verse, Chapter.id == Verse.chapter_id)
        .filter(Verse.chanda == chanda_name)
        .group_by(Canto.number)
        .order_by(Canto.number)
        .all()
    )

    return {
        "chanda": chanda_name,
        "total": total,
        "skip": skip,
        "limit": limit,
        "canto_counts": [{"canto": n, "count": c} for n, c in canto_counts_q],
        "verses": [
            {
                "id": v.id,
                "reference": v.full_reference,
                "verse_slug": v.full_reference.replace("SB ", "").replace(".", "/"),
                "canto": v.chapter.canto.number,
                "translation": v.translation[:150] + "..." if v.translation and len(v.translation) > 150 else v.translation
            }
            for v in verses
        ]
    }

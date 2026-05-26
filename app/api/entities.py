from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, distinct
from app.db.base import get_db
from app.models.models import Entity, VerseEntity, Relationship, Verse, Chapter, Canto, Book
from app.services.entity_service import EntityService

router = APIRouter(prefix="/api/entities", tags=["entities"])

@router.get("")
@router.get("/")
def list_entities(type: str = Query(None), book: str = Query(None), db: Session = Depends(get_db)):
    mentions_sq = (
        db.query(
            VerseEntity.entity_id,
            func.count(distinct(VerseEntity.verse_id)).label("verse_count"),
        )
        .group_by(VerseEntity.entity_id)
        .subquery()
    )
    q = db.query(Entity, mentions_sq.c.verse_count).join(mentions_sq, Entity.id == mentions_sq.c.entity_id)
    if type:
        types = [t.strip() for t in type.split(",")]
        q = q.filter(Entity.entity_type.in_(types))
    if book:
        book_obj = db.query(Book).filter_by(code=book.upper()).first()
        if book_obj:
            q = q.filter(
                Entity.id.in_(
                    db.query(VerseEntity.entity_id)
                    .join(Verse, VerseEntity.verse_id == Verse.id)
                    .filter(Verse.book_id == book_obj.id)
                    .subquery()
                )
            )
    rows = q.order_by(Entity.name).all()
    canto_rows = (
        db.query(VerseEntity.entity_id, Canto.number)
        .join(Verse, VerseEntity.verse_id == Verse.id)
        .join(Chapter, Verse.chapter_id == Chapter.id)
        .join(Canto, Chapter.canto_id == Canto.id)
        .filter(VerseEntity.mention_location.in_(["verse_text", "both"]))
        .distinct()
        .all()
    )
    canto_map: dict[int, list[int]] = {}
    for eid, cnum in canto_rows:
        canto_map.setdefault(eid, []).append(cnum)
    return [
        {
            "id": e.id,
            "name": e.name,
            "type": e.entity_type,
            "verse_count": vc or 0,
            "cantos": sorted(set(canto_map.get(e.id, []))),
        }
        for e, vc in rows
    ]

@router.get("/graph/all")
def get_full_graph(source: str = Query("verse"), db: Session = Depends(get_db)):
    """Return entities and relationships. source=verse (default) or source=all."""
    if source == "verse":
        verse_ids_sq = (
            db.query(VerseEntity.entity_id)
            .filter(VerseEntity.mention_location.in_(["verse_text", "both"]))
            .distinct()
            .subquery()
        )
        entities = db.query(Entity).filter(Entity.id.in_(verse_ids_sq)).all()
    else:
        entities = db.query(Entity).all()
    rels = db.query(Relationship).all()
    entity_id_set = {e.id for e in entities}
    nodes = [{"id": e.id, "name": e.name, "type": e.entity_type} for e in entities]
    edges = [
        {"source": r.source_entity_id, "target": r.target_entity_id, "type": r.relationship_type, "id": r.id}
        for r in rels
        if r.source_entity_id in entity_id_set and r.target_entity_id in entity_id_set
    ]
    return {"nodes": nodes, "edges": edges}

@router.get("/relationships/all")
def list_all_relationships(db: Session = Depends(get_db)):
    """Return all relationships as a flat list for the lineage table view."""
    rels = db.query(Relationship).all()
    entity_map = {
        e.id: {"name": e.name, "type": e.entity_type}
        for e in db.query(Entity).all()
    }
    # verse references
    verse_map = {
        v.id: v.full_reference
        for v in db.query(Verse.id, Verse.full_reference).all()
    }
    return [
        {
            "id": r.id,
            "source_id": r.source_entity_id,
            "source": entity_map.get(r.source_entity_id, {}).get("name", "?"),
            "target_id": r.target_entity_id,
            "target": entity_map.get(r.target_entity_id, {}).get("name", "?"),
            "type": r.relationship_type,
            "verse_ref": verse_map.get(r.source_verse_id) if r.source_verse_id else None,
        }
        for r in rels
    ]

@router.get("/{entity_id}")
def get_entity(entity_id: int, db: Session = Depends(get_db)):
    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {
        "id": entity.id,
        "name": entity.name,
        "type": entity.entity_type,
        "description": entity.description,
    }

@router.get("/{entity_id}/mentions")
def get_entity_mentions(entity_id: int, db: Session = Depends(get_db)):
    mentions = EntityService.get_entity_mentions(db, entity_id)
    if not mentions:
        raise HTTPException(status_code=404, detail="Entity not found")
    return mentions

@router.get("/{entity_id}/relationships")
def get_entity_relationships(entity_id: int, db: Session = Depends(get_db)):
    rels = EntityService.get_entity_relationships(db, entity_id)
    if not rels:
        raise HTTPException(status_code=404, detail="Entity not found")
    return rels

@router.get("/{entity_id}/graph")
def get_entity_graph(entity_id: int, depth: int = 1, db: Session = Depends(get_db)):
    graph = EntityService.get_entity_graph(db, entity_id, depth)
    if not graph:
        raise HTTPException(status_code=404, detail="Entity not found")
    return graph

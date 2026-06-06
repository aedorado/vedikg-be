"""API endpoints for AI-extracted entities and relationships."""

import json as _json
from fastapi import APIRouter, HTTPException
from db import get_conn

router = APIRouter(prefix="/api/ai", tags=["ai"])

FAMILY_RELS = {
    "father_of", "mother_of", "son_of", "daughter_of",
    "brother_of", "sister_of", "spouse_of",
    "uncle_of", "nephew_of", "cousin_of",
    "grandfather_of", "grandson_of",
}


@router.get("/personalities")
def list_ai_personalities(
    type: str | None = None,
    search: str | None = None,
    book: str | None = None,
    canto: int | None = None,
    chapter: int | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List personalities/entities excluding concepts."""
    conn = get_conn()
    cursor = conn.cursor()

    where_clauses = ["e.entity_type != 'concept'"]
    params = []
    join_clauses = ""

    if type:
        types = [t.strip() for t in type.split(",")]
        placeholders = ",".join(["%s"] * len(types))
        where_clauses.append(f"e.entity_type IN ({placeholders})")
        params.extend(types)

    if search:
        where_clauses.append(
            "(LOWER(e.name) LIKE %s OR LOWER(e.sanskrit_name) LIKE %s OR LOWER(e.aliases_json) LIKE %s)"
        )
        pattern = f"%{search.lower()}%"
        params.extend([pattern, pattern, pattern])

    # Book/canto/chapter filtering
    if book or canto or chapter:
        join_clauses += """
            JOIN verses v ON v.id = ave.verse_id
            JOIN chapters ch ON ch.id = v.chapter_id
            JOIN cantos ca ON ca.id = ch.canto_id
            JOIN books b ON b.id = ca.book_id
        """
        if book:
            where_clauses.append("UPPER(b.code) = %s")
            params.append(book.upper())
        if canto is not None:
            where_clauses.append("ca.number = %s")
            params.append(canto)
        if chapter is not None:
            where_clauses.append("ch.chapter_number = %s")
            params.append(chapter)

    where_sql = f"WHERE {' AND '.join(where_clauses)}"

    cursor.execute(f"""
        SELECT
            e.id, e.name, e.sanskrit_name, e.entity_type,
            e.description, e.aliases_json, e.mention_count,
            COUNT(DISTINCT ave.verse_id) AS verse_count
        FROM ai_entities e
        LEFT JOIN ai_verse_entities ave ON ave.entity_id = e.id
        {join_clauses}
        {where_sql}
        GROUP BY e.id
        ORDER BY verse_count DESC, e.mention_count DESC
        LIMIT %s OFFSET %s
    """, params + [limit, offset])
    rows = cursor.fetchall()

    # total count (same filters, no limit)
    cursor.execute(f"""
        SELECT COUNT(DISTINCT e.id)
        FROM ai_entities e
        LEFT JOIN ai_verse_entities ave ON ave.entity_id = e.id
        {join_clauses}
        {where_sql}
    """, params)
    total = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    result = []
    for r in rows:
        try:
            aliases = _json.loads(r[5] or "[]")
        except Exception:
            aliases = []
        result.append({
            "id": r[0], "name": r[1], "sanskrit_name": r[2],
            "entity_type": r[3], "description": r[4],
            "aliases": aliases, "mention_count": r[6], "verse_count": r[7],
        })
    return {"items": result, "total": total, "offset": offset, "limit": limit}


@router.get("/entities")
def list_ai_entities(
    type: str | None = None,
    search: str | None = None,
    book: str | None = None,
    canto: int | None = None,
    chapter: int | None = None,
    limit: int = 50,
    offset: int = 0,
):
    conn = get_conn()
    cursor = conn.cursor()

    where_clauses = []
    params = []
    join_clauses = ""

    if type:
        types = [t.strip() for t in type.split(",")]
        placeholders = ",".join(["%s"] * len(types))
        where_clauses.append(f"e.entity_type IN ({placeholders})")
        params.extend(types)

    if search:
        where_clauses.append(
            "(LOWER(e.name) LIKE %s OR LOWER(e.sanskrit_name) LIKE %s OR LOWER(e.aliases_json) LIKE %s)"
        )
        pattern = f"%{search.lower()}%"
        params.extend([pattern, pattern, pattern])

    # Book/canto/chapter filtering
    if book or canto or chapter:
        join_clauses += """
            JOIN verses v ON v.id = ave.verse_id
            JOIN chapters ch ON ch.id = v.chapter_id
            JOIN cantos ca ON ca.id = ch.canto_id
            JOIN books b ON b.id = ca.book_id
        """
        if book:
            where_clauses.append("UPPER(b.code) = %s")
            params.append(book.upper())
        if canto is not None:
            where_clauses.append("ca.number = %s")
            params.append(canto)
        if chapter is not None:
            where_clauses.append("ch.chapter_number = %s")
            params.append(chapter)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    cursor.execute(f"""
        SELECT
            e.id, e.name, e.sanskrit_name, e.entity_type,
            e.description, e.aliases_json, e.mention_count,
            COUNT(DISTINCT ave.verse_id) AS verse_count
        FROM ai_entities e
        LEFT JOIN ai_verse_entities ave ON ave.entity_id = e.id
        {join_clauses}
        {where_sql}
        GROUP BY e.id
        ORDER BY verse_count DESC, e.mention_count DESC
        LIMIT %s OFFSET %s
    """, params + [limit, offset])
    rows = cursor.fetchall()

    # total count (same filters, no limit)
    count_where = where_sql.replace("ave.verse_id", "ave2.verse_id") if join_clauses else where_sql
    cursor.execute(f"""
        SELECT COUNT(DISTINCT e.id)
        FROM ai_entities e
        LEFT JOIN ai_verse_entities ave ON ave.entity_id = e.id
        {join_clauses}
        {where_sql}
    """, params)
    total = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    result = []
    for r in rows:
        try:
            aliases = _json.loads(r[5] or "[]")
        except Exception:
            aliases = []
        result.append({
            "id": r[0], "name": r[1], "sanskrit_name": r[2],
            "entity_type": r[3], "description": r[4],
            "aliases": aliases, "mention_count": r[6], "verse_count": r[7],
        })
    return {"items": result, "total": total, "offset": offset, "limit": limit}

# New endpoint: List all concepts with associated verses and verse titles
@router.get("/concepts")
def list_ai_concepts(limit: int = 100000):
    """List all unique concepts with the verses and verse titles where they appear."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT e.name, e.description, array_agg(v.id) AS verse_ids, array_agg(v.full_reference) AS verse_titles
        FROM ai_verse_concepts vc
        JOIN ai_entities e ON e.id = vc.concept_id
        JOIN verses v ON v.id = vc.verse_id
        WHERE e.entity_type = 'concept'
        GROUP BY e.id, e.name, e.description
        ORDER BY COUNT(*) DESC
        LIMIT %s
        """,
        (limit,)
    )
    rows = cursor.fetchall()
    result = []
    for r in rows:
        result.append({
            "concept": r[0],
            "description": r[1],
            "verse_ids": r[2],
            "verse_titles": r[3],
        })
    cursor.close()
    conn.close()
    return result

@router.get("/entities/{entity_id}")
def get_ai_entity(entity_id: int):
    """Full entity profile: metadata, verses with purport, relationships, concepts."""
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute(
        """SELECT id, name, entity_type, description, aliases_json,
                  mention_count, sanskrit_name
           FROM ai_entities WHERE id=%s""",
        (entity_id,),
    )
    entity = cursor.fetchone()
    if not entity:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Entity not found")

    cursor.execute("""
        SELECT v.id, v.full_reference, v.devanagari, v.transliteration,
               v.translation, v.purport_text, ave.mention_source
        FROM ai_verse_entities ave
        JOIN verses v ON v.id = ave.verse_id
        WHERE ave.entity_id = %s
        ORDER BY v.id
        LIMIT 500
    """, (entity_id,))
    verse_rows = cursor.fetchall()

    cursor.execute("""
        SELECT e.id, e.name, e.sanskrit_name, e.entity_type,
               r.relationship_type, r.context
        FROM ai_relationships r
        JOIN ai_entities e ON e.id = r.target_entity_id
        WHERE r.source_entity_id = %s
        ORDER BY r.relationship_type, e.name
    """, (entity_id,))
    rels_out = cursor.fetchall()

    cursor.execute("""
        SELECT e.id, e.name, e.sanskrit_name, e.entity_type,
               r.relationship_type, r.context
        FROM ai_relationships r
        JOIN ai_entities e ON e.id = r.source_entity_id
        WHERE r.target_entity_id = %s
        ORDER BY r.relationship_type, e.name
    """, (entity_id,))
    rels_in = cursor.fetchall()

    cursor.execute("""
        SELECT e.name, COUNT(*) as freq
        FROM ai_verse_concepts vc
        JOIN ai_entities e ON e.id = vc.concept_id
        WHERE vc.verse_id IN (
            SELECT verse_id FROM ai_verse_entities WHERE entity_id = %s
        )
        AND e.entity_type = 'concept'
        GROUP BY e.id, e.name
        ORDER BY freq DESC
        LIMIT 40
    """, (entity_id,))
    concepts = [{"concept": r[0], "count": r[1]} for r in cursor.fetchall()]

    cursor.close()
    conn.close()

    try:
        aliases = _json.loads(entity[4] or "[]")
    except Exception:
        aliases = []

    def fmt_rel(r, direction: str):
        return {
            "entity_id": r[0], "name": r[1], "sanskrit_name": r[2],
            "entity_type": r[3], "type": r[4], "context": r[5],
            "direction": direction,
        }

    return {
        "id": entity[0],
        "name": entity[1],
        "entity_type": entity[2],
        "description": entity[3],
        "aliases": aliases,
        "mention_count": entity[5],
        "sanskrit_name": entity[6],
        "concepts": concepts,
        "verses": [
            {
                "id": r[0],
                "reference": r[1],
                "devanagari": r[2],
                "transliteration": r[3],
                "translation": r[4],
                "purport_excerpt": (r[5] or "")[:800],
                "mention_source": r[6],
            }
            for r in verse_rows
        ],
        "family_relationships": (
            [fmt_rel(r, "out") for r in rels_out if r[4] in FAMILY_RELS] +
            [fmt_rel(r, "in")  for r in rels_in  if r[4] in FAMILY_RELS]
        ),
        "other_relationships": (
            [fmt_rel(r, "out") for r in rels_out if r[4] not in FAMILY_RELS] +
            [fmt_rel(r, "in")  for r in rels_in  if r[4] not in FAMILY_RELS]
        ),
    }


@router.get("/concepts")
def list_ai_concepts(search: str | None = None, limit: int = 50, offset: int = 0):
    conn = get_conn()
    cursor = conn.cursor()

    search_clause = "AND LOWER(e.name) LIKE %s" if search else ""
    search_params = [f"%{search.lower()}%"] if search else []

    cursor.execute(f"""
        SELECT e.id,
               e.name,
               COUNT(DISTINCT vc.verse_id) AS verse_count,
               e.description
        FROM ai_entities e
        LEFT JOIN ai_verse_concepts vc ON vc.concept_id = e.id
        WHERE e.entity_type = 'concept'
        {search_clause}
        GROUP BY e.id, e.name, e.description
        ORDER BY verse_count DESC
        LIMIT %s OFFSET %s
    """, search_params + [limit, offset])
    rows = cursor.fetchall()

    cursor.execute(f"""
        SELECT COUNT(DISTINCT e.id) FROM ai_entities e
        WHERE e.entity_type = 'concept'
        {search_clause}
    """, search_params)
    total = cursor.fetchone()[0]

    cursor.close()
    conn.close()
    return {
        "items": [
            {
                "entity_id": r[0],
                "concept": r[1],
                "verse_count": r[2],
                "description": r[3],
            }
            for r in rows
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/concepts/{slug}")
def get_ai_concept(slug: str):
    from urllib.parse import unquote
    concept_name = unquote(slug)
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT e.id,
               e.name,
               e.description,
               array_agg(v.id ORDER BY v.id)               AS verse_ids,
               array_agg(v.full_reference ORDER BY v.id)    AS verse_refs,
               array_agg(v.translation ORDER BY v.id)       AS translations
        FROM ai_entities e
        LEFT JOIN ai_verse_concepts vc ON vc.concept_id = e.id
        LEFT JOIN verses v ON v.id = vc.verse_id
        WHERE e.entity_type = 'concept' AND LOWER(e.name) = LOWER(%s)
        GROUP BY e.id, e.name, e.description
    """, (concept_name,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Concept not found")

    return {
        "entity_id": row[0],
        "concept": row[1],
        "description": row[2],
        "verse_ids": row[3],
        "verse_titles": row[4],
        "translations": row[5],
    }


@router.get("/relationships")
def list_ai_relationships(limit: int = 1000):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id,
               s.id, s.name, s.sanskrit_name, s.entity_type,
               t.id, t.name, t.sanskrit_name, t.entity_type,
               r.relationship_type, r.context
        FROM ai_relationships r
        JOIN ai_entities s ON s.id = r.source_entity_id
        JOIN ai_entities t ON t.id = r.target_entity_id
        ORDER BY r.id DESC
        LIMIT %s
    """, (limit,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [
        {
            "id": r[0],
            "source_id": r[1], "source": r[2], "source_sanskrit": r[3], "source_type": r[4],
            "target_id": r[5], "target": r[6], "target_sanskrit": r[7], "target_type": r[8],
            "type": r[9], "context": r[10],
        }
        for r in rows
    ]


@router.get("/graph")
def ai_graph():
    conn = get_conn()
    cursor = conn.cursor()

    # Get all familial relationships first
    cursor.execute("""
        SELECT source_entity_id, target_entity_id, relationship_type
        FROM ai_relationships
        WHERE relationship_type = ANY(%s)
    """, (list(FAMILY_RELS),))
    edges_rows = cursor.fetchall()

    # Collect all entity IDs that appear in familial relationships
    entity_ids = set()
    for r in edges_rows:
        entity_ids.add(r[0])
        entity_ids.add(r[1])

    if not entity_ids:
        return {"nodes": [], "edges": []}

    # Now fetch all those entities (any type: person, deva, sage, demon, etc.)
    placeholders = ",".join(["%s"] * len(entity_ids))
    cursor.execute(f"""
        SELECT e.id, e.name, e.sanskrit_name, e.entity_type,
               COUNT(DISTINCT ave.verse_id) AS verse_count
        FROM ai_entities e
        LEFT JOIN ai_verse_entities ave ON ave.entity_id = e.id
        WHERE e.id IN ({placeholders})
        GROUP BY e.id
        ORDER BY verse_count DESC
    """, list(entity_ids))
    nodes_rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return {
        "nodes": [
            {"id": r[0], "name": r[1], "sanskrit_name": r[2], "type": r[3], "verse_count": r[4]}
            for r in nodes_rows
        ],
        "edges": [
            {"source": r[0], "target": r[1], "type": r[2]}
            for r in edges_rows
        ],
    }


@router.get("/progress")
def ai_progress():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM ai_entities")
    total_entities = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM ai_relationships")
    total_relationships = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT verse_id) FROM ai_verse_entities")
    total_verse_links = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT concept_id) FROM ai_verse_concepts")
    total_concepts = cursor.fetchone()[0]

    cursor.execute("""
        SELECT entity_type, COUNT(*) FROM ai_entities
        GROUP BY entity_type ORDER BY COUNT(*) DESC
    """)
    by_type = cursor.fetchall()

    cursor.execute("""
        SELECT b.code, b.title, COUNT(DISTINCT v.id) AS verses_done
        FROM verses v
        JOIN chapters ch ON ch.id = v.chapter_id
        JOIN cantos ca ON ca.id = ch.canto_id
        JOIN books b ON b.id = ca.book_id
        WHERE v.ai_processed = 1
        GROUP BY b.id, b.code, b.title
        ORDER BY b.id
    """)
    by_book = cursor.fetchall()

    cursor.execute("""
        SELECT b.code, COUNT(*) AS total
        FROM verses v
        JOIN chapters ch ON ch.id = v.chapter_id
        JOIN cantos ca ON ca.id = ch.canto_id
        JOIN books b ON b.id = ca.book_id
        GROUP BY b.id, b.code
    """)
    total_map = {r[0]: r[1] for r in cursor.fetchall()}

    cursor.close()
    conn.close()

    return {
        "total_entities": total_entities,
        "total_relationships": total_relationships,
        "verses_covered": total_verse_links,
        "total_concepts": total_concepts,
        "entities_by_type": [{"type": r[0], "count": r[1]} for r in by_type],
        "by_book": [
            {
                "book": r[0], "title": r[1],
                "verses_done": r[2],
                "verses_total": total_map.get(r[0], 0),
            }
            for r in by_book
        ],
    }

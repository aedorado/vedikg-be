"""API endpoints for AI-extracted entities and relationships."""

from fastapi import APIRouter, HTTPException
from db import get_conn

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/entities")
def list_ai_entities(
    type: str | None = None,
    search: str | None = None,
    limit: int = 500,
):
    """List all AI-extracted entities with verse counts and concepts."""
    conn = get_conn()
    cursor = conn.cursor()
    
    where_clauses = []
    params = []

    if type:
        types = [t.strip() for t in type.split(",")]
        placeholders = ",".join(["%s"] * len(types))
        where_clauses.append(f"e.entity_type IN ({placeholders})")
        params.extend(types)

    if search:
        where_clauses.append("LOWER(e.name) LIKE %s")
        params.append(f"%{search.lower()}%")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    query = f"""
        SELECT
            e.id,
            e.name,
            e.sanskrit_name,
            e.entity_type,
            e.description,
            e.aliases_json,
            e.mention_count,
            COUNT(DISTINCT ave.verse_id) AS verse_count
        FROM ai_entities e
        LEFT JOIN ai_verse_entities ave ON ave.entity_id = e.id
        {where_sql}
        GROUP BY e.id
        ORDER BY verse_count DESC, e.mention_count DESC
        LIMIT %s
    """
    
    params.append(limit)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "name": r[1],
            "sanskrit_name": r[2],
            "entity_type": r[3],
            "description": r[4],
            "aliases": r[5],
            "mention_count": r[6],
            "verse_count": r[7],
            "concepts": [],
        })
    
    cursor.close()
    conn.close()
    return result


@router.get("/entities/{entity_id}")
def get_ai_entity(entity_id: int):
    """Get a single AI entity with its verse mentions and relationships."""
    conn = get_conn()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, name, entity_type, description, aliases_json, mention_count, sanskrit_name FROM ai_entities WHERE id=%s",
        (entity_id,)
    )
    entity = cursor.fetchone()
    
    if not entity:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Entity not found")

    cursor.execute("""
        SELECT v.full_reference, v.devanagari, v.transliteration, v.translation, ave.mention_source
        FROM ai_verse_entities ave
        JOIN verses v ON v.id = ave.verse_id
        WHERE ave.entity_id = %s
        ORDER BY v.id
        LIMIT 100
    """, (entity_id,))
    verses = cursor.fetchall()

    cursor.execute("""
        SELECT e.sanskrit_name, r.relationship_type, r.context
        FROM ai_relationships r
        JOIN ai_entities e ON e.id = r.target_entity_id
        WHERE r.source_entity_id = %s
    """, (entity_id,))
    rels_out = cursor.fetchall()

    cursor.execute("""
        SELECT e.sanskrit_name, r.relationship_type, r.context
        FROM ai_relationships r
        JOIN ai_entities e ON e.id = r.source_entity_id
        WHERE r.target_entity_id = %s
    """, (entity_id,))
    rels_in = cursor.fetchall()

    # Fetch concepts associated with this entity's verses
    cursor.execute("""
        SELECT DISTINCT concept FROM ai_verse_concepts 
        WHERE verse_id IN (SELECT verse_id FROM ai_verse_entities WHERE entity_id = %s)
        LIMIT 20
    """, (entity_id,))
    concepts = [row[0] for row in cursor.fetchall()]

    cursor.close()
    conn.close()

    return {
        "id": entity[0],
        "name": entity[1],
        "sanskrit_name": entity[6],
        "type": entity[2],
        "description": entity[3],
        "aliases": entity[4],
        "mention_count": entity[5],
        "concepts": concepts,
        "verses": [{"reference": r[0], "devanagari": r[1], "transliteration": r[2], "translation": r[3], "mention_source": r[4]} for r in verses],
        "relationships_out": [{"target": r[0], "type": r[1], "context": r[2]} for r in rels_out],
        "relationships_in": [{"source": r[0], "type": r[1], "context": r[2]} for r in rels_in],
    }


@router.get("/relationships")
def list_ai_relationships(limit: int = 1000):
    """List all AI-extracted relationships."""
    conn = get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT
            r.id,
            s.name AS source,
            t.name AS target,
            r.relationship_type,
            r.context,
            s.entity_type AS source_type,
            t.entity_type AS target_type
        FROM ai_relationships r
        JOIN ai_entities s ON s.id = r.source_entity_id
        JOIN ai_entities t ON t.id = r.target_entity_id
        ORDER BY r.id DESC
        LIMIT %s
    """, (limit,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # Normalize relationships that are stored backward
    inversions = {
        "expansion_of": "expands_as",
        "killed_by": "kills",
    }
    
    result = []
    for r in rows:
        source, target, rel_type = r[1], r[2], r[3]
        
        # If relationship type should be inverted, swap source/target
        if rel_type in inversions:
            result.append({
                "id": r[0],
                "source": target,
                "target": source,
                "type": inversions[rel_type],
                "context": r[4],
                "source_type": r[6],
                "target_type": r[5],
            })
        else:
            result.append({
                "id": r[0],
                "source": source,
                "target": target,
                "type": rel_type,
                "context": r[4],
                "source_type": r[5],
                "target_type": r[6],
            })

    return result


@router.get("/graph")
def ai_graph():
    """Return nodes + edges for a force graph (familial relationships only)."""
    # Familial relationship types to include
    FAMILIAL_RELS = {
        "son_of", "daughter_of", "father_of", "mother_of",
        "brother_of", "sister_of", "spouse_of", "cousin_of",
        "uncle_of", "aunt_of", "nephew_of", "niece_of",
        "grandfather_of", "grandmother_of", "grandson_of", "granddaughter_of",
        "parent_of", "child_of", "sibling_of"
    }
    
    conn = get_conn()
    cursor = conn.cursor()
    
    # Get top entities by verse count
    cursor.execute("""
        SELECT e.id, e.name, e.entity_type,
               COUNT(DISTINCT ave.verse_id) AS verse_count
        FROM ai_entities e
        LEFT JOIN ai_verse_entities ave ON ave.entity_id = e.id
        GROUP BY e.id
        ORDER BY verse_count DESC
        LIMIT 300
    """)
    nodes_rows = cursor.fetchall()

    node_ids = {r[0] for r in nodes_rows}

    # Get only familial relationships between top entities
    cursor.execute("""
        SELECT source_entity_id, target_entity_id, relationship_type
        FROM ai_relationships
        WHERE LOWER(relationship_type) IN ({})
    """.format(",".join(["%s"] * len(FAMILIAL_RELS))), list(FAMILIAL_RELS))
    edges_rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return {
        "nodes": [{"id": r[0], "name": r[1], "type": r[2], "verse_count": r[3]} for r in nodes_rows],
        "edges": [
            {"source": r[0], "target": r[1], "type": r[2]}
            for r in edges_rows
            if r[0] in node_ids and r[1] in node_ids
        ],
    }


@router.get("/progress")
def ai_progress():
    """Extraction progress: how many verses processed per book/canto."""
    conn = get_conn()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM ai_entities")
    total_entities = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM ai_relationships")
    total_relationships = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT verse_id) FROM ai_verse_entities")
    total_verse_links = cursor.fetchone()[0]

    cursor.execute("""
        SELECT entity_type, COUNT(*) FROM ai_entities GROUP BY entity_type ORDER BY COUNT(*) DESC
    """)
    by_type = cursor.fetchall()

    cursor.execute("""
        SELECT b.code, b.title, COUNT(DISTINCT ave.verse_id) AS verses_done
        FROM ai_verse_entities ave
        JOIN verses v ON v.id = ave.verse_id
        JOIN chapters ch ON ch.id = v.chapter_id
        JOIN cantos ca ON ca.id = ch.canto_id
        JOIN books b ON b.id = ca.book_id
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
    total_verses_by_book = cursor.fetchall()
    total_map = {r[0]: r[1] for r in total_verses_by_book}

    cursor.close()
    conn.close()

    return {
        "total_entities": total_entities,
        "total_relationships": total_relationships,
        "verses_covered": total_verse_links,
        "entities_by_type": [{"type": r[0], "count": r[1]} for r in by_type],
        "by_book": [
            {
                "book": r[0],
                "title": r[1],
                "verses_done": r[2],
                "verses_total": total_map.get(r[0], 0),
            }
            for r in by_book
        ],
    }

"""
Pipeline to extract entities and relationships from Bhagavatam verses using Gemini.

Usage:
    python extract_entities.py --book SB --canto 1 --dry-run
    python extract_entities.py --book SB --canto 1
    python extract_entities.py --book CB
    python extract_entities.py --all
    python extract_entities.py --all --reprocess   # clear and re-extract everything

Rate: 1 verse per call, key pool respects 15 RPM / 500 RPD per key.
"""

import argparse
import json
import logging
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import psycopg
from app.services.gemini_extractor import extract_with_retry, normalize_entity_name, CANONICAL_NAMES, get_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("POSTGRES_URL")
if not DATABASE_URL:
    raise ValueError("POSTGRES_URL environment variable not set")


def get_conn():
    conn = psycopg.connect(
        DATABASE_URL,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
        connect_timeout=15,
    )
    conn.prepare_threshold = None  # disable auto-prepare to avoid DuplicatePreparedStatement
    return conn


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------

def strip_possessive(name: str) -> str:
    return re.sub(r"['']s?\s*$", "", name.strip()).strip()


def ascii_fold(name: str) -> str:
    """Remove diacritics → plain ASCII."""
    nfd = unicodedata.normalize("NFD", name)
    return nfd.encode("ascii", "ignore").decode("ascii").strip()


def canonical_normalized(name: str) -> str:
    """Full normalization pipeline: possessive → ascii → lowercase → canonical map."""
    name = strip_possessive(name)
    name = ascii_fold(name)
    lower = name.lower()
    return CANONICAL_NAMES.get(lower, lower)


# ---------------------------------------------------------------------------
# DB helpers — all accept an open connection/cursor to avoid per-op overhead
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# In-process entity cache — avoids repeated full-table fuzzy scans
# ---------------------------------------------------------------------------

# {entity_type -> [(id, normalized_name)]}
_ENTITY_CACHE: dict[str, list[tuple[int, str]]] = {}
# {normalized_name -> id}
_NORM_TO_ID: dict[str, int] = {}
_CACHE_LOADED = False


def _load_entity_cache(cursor) -> None:
    """Load all existing entities into memory once per run."""
    global _CACHE_LOADED
    if _CACHE_LOADED:
        return
    cursor.execute("SELECT id, normalized_name, entity_type FROM ai_entities")
    for eid, norm, etype in cursor.fetchall():
        _NORM_TO_ID[norm] = eid
        _ENTITY_CACHE.setdefault(etype, []).append((eid, norm))
    _CACHE_LOADED = True


def _cache_add(entity_id: int, normalized: str, entity_type: str) -> None:
    _NORM_TO_ID[normalized] = entity_id
    _ENTITY_CACHE.setdefault(entity_type, []).append((entity_id, normalized))


def db_get_or_create_entity(cursor, name: str, entity_type: str,
                             description: str, aliases: list,
                             sanskrit_name: str | None,
                             verse_id: int | None) -> int:
    """Upsert entity. Returns entity_id. Uses normalized name + fuzzy dedup.
    Reads from in-process cache; only writes to DB (no full-table scans)."""
    import difflib

    normalized = canonical_normalized(name)

    # 1. Exact match from cache
    if normalized in _NORM_TO_ID:
        entity_id = _NORM_TO_ID[normalized]
        cursor.execute("""
            UPDATE ai_entities SET
                mention_count = mention_count + 1,
                description = %s
            WHERE id = %s
        """, (description or "", entity_id))
        _merge_alias(cursor, entity_id, name)
        return entity_id

    # 2. Fuzzy match within same type — purely in-process, no DB read
    candidates = _ENTITY_CACHE.get(entity_type, [])
    best_id, best_ratio = None, 0.82
    for cand_id, cand_norm in candidates:
        ratio = difflib.SequenceMatcher(None, normalized, cand_norm).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_id = cand_id

    if best_id:
        cursor.execute("""
            UPDATE ai_entities SET
                mention_count = mention_count + 1,
                description = %s
            WHERE id = %s
        """, (description or "", best_id))
        _merge_alias(cursor, best_id, name)
        return best_id

    # 3. Create new entity
    all_aliases = list({a for a in aliases if a and strip_possessive(a) != name})
    if sanskrit_name and ascii_fold(sanskrit_name) != name:
        all_aliases.append(sanskrit_name)

    try:
        cursor.execute("""
            INSERT INTO ai_entities
                (name, normalized_name, entity_type, description,
                 aliases_json, sanskrit_name, first_seen_verse_id, mention_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            RETURNING id
        """, (name, normalized, entity_type, description or "",
              json.dumps(all_aliases), sanskrit_name or "", verse_id))
        entity_id = cursor.fetchone()[0]
        _cache_add(entity_id, normalized, entity_type)
        return entity_id
    except Exception as e:
        if "unique" in str(e).lower() and "normalized_name" in str(e).lower():
            # Entity already exists in DB but not in cache — recover by updating
            logger.warning(f"Entity '{name}' already in DB (cache miss) — updating instead")
            # Rollback failed transaction before executing recovery query
            cursor.connection.rollback()
            cursor.execute("""
                SELECT id FROM ai_entities WHERE normalized_name = %s
            """, (normalized,))
            row = cursor.fetchone()
            if row:
                entity_id = row[0]
                cursor.execute("""
                    UPDATE ai_entities SET
                        mention_count = mention_count + 1,
                        description = %s
                    WHERE id = %s
                """, (description or "", entity_id))
                _cache_add(entity_id, normalized, entity_type)
                _merge_alias(cursor, entity_id, name)
                return entity_id
        raise


def _merge_alias(cursor, entity_id: int, new_alias: str):
    """Add alias to entity if not already present."""
    clean = strip_possessive(new_alias)
    cursor.execute("SELECT normalized_name, aliases_json FROM ai_entities WHERE id = %s", (entity_id,))
    row = cursor.fetchone()
    if not row:
        return
    canon_norm, aliases_raw = row
    try:
        aliases = json.loads(aliases_raw or "[]")
    except (json.JSONDecodeError, TypeError):
        aliases = []
    # Don't add if alias matches normalized canonical name or already present
    clean_norm = canonical_normalized(clean)
    if clean_norm != canon_norm and clean not in aliases:
        aliases.append(clean)
        cursor.execute("UPDATE ai_entities SET aliases_json = %s WHERE id = %s",
                       (json.dumps(aliases), entity_id))


def db_get_or_create_relationship(cursor, src_id: int, tgt_id: int,
                                   rel_type: str, context: str,
                                   verse_id: int | None) -> bool:
    """Create relationship if not exists. Returns True if created."""
    cursor.execute("""
        SELECT id FROM ai_relationships
        WHERE source_entity_id=%s AND target_entity_id=%s AND relationship_type=%s
    """, (src_id, tgt_id, rel_type))
    if cursor.fetchone():
        return False
    cursor.execute("""
        INSERT INTO ai_relationships
            (source_entity_id, target_entity_id, relationship_type, context, source_verse_id)
        VALUES (%s, %s, %s, %s, %s)
    """, (src_id, tgt_id, rel_type, context or "", verse_id))
    return True


def db_link_verse_entity(cursor, verse_id: int, entity_id: int, mention_source: str = "verse"):
    """Link verse to entity. ON CONFLICT: merge mention_source values to 'both' if different."""
    try:
        cursor.execute("""
            INSERT INTO ai_verse_entities (verse_id, entity_id, mention_source)
            VALUES (%s, %s, %s)
            ON CONFLICT (verse_id, entity_id) DO UPDATE SET 
                mention_source = CASE
                    WHEN EXCLUDED.mention_source = 'both' THEN 'both'
                    WHEN EXCLUDED.mention_source = ai_verse_entities.mention_source THEN EXCLUDED.mention_source
                    ELSE 'both'
                END
        """, (verse_id, entity_id, mention_source))
    except Exception:
        pass  # silently skip if constraint not set up for ON CONFLICT


def db_save_verse_concepts(cursor, verse_id: int, concepts: list) -> int:
    """Save concepts as entities (type='concept') and link to verse.
    Expects concepts in new format: [{"name": "bhakti", "description": "..."}, ...]
    Also handles legacy format: ["bhakti", "maya", ...] for backwards compat.
    """
    count = 0
    for concept_item in concepts:
        # Handle both dict format (new) and string format (legacy)
        if isinstance(concept_item, dict):
            concept_name = concept_item.get("name", "").strip().lower()
            concept_desc = concept_item.get("description", "").strip()
        else:
            concept_name = str(concept_item).strip().lower() if concept_item else ""
            concept_desc = ""

        if not concept_name:
            continue

        try:
            # Create/upsert concept as entity with type='concept'
            concept_id = db_get_or_create_entity(
                cursor, concept_name, "concept",
                description=concept_desc,
                aliases=[],
                sanskrit_name=None,
                verse_id=verse_id
            )

            # Link concept entity to verse
            cursor.execute("""
                INSERT INTO ai_verse_concepts (verse_id, concept_id)
                VALUES (%s, %s)
                ON CONFLICT (verse_id, concept_id) DO NOTHING
            """, (verse_id, concept_id))
            count += 1
        except Exception as e:
            logger.warning(f"Failed to save concept '{concept_name}': {e}")

    return count


# ---------------------------------------------------------------------------
# Save results — with reconnect retry on dropped connections
# ---------------------------------------------------------------------------

def _do_save(verses: list, result: dict) -> dict:
    """Inner save logic. Uses a single connection; caller handles reconnect."""
    import time as _time

    stats = {"entities_created": 0, "entities_reused": 0,
             "relationships_created": 0, "mentions_created": 0, "concepts_created": 0}

    verse_map = {v["full_reference"]: v for v in verses}
    entity_name_to_id: dict[str, int] = {}

    conn = get_conn()
    cursor = conn.cursor()

    try:
        # Load entity cache once (no-op after first call)
        _load_entity_cache(cursor)

        # 1. Upsert entities
        for ent_data in result.get("entities", []):
            name = ent_data.get("name", "").strip()
            name = strip_possessive(name)
            if not name:
                continue

            etype = ent_data.get("type", "person")
            desc = ent_data.get("description", "")
            aliases = [strip_possessive(a) for a in ent_data.get("aliases", []) if a]
            sanskrit = ent_data.get("sanskrit_name", "")

            # Find first verse mentioning this entity
            first_verse_id = None
            for vs in result.get("verse_summaries", []):
                for m in vs.get("entities_mentioned", []):
                    mname = m.get("name", "") if isinstance(m, dict) else m
                    if mname == name:
                        ref_verse = verse_map.get(vs["reference"])
                        if ref_verse:
                            first_verse_id = ref_verse["id"]
                        break
                if first_verse_id:
                    break

            norm = canonical_normalized(name)
            was_new = norm not in _NORM_TO_ID

            entity_id = db_get_or_create_entity(
                cursor, name, etype, desc, aliases, sanskrit, first_verse_id
            )

            if desc:
                desc_preview = desc[:80] if len(desc) > 80 else desc
                logger.info(f"     → saved to DB: desc='{desc_preview}...'")

            entity_name_to_id[name] = entity_id
            entity_name_to_id[name.lower()] = entity_id
            entity_name_to_id[norm] = entity_id

            if was_new:
                stats["entities_created"] += 1
            else:
                stats["entities_reused"] += 1

        # 2. Upsert relationships
        for rel_data in result.get("relationships", []):
            src_name = rel_data.get("source", "").strip()
            tgt_name = rel_data.get("target", "").strip()
            rel_type = rel_data.get("type", "interacted_with")
            context = rel_data.get("context", "")

            src_id = entity_name_to_id.get(src_name) or entity_name_to_id.get(src_name.lower())
            tgt_id = entity_name_to_id.get(tgt_name) or entity_name_to_id.get(tgt_name.lower())

            if not src_id:
                src_id = _NORM_TO_ID.get(canonical_normalized(src_name))
            if not tgt_id:
                tgt_id = _NORM_TO_ID.get(canonical_normalized(tgt_name))

            if not src_id or not tgt_id or src_id == tgt_id:
                continue

            verse_id = verses[0]["id"] if verses else None
            created = db_get_or_create_relationship(cursor, src_id, tgt_id, rel_type, context, verse_id)
            if created:
                stats["relationships_created"] += 1

        # 3. Link entities with their mention source (verse/purport/both)
        # Source is now directly on each entity dict from Stage 1
        verse = verses[0] if verses else None
        if verse:
            for entity_data in result.get("entities", []):
                ename = entity_data.get("name", "").strip()
                if not ename:
                    continue

                entity_id = (entity_name_to_id.get(ename)
                             or entity_name_to_id.get(ename.lower())
                             or entity_name_to_id.get(canonical_normalized(ename)))
                if not entity_id:
                    entity_id = _NORM_TO_ID.get(canonical_normalized(ename))

                if entity_id:
                    mention_source = entity_data.get("source", "verse")
                    if mention_source not in ("verse", "purport", "both"):
                        logger.warning(f"  ⚠️  Invalid source '{mention_source}' for '{ename}', defaulting to 'verse'")
                        mention_source = "verse"
                    db_link_verse_entity(cursor, verse["id"], entity_id, mention_source)
                    stats["mentions_created"] += 1

        # 4. Save concepts (flat list from Stage 3 result)
        verse = verses[0] if verses else None
        if verse:
            concepts = result.get("concepts", [])
            if concepts:
                stats["concepts_created"] += db_save_verse_concepts(cursor, verse["id"], concepts)

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    return stats


def save_extraction_results(verses: list, result: dict) -> dict:
    """Save with up to 3 reconnect attempts on dropped connections."""
    import time as _time

    for attempt in range(3):
        try:
            return _do_save(verses, result)
        except (psycopg.OperationalError, psycopg.InterfaceError) as e:
            if attempt == 2:
                logger.error(f"DB connection lost after 3 attempts: {e}")
                raise
            wait = 3 * (attempt + 1)
            logger.warning(f"DB connection lost, reconnecting in {wait}s (attempt {attempt + 1}/3): {e}")
            # Force cache reload on next save — new connection won't have old state
            global _CACHE_LOADED
            _CACHE_LOADED = False
            _NORM_TO_ID.clear()
            _ENTITY_CACHE.clear()
            _time.sleep(wait)


# ---------------------------------------------------------------------------
# Chapter and verse fetching
# ---------------------------------------------------------------------------

def get_chapters_with_unprocessed(book_code: str | None = None,
                                  canto_num: int | None = None,
                                  reprocess: bool = False) -> list:
    """Get list of (canto_num, chapter_num) tuples with unprocessed verses."""
    conn = get_conn()
    cursor = conn.cursor()

    conditions = []
    params = []

    if not reprocess:
        conditions.append("v.ai_processed = 0")

    if book_code:
        conditions.append("bk.code = %s")
        params.append(book_code.upper())

    if canto_num is not None:
        conditions.append("ca.number = %s")
        params.append(canto_num)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    query = f"""
        SELECT DISTINCT ca.number, ch.chapter_number
        FROM verses v
        JOIN chapters ch ON ch.id = v.chapter_id
        JOIN cantos ca   ON ca.id = ch.canto_id
        JOIN books bk    ON bk.id = v.book_id
        {where_clause}
        ORDER BY ca.number, ch.chapter_number
    """

    cursor.execute(query, params)
    chapters = [(row[0], row[1]) for row in cursor.fetchall()]
    cursor.close()
    conn.close()

    return chapters


def get_verses_to_process(book_code: str | None = None,
                           canto_num: int | None = None,
                           chapter_num: int | None = None,
                           reprocess: bool = False) -> list:
    conn = get_conn()
    cursor = conn.cursor()

    conditions = []
    params = []

    if not reprocess:
        conditions.append("v.ai_processed = 0")

    if book_code:
        conditions.append("bk.code = %s")
        params.append(book_code.upper())

    if canto_num is not None:
        conditions.append("ca.number = %s")
        params.append(canto_num)

    if chapter_num is not None:
        conditions.append("ch.chapter_number = %s")
        params.append(chapter_num)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    query = f"""
        SELECT v.id, v.full_reference, v.translation, v.purport_text
        FROM verses v
        JOIN chapters ch ON ch.id = v.chapter_id
        JOIN cantos ca   ON ca.id = ch.canto_id
        JOIN books bk    ON bk.id = v.book_id
        {where_clause}
        ORDER BY v.id
        LIMIT 500
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [{"id": r[0], "full_reference": r[1],
             "translation": r[2] or "", "purport_text": r[3] or ""} for r in rows]


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_verses(verses: list, dry_run: bool = False, reprocess: bool = False):
    total = len(verses)
    logger.info(f"Processing {total} verses one at a time (dry_run={dry_run}, reprocess={reprocess})")

    total_stats = {"entities_created": 0, "entities_reused": 0,
                   "relationships_created": 0, "mentions_created": 0, "concepts_created": 0}

    for i, verse in enumerate(verses):
        ref = verse["full_reference"]
        logger.info(f"\n{'='*70}")
        logger.info(f"[{i+1}/{total}] Processing: {ref}")
        logger.info(f"{'='*70}")

        result = extract_with_retry([verse])

        entities = result.get("entities", [])
        relationships = result.get("relationships", [])
        concepts = result.get("concepts", [])

        logger.info(f"\n📊 EXTRACTION RESULT:")
        logger.info(f"   ✓ {len(entities)} entities, {len(relationships)} rels, {len(concepts)} concepts")

        if entities:
            logger.info(f"\n📝 ENTITIES EXTRACTED:")
            for e in entities:
                src = e.get("source", "?")
                typ = e.get("type", "?")
                logger.info(f"   • [{typ:8s}] {e.get('name'):25s} (source={src:7s}) → {e.get('description','')}")

        if relationships:
            logger.info(f"\n🔗 RELATIONSHIPS EXTRACTED:")
            for r in relationships:
                logger.info(f"   • {r.get('source')} --[{r.get('type')}]--> {r.get('target')}")

        if concepts:
            logger.info(f"\n💡 CONCEPTS EXTRACTED: {concepts}")

        logger.info(f"\n📈 API QUOTA STATUS:")
        try:
            pool = get_pool()
            pool.log_quota_status()
        except Exception as e:
            logger.warning(f"Could not log quota status: {e}")

        if dry_run:
            logger.info("  [dry-run] skipping DB write")
            continue

        if reprocess:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM ai_verse_entities WHERE verse_id = %s", (verse["id"],))
            cur.execute("DELETE FROM ai_verse_concepts WHERE verse_id = %s", (verse["id"],))
            conn.commit()
            cur.close()
            conn.close()

        stats = save_extraction_results([verse], result)
        for k in total_stats:
            total_stats[k] += stats[k]

        # Mark as processed
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE verses SET ai_processed = 1 WHERE id = %s", (verse["id"],))
        conn.commit()
        cur.close()
        conn.close()

    logger.info(f"\n✓ Done! Processed {total} verses")

    # Log final quota status
    try:
        pool = get_pool()
        pool.log_quota_status()
    except Exception as e:
        logger.warning(f"Could not log final quota status: {e}")

    if not dry_run:
        logger.info(
            f"  Entities created: {total_stats['entities_created']}  "
            f"reused: {total_stats['entities_reused']}\n"
            f"  Relationships created: {total_stats['relationships_created']}\n"
            f"  Verse-entity mentions: {total_stats['mentions_created']}\n"
            f"  Concepts extracted: {total_stats['concepts_created']}"
        )
    return total_stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Extract entities from Bhagavatam verses using Gemini")
    parser.add_argument("--book",      help="Book code: SB, CC, CB, BRS")
    parser.add_argument("--canto",     type=int, help="Canto/section number")
    parser.add_argument("--chapter",   type=int, help="Chapter number")
    parser.add_argument("--all",       action="store_true", help="Process all unprocessed verses")
    parser.add_argument("--dry-run",   action="store_true", help="Print extraction without saving")
    parser.add_argument("--reprocess", action="store_true",
                        help="Re-extract even already-processed verses (clears verse-level data first)")
    parser.add_argument("--limit",     type=int, default=None, help="Max chapters to process")
    args = parser.parse_args()

    if not args.book and not args.all:
        parser.error("Specify --book SB|CC|CB|BRS or --all")

    # Get all chapters with unprocessed verses, then process one chapter at a time
    chapters = get_chapters_with_unprocessed(
        book_code=args.book,
        canto_num=args.canto,
        reprocess=args.reprocess,
    )

    # If a specific chapter is requested, filter to just that one
    if args.chapter is not None:
        chapters = [(c, n) for c, n in chapters if n == args.chapter]

    if not chapters:
        logger.info("No verses found matching criteria.")
        return

    logger.info(f"Found {len(chapters)} chapters with unprocessed verses")

    chapters_processed = 0
    for canto_num, chapter_num in chapters:
        if args.limit and chapters_processed >= args.limit:
            logger.info(f"Reached chapter limit ({args.limit})")
            break

        logger.info(f"Processing canto {canto_num}, chapter {chapter_num}...")
        verses = get_verses_to_process(
            book_code=args.book,
            canto_num=canto_num,
            chapter_num=chapter_num,
            reprocess=args.reprocess,
        )
        logger.info(f"Found {len(verses)} to process")

        if verses:
            process_verses(verses, dry_run=args.dry_run, reprocess=args.reprocess)
            chapters_processed += 1


if __name__ == "__main__":
    main()

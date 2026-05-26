"""
Pipeline to extract entities and relationships from Bhagavatam verses using Gemini.

Usage:
    # Dry-run: just print what would be extracted (no DB writes)
    python extract_entities.py --book SB --canto 1 --dry-run

    # Process SB Canto 1
    python extract_entities.py --book SB --canto 1

    # Process all CB verses
    python extract_entities.py --book CB

    # Process everything
    python extract_entities.py --all

Rate: 1 RPM → batch of 10 verses, sleep 60s between batches
"""

import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import psycopg
from app.services.gemini_extractor import extract_with_retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# PostgreSQL connection
DATABASE_URL = os.getenv("POSTGRES_URL")
if not DATABASE_URL:
    raise ValueError("POSTGRES_URL environment variable not set")


def get_conn():
    """Get PostgreSQL connection."""
    return psycopg.connect(DATABASE_URL)


BATCH_SIZE = 4
RPM_LIMIT  = 1       # requests per minute
SLEEP_SECS = 60      # 60 seconds between calls


# ---------------------------------------------------------------------------
# Raw SQL helpers for AI-specific tables
# ---------------------------------------------------------------------------

def ai_get_or_create_entity(name: str, entity_type: str,
                              description: str, aliases: list,
                              sanskrit_name: str | None,
                              verse_id: int | None) -> int:
    """Upsert into ai_entities, return its id."""
    conn = get_conn()
    cursor = conn.cursor()
    
    normalized = name.strip().lower()
    cursor.execute(
        "SELECT id FROM ai_entities WHERE normalized_name = %s",
        (normalized,)
    )
    row = cursor.fetchone()
    
    if row:
        # Merge description if empty
        cursor.execute("""
            UPDATE ai_entities SET
                mention_count = mention_count + 1,
                description = CASE WHEN description IS NULL OR description = '' THEN %s ELSE description END
            WHERE normalized_name = %s
        """, (description or "", normalized))
        conn.commit()
        entity_id = row[0]
    else:
        all_aliases = list(set(a for a in aliases if a and a != name))
        if sanskrit_name and sanskrit_name != name:
            all_aliases.append(sanskrit_name)

        cursor.execute("""
            INSERT INTO ai_entities (name, normalized_name, entity_type, description,
                                     aliases_json, sanskrit_name, first_seen_verse_id, mention_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
        """, (name, normalized, entity_type, description or "", json.dumps(all_aliases),
              sanskrit_name or "", verse_id))
        conn.commit()
        
        cursor.execute(
            "SELECT id FROM ai_entities WHERE normalized_name = %s",
            (normalized,)
        )
        entity_id = cursor.fetchone()[0]
    
    cursor.close()
    conn.close()
    return entity_id


def ai_get_or_create_relationship(src_id: int, tgt_id: int,
                                   rel_type: str, context: str,
                                   verse_id: int | None) -> None:
    """Create relationship if it doesn't exist."""
    conn = get_conn()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id FROM ai_relationships
        WHERE source_entity_id=%s AND target_entity_id=%s AND relationship_type=%s
    """, (src_id, tgt_id, rel_type))
    
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO ai_relationships
                (source_entity_id, target_entity_id, relationship_type, context, source_verse_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (src_id, tgt_id, rel_type, context or "", verse_id))
        conn.commit()
    
    cursor.close()
    conn.close()


def ai_link_verse_entity(verse_id: int, entity_id: int, mention_source: str = 'verse') -> None:
    """Link verse to entity with mention source tracking (unique constraint prevents duplicates)."""
    conn = get_conn()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO ai_verse_entities (verse_id, entity_id, mention_source)
            VALUES (%s, %s, %s)
        """, (verse_id, entity_id, mention_source))
        conn.commit()
    except psycopg.IntegrityError:
        # Already linked - update mention source if different
        conn.rollback()
        cursor.execute("""
            UPDATE ai_verse_entities 
            SET mention_source = %s 
            WHERE verse_id = %s AND entity_id = %s
        """, (mention_source, verse_id, entity_id))
        conn.commit()
    
    cursor.close()
    conn.close()


def save_extraction_results(verses: list, result: dict) -> dict:
    """Persist extracted entities/relationships into the AI-specific tables."""
    stats = {"entities_created": 0, "entities_reused": 0,
             "relationships_created": 0, "mentions_created": 0}

    verse_map = {v["full_reference"]: v for v in verses}
    entity_name_to_id: dict[str, int] = {}

    # 1. Upsert AI entities
    for ent_data in result.get("entities", []):
        name = ent_data.get("name", "").strip()
        if not name:
            continue
        etype      = ent_data.get("type", "person")
        desc       = ent_data.get("description", "")
        aliases    = ent_data.get("aliases", [])
        sanskrit   = ent_data.get("sanskrit_name", "")

        # Find first verse mentioning this entity
        first_verse_id = None
        for vs in result.get("verse_summaries", []):
            if name in vs.get("entities_mentioned", []):
                ref_verse = verse_map.get(vs["reference"])
                if ref_verse:
                    first_verse_id = ref_verse["id"]
                    break

        normalized = name.strip().lower()
        
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM ai_entities WHERE normalized_name = %s",
            (normalized,)
        )
        was_new = cursor.fetchone() is None
        cursor.close()
        conn.close()

        entity_id = ai_get_or_create_entity(
            name, etype, desc, aliases, sanskrit, first_verse_id
        )
        entity_name_to_id[normalized] = entity_id

        if was_new:
            stats["entities_created"] += 1
        else:
            stats["entities_reused"] += 1

    # 2. Upsert AI relationships
    for rel_data in result.get("relationships", []):
        src_name = rel_data.get("source", "").strip().lower()
        tgt_name = rel_data.get("target", "").strip().lower()
        rel_type = rel_data.get("type", "interacted_with")
        context  = rel_data.get("context", "")

        src_id = entity_name_to_id.get(src_name)
        if not src_id:
            conn = get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM ai_entities WHERE normalized_name=%s",
                (src_name,)
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            src_id = row[0] if row else None
        
        tgt_id = entity_name_to_id.get(tgt_name)
        if not tgt_id:
            conn = get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM ai_entities WHERE normalized_name=%s",
                (tgt_name,)
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            tgt_id = row[0] if row else None

        if not src_id or not tgt_id:
            continue

        verse_id = verses[0]["id"] if verses else None
        
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM ai_relationships
            WHERE source_entity_id=%s AND target_entity_id=%s AND relationship_type=%s
        """, (src_id, tgt_id, rel_type))
        
        if not cursor.fetchone():
            ai_get_or_create_relationship(src_id, tgt_id, rel_type, context, verse_id)
            stats["relationships_created"] += 1
        
        cursor.close()
        conn.close()

    # 3. Link verses to AI entities
    for vs_summary in result.get("verse_summaries", []):
        verse = verse_map.get(vs_summary.get("reference", ""))
        if not verse:
            continue
        for mention in vs_summary.get("entities_mentioned", []):
            # Handle both old format (string) and new format (dict with name and source)
            if isinstance(mention, dict):
                ename = mention.get("name", "")
                mention_source = mention.get("source", "verse")
            else:
                ename = mention
                mention_source = "verse"
            
            if not ename:
                continue
                
            entity_id = entity_name_to_id.get(ename.lower())
            if not entity_id:
                conn = get_conn()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM ai_entities WHERE normalized_name=%s",
                    (ename.lower(),)
                )
                row = cursor.fetchone()
                cursor.close()
                conn.close()
                entity_id = row[0] if row else None
            
            if not entity_id:
                continue
            
            ai_link_verse_entity(verse["id"], entity_id, mention_source)
            stats["mentions_created"] += 1

    return stats


# ---------------------------------------------------------------------------
# Main processing logic
# ---------------------------------------------------------------------------

def get_verses_to_process(book_code: str | None = None,
                           canto_num: int | None = None,
                           chapter_num: int | None = None) -> list:
    """Fetch unprocessed verses matching the given filters."""
    conn = get_conn()
    cursor = conn.cursor()
    
    query = "SELECT id, full_reference, translation, purport_text FROM verses WHERE ai_processed = 0"
    params = []
    
    if book_code:
        query += " AND book_id = (SELECT id FROM books WHERE code = %s)"
        params.append(book_code.upper())
    
    if canto_num is not None:
        query += """
            AND chapter_id IN (
                SELECT id FROM chapters
                WHERE canto_id IN (
                    SELECT id FROM cantos
                    WHERE number = %s
        """
        params.append(canto_num)
        if book_code:
            query += " AND book_id = (SELECT id FROM books WHERE code = %s)"
            params.append(book_code.upper())
        query += "))"
        
        if chapter_num is not None:
            query += " AND chapter_id IN (SELECT id FROM chapters WHERE chapter_number = %s)"
            params.append(chapter_num)
    
    query += " ORDER BY id LIMIT 10000"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return [{"id": r[0], "full_reference": r[1], "translation": r[2] or "", "purport_text": r[3] or ""} for r in rows]


def process_verses(verses: list, dry_run: bool = False):
    """Batch-process a list of verses through Gemini."""
    total = len(verses)
    logger.info(f"Processing {total} verses (batch size={BATCH_SIZE}, dry_run={dry_run})")

    processed = 0
    total_stats = {"entities_created": 0, "entities_reused": 0,
                   "relationships_created": 0, "mentions_created": 0}

    for i in range(0, total, BATCH_SIZE):
        batch = verses[i:i + BATCH_SIZE]
        verse_dicts = [
            {
                "full_reference": v["full_reference"],
                "translation": v["translation"],
                "purport_text": v["purport_text"],
            }
            for v in batch
        ]

        refs = ", ".join(v["full_reference"] for v in batch)
        logger.info(f"[{i+1}/{total}] Extracting: {refs}")

        result = extract_with_retry(verse_dicts)

        entities_found    = len(result.get("entities", []))
        rels_found        = len(result.get("relationships", []))
        logger.info(f"  → {entities_found} entities, {rels_found} relationships")

        if dry_run:
            for e in result.get("entities", []):
                logger.info(f"    ENTITY: [{e.get('type')}] {e.get('name')} — {e.get('description', '')[:80]}")
            for r in result.get("relationships", []):
                logger.info(f"    REL: {r.get('source')} --{r.get('type')}--> {r.get('target')}")
        else:
            stats = save_extraction_results(batch, result)
            for k in total_stats:
                total_stats[k] += stats[k]

            # Mark verses as processed
            conn = get_conn()
            cursor = conn.cursor()
            verse_ids = [v["id"] for v in batch]
            cursor.execute(
                f"UPDATE verses SET ai_processed = 1 WHERE id IN ({','.join(['%s']*len(verse_ids))})",
                verse_ids
            )
            conn.commit()
            cursor.close()
            conn.close()

        processed += len(batch)

        # Rate-limit
        if i + BATCH_SIZE < total:
            logger.info(f"  Sleeping {SLEEP_SECS}s (rate limit)…")
            time.sleep(SLEEP_SECS)

    logger.info(f"\n✓ Done! Processed {processed} verses")
    if not dry_run:
        logger.info(
            f"  Entities created: {total_stats['entities_created']}  "
            f"reused: {total_stats['entities_reused']}\n"
            f"  Relationships created: {total_stats['relationships_created']}\n"
            f"  Verse-entity mentions: {total_stats['mentions_created']}"
        )
    return total_stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Extract entities from Bhagavatam verses using Gemini")
    parser.add_argument("--book",    help="Book code: SB, CC, or CB")
    parser.add_argument("--canto",   type=int, help="Canto/section number")
    parser.add_argument("--chapter", type=int, help="Chapter number")
    parser.add_argument("--all",     action="store_true", help="Process all unprocessed verses")
    parser.add_argument("--dry-run", action="store_true", help="Print extraction results without saving")
    parser.add_argument("--limit",   type=int, default=None, help="Max verses to process (useful for testing)")
    args = parser.parse_args()

    if not args.book and not args.all:
        parser.error("Specify --book SB|CC|CB or --all")

    try:
        verses = get_verses_to_process(
            book_code=args.book,
            canto_num=args.canto,
            chapter_num=args.chapter,
        )

        if args.limit:
            verses = verses[:args.limit]

        if not verses:
            logger.info("No unprocessed verses found matching criteria.")
            return

        logger.info(f"Found {len(verses)} verses to process")
        process_verses(verses, dry_run=args.dry_run)

    except Exception as e:
        logger.error(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()

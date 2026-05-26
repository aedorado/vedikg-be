#!/usr/bin/env python3
"""
Migrate data from SQLite (bhagavatam.db) to PostgreSQL.

This script reads from the local SQLite database and inserts all data into
the PostgreSQL database specified in POSTGRES_URL.

Note: 354MB SQLite fits comfortably in 500MB PostgreSQL quota since PostgreSQL
is more efficient with compression (~200-250MB estimated).

Usage:
    python migrate_to_postgres.py --dry-run    # Preview what would be migrated
    python migrate_to_postgres.py              # Execute migration
"""

import os
import sqlite3
import logging
from dotenv import load_dotenv
import psycopg
import sys

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# SQLite path
SQLITE_DB = os.path.join(os.path.dirname(__file__), "bhagavatam.db")

# PostgreSQL connection
POSTGRES_URL = os.getenv("POSTGRES_URL")
if not POSTGRES_URL:
    raise ValueError("POSTGRES_URL environment variable not set")


def get_sqlite_conn():
    """Get SQLite connection."""
    return sqlite3.connect(SQLITE_DB)


def get_postgres_conn():
    """Get PostgreSQL connection."""
    return psycopg.connect(POSTGRES_URL)


def migrate_table(table_name: str, dry_run: bool = False):
    """Migrate a single table from SQLite to PostgreSQL."""
    
    sqlite_conn = get_sqlite_conn()
    sqlite_cursor = sqlite_conn.cursor()
    
    # Get all rows from SQLite
    sqlite_cursor.execute(f"SELECT * FROM {table_name}")
    rows = sqlite_cursor.fetchall()
    
    if not rows:
        logger.info(f"  {table_name}: no data")
        sqlite_conn.close()
        return 0
    
    # Get column names
    sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
    columns_info = sqlite_cursor.fetchall()
    columns = [col[1] for col in columns_info]
    sqlite_conn.close()
    
    # Check if table already has ALL data in PostgreSQL
    pg_conn = get_postgres_conn()
    pg_cursor = pg_conn.cursor()
    try:
        pg_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        existing_count = pg_cursor.fetchone()[0]
    except Exception:
        existing_count = 0
    finally:
        pg_cursor.close()
        pg_conn.close()
    
    if existing_count >= len(rows):
        logger.info(f"  {table_name}: complete ({existing_count}/{len(rows)} rows, skipping)")
        return 0
    
    # Resume from where we left off
    if existing_count > 0:
        logger.info(f"  {table_name}: resuming from row {existing_count}/{len(rows)}")
        rows = rows[existing_count:]  # Skip already-migrated rows
    
    if dry_run:
        logger.info(f"  {table_name}: {len(rows)} rows (would be migrated)")
        return len(rows)
    
    # Insert into PostgreSQL
    pg_conn = get_postgres_conn()
    pg_cursor = pg_conn.cursor()
    
    columns_str = ", ".join(columns)
    batch_size = 500
    
    try:
        for batch_start in range(0, len(rows), batch_size):
            batch = rows[batch_start:batch_start + batch_size]
            
            # Build multi-row INSERT with ON CONFLICT DO NOTHING to skip duplicates on resume
            placeholders = ", ".join([f"({', '.join(['%s'] * len(columns))})" for _ in batch])
            insert_query = f"INSERT INTO {table_name} ({columns_str}) VALUES {placeholders} ON CONFLICT DO NOTHING"
            
            # Flatten all values
            flat_values = []
            for row in batch:
                flat_values.extend([None if v is None else v for v in row])
            
            pg_cursor.execute(insert_query, flat_values)
            pg_conn.commit()
            
            idx = existing_count + min(batch_start + batch_size, len(rows))
            total = existing_count + len(rows)
            pct = (idx / total) * 100
            logger.info(f"    {table_name}: {idx}/{total} ({pct:.1f}%)")
        
        logger.info(f"  {table_name}: ✓ {len(rows)} rows migrated")
    except Exception as e:
        pg_conn.rollback()
        logger.error(f"  {table_name}: ERROR - {e}")
        raise
    finally:
        pg_cursor.close()
        pg_conn.close()
    
    return len(rows)


def get_table_size(table_name: str) -> int:
    """Get approximate size of table in bytes (SQLite)."""
    conn = get_sqlite_conn()
    cursor = conn.cursor()
    cursor.execute(f"SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size() WHERE name='{table_name}'")
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Migrate Bhagavatam data from SQLite to PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Preview migration without writing")
    args = parser.parse_args()
    
    # Tables to migrate (in order to respect foreign keys)
    # Skip: ai_entities, ai_relationships, ai_verse_entities, verse_entities (old, legacy tables)
    tables = [
        "books",
        "authors",
        "cantos",
        "chapters",
        "verses",
        "purports",
        "entities",
        "relationships",
        "scrape_jobs",
    ]
    
    logger.info("=" * 60)
    logger.info("Bhagavatam SQLite → PostgreSQL Migration")
    logger.info("=" * 60)
    logger.info(f"Source: {SQLITE_DB}")
    logger.info(f"Target: {POSTGRES_URL[:50]}...")
    logger.info(f"Mode: {'DRY-RUN' if args.dry_run else 'WRITE'}")
    logger.info("")
    
    total_rows = 0
    
    try:
        for idx, table in enumerate(tables, 1):
            pct = (idx / len(tables)) * 100
            logger.info(f"[{idx}/{len(tables)} ({pct:.0f}%)] Processing {table}...")
            try:
                rows = migrate_table(table, dry_run=args.dry_run)
                total_rows += rows
            except Exception as e:
                if "no such table" in str(e).lower():
                    logger.warning(f"  {table}: table not found (skipping)")
                else:
                    logger.error(f"  {table}: failed - {e}")
                    if not args.dry_run:
                        raise
        
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"Total rows migrated: {total_rows}")
        
        if args.dry_run:
            logger.info("This was a DRY-RUN. No data was written.")
            logger.info("Run without --dry-run to execute the migration.")
        else:
            logger.info("✓ Migration complete!")
        
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

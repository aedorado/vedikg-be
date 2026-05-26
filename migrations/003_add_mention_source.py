"""003_add_mention_source - Add mention_source column to track verse vs purport

Revision ID: 003
Revises: 002_ai_tables
Create Date: 2026-05-26 00:00:00.000000

"""

import psycopg


def upgrade(conn):
    """Add mention_source column to ai_verse_entities."""
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("""
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='ai_verse_entities' AND column_name='mention_source'
    """)
    if not cursor.fetchone():
        # Add column: 'verse' or 'purport'
        cursor.execute("""
            ALTER TABLE ai_verse_entities
            ADD COLUMN mention_source VARCHAR(20) DEFAULT 'verse'
        """)
        conn.commit()


def downgrade(conn):
    """Remove mention_source column."""
    cursor = conn.cursor()
    
    cursor.execute("""
        ALTER TABLE ai_verse_entities
        DROP COLUMN IF EXISTS mention_source
    """)
    
    conn.commit()

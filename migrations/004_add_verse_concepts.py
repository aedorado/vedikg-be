"""004_add_verse_concepts - Add table for verse concepts (themes, virtues, philosophical principles)

Revision ID: 004
Revises: 003_add_mention_source
Create Date: 2026-05-27 00:00:00.000000

""" 

import psycopg


def upgrade(conn):
    """Create verse concepts table."""
    cursor = conn.cursor()
    
    # AI Verse Concepts table (unified for all concept types)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_verse_concepts (
            id SERIAL PRIMARY KEY,
            verse_id INTEGER NOT NULL,
            concept VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_ai_verse_concepts_verse FOREIGN KEY (verse_id) REFERENCES verses(id) ON DELETE CASCADE
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_verse_concepts_verse ON ai_verse_concepts(verse_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_verse_concepts_concept ON ai_verse_concepts(concept)')
    
    conn.commit()


def downgrade(conn):
    """Revert concepts table."""
    cursor = conn.cursor()
    
    cursor.execute('DROP TABLE IF EXISTS ai_verse_concepts')
    
    conn.commit()



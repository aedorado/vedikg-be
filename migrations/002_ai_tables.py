"""002_ai_tables - Create AI-specific extraction tables

Revision ID: 002
Revises: 001_initial_schema
Create Date: 2026-05-26 00:00:00.000000

"""

import psycopg


def upgrade(conn):
    """Create AI-specific tables."""
    cursor = conn.cursor()
    
    # AI Entities table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_entities (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            normalized_name VARCHAR(255) NOT NULL UNIQUE,
            entity_type VARCHAR(50),
            description TEXT,
            aliases_json TEXT,
            sanskrit_name VARCHAR(255),
            first_seen_verse_id INTEGER,
            mention_count INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_ai_entities_verse FOREIGN KEY (first_seen_verse_id) REFERENCES verses(id)
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_entities_normalized ON ai_entities(normalized_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_entities_type ON ai_entities(entity_type)')
    
    # AI Relationships table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_relationships (
            id SERIAL PRIMARY KEY,
            source_entity_id INTEGER NOT NULL,
            target_entity_id INTEGER NOT NULL,
            relationship_type VARCHAR(50),
            context TEXT,
            source_verse_id INTEGER,
            confidence FLOAT DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_ai_rel_source FOREIGN KEY (source_entity_id) REFERENCES ai_entities(id),
            CONSTRAINT fk_ai_rel_target FOREIGN KEY (target_entity_id) REFERENCES ai_entities(id),
            CONSTRAINT fk_ai_rel_verse FOREIGN KEY (source_verse_id) REFERENCES verses(id),
            CONSTRAINT unique_ai_relationship UNIQUE(source_entity_id, target_entity_id, relationship_type)
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_relationships_source ON ai_relationships(source_entity_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_relationships_target ON ai_relationships(target_entity_id)')
    
    # AI Verse-Entity linking table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_verse_entities (
            id SERIAL PRIMARY KEY,
            verse_id INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            confidence FLOAT DEFAULT 1.0,
            CONSTRAINT fk_ai_ve_verse FOREIGN KEY (verse_id) REFERENCES verses(id),
            CONSTRAINT fk_ai_ve_entity FOREIGN KEY (entity_id) REFERENCES ai_entities(id),
            CONSTRAINT unique_ai_verse_entity UNIQUE(verse_id, entity_id)
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_verse_entities_verse ON ai_verse_entities(verse_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_verse_entities_entity ON ai_verse_entities(entity_id)')
    
    conn.commit()


def downgrade(conn):
    """Revert AI tables."""
    cursor = conn.cursor()
    
    cursor.execute('DROP TABLE IF EXISTS ai_verse_entities')
    cursor.execute('DROP TABLE IF EXISTS ai_relationships')
    cursor.execute('DROP TABLE IF EXISTS ai_entities')
    
    conn.commit()

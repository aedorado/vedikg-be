"""001_initial_schema - Create base tables

Revision ID: 001
Revises: None
Create Date: 2026-05-26 00:00:00.000000

"""

import psycopg


def upgrade(conn):
    """Apply initial schema."""
    cursor = conn.cursor()
    
    # Books table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            code VARCHAR(10) NOT NULL UNIQUE,
            title VARCHAR(255) NOT NULL,
            url_prefix VARCHAR(255),
            author VARCHAR(255),
            translator VARCHAR(255),
            commentary_name VARCHAR(255),
            commentary_author VARCHAR(255)
        )
    ''')
    
    # Authors table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS authors (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(100) NOT NULL UNIQUE
        )
    ''')
    
    # Cantos table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cantos (
            id SERIAL PRIMARY KEY,
            number INTEGER NOT NULL,
            title VARCHAR(255),
            slug VARCHAR(255) UNIQUE,
            summary TEXT,
            book_id INTEGER,
            section_label VARCHAR(100),
            CONSTRAINT fk_cantos_book FOREIGN KEY (book_id) REFERENCES books(id),
            CONSTRAINT unique_book_canto UNIQUE(book_id, number)
        )
    ''')
    
    # Chapters table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chapters (
            id SERIAL PRIMARY KEY,
            canto_id INTEGER NOT NULL,
            chapter_number INTEGER,
            title VARCHAR(255),
            slug VARCHAR(255),
            summary TEXT,
            source_url VARCHAR(500),
            CONSTRAINT fk_chapters_canto FOREIGN KEY (canto_id) REFERENCES cantos(id)
        )
    ''')
    
    # Verses table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS verses (
            id SERIAL PRIMARY KEY,
            chapter_id INTEGER NOT NULL,
            verse_number INTEGER,
            full_reference VARCHAR(50),
            source_url VARCHAR(500),
            devanagari TEXT,
            transliteration TEXT,
            translation TEXT,
            synonyms_raw TEXT,
            purport_html TEXT,
            purport_text TEXT,
            previous_verse_id INTEGER,
            next_verse_id INTEGER,
            chanda VARCHAR(255),
            chanda_json TEXT,
            language VARCHAR(5) DEFAULT 'sa',
            book_id INTEGER,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            ai_processed INTEGER DEFAULT 0,
            CONSTRAINT fk_verses_chapter FOREIGN KEY (chapter_id) REFERENCES chapters(id),
            CONSTRAINT fk_verses_prev FOREIGN KEY (previous_verse_id) REFERENCES verses(id),
            CONSTRAINT fk_verses_next FOREIGN KEY (next_verse_id) REFERENCES verses(id),
            CONSTRAINT fk_verses_book FOREIGN KEY (book_id) REFERENCES books(id)
        )
    ''')
        
    # Purports table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS purports (
            id SERIAL PRIMARY KEY,
            verse_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            body_html TEXT,
            body_text TEXT,
            language VARCHAR(5) DEFAULT 'en',
            CONSTRAINT fk_purports_verse FOREIGN KEY (verse_id) REFERENCES verses(id),
            CONSTRAINT fk_purports_author FOREIGN KEY (author_id) REFERENCES authors(id)
        )
    ''')
    
    # Create indexes
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_verses_full_reference ON verses(full_reference)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_verses_book_id ON verses(book_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_chapters_canto_id ON chapters(canto_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_purports_verse_id ON purports(verse_id)')
    
    # Old entities/relationships tables (legacy, keeping for reference)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS entities (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            normalized_name VARCHAR(255),
            entity_type VARCHAR(50),
            description TEXT,
            aliases_json TEXT,
            image_url VARCHAR(500),
            first_appearance_verse_id INTEGER,
            CONSTRAINT fk_entities_verse FOREIGN KEY (first_appearance_verse_id) REFERENCES verses(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS verse_entities (
            id SERIAL PRIMARY KEY,
            verse_id INTEGER,
            entity_id INTEGER,
            mention_location VARCHAR(50),
            mention_text TEXT,
            context_summary TEXT,
            confidence_score FLOAT DEFAULT 1.0,
            CONSTRAINT fk_verse_entities_verse FOREIGN KEY (verse_id) REFERENCES verses(id),
            CONSTRAINT fk_verse_entities_entity FOREIGN KEY (entity_id) REFERENCES entities(id)
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_verse_entities_verse_id ON verse_entities(verse_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_verse_entities_entity_id ON verse_entities(entity_id)')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS relationships (
            id SERIAL PRIMARY KEY,
            source_entity_id INTEGER,
            target_entity_id INTEGER,
            relationship_type VARCHAR(50),
            source_verse_id INTEGER,
            confidence_score FLOAT DEFAULT 1.0,
            CONSTRAINT fk_relationships_source FOREIGN KEY (source_entity_id) REFERENCES entities(id),
            CONSTRAINT fk_relationships_target FOREIGN KEY (target_entity_id) REFERENCES entities(id),
            CONSTRAINT fk_relationships_verse FOREIGN KEY (source_verse_id) REFERENCES verses(id)
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_relationships_source ON relationships(source_entity_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_relationships_target ON relationships(target_entity_id)')
    
    # Scrape jobs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scrape_jobs (
            id SERIAL PRIMARY KEY,
            canto_number INTEGER,
            chapter_number INTEGER,
            status VARCHAR(50) DEFAULT 'pending',
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            last_processed_verse INTEGER,
            error_message TEXT,
            book_code VARCHAR(10) DEFAULT 'SB'
        )
    ''')
    
    conn.commit()


def downgrade(conn):
    """Revert initial schema."""
    cursor = conn.cursor()
    
    # Drop in reverse dependency order
    cursor.execute('DROP TABLE IF EXISTS scrape_jobs')
    cursor.execute('DROP TABLE IF EXISTS relationships')
    cursor.execute('DROP TABLE IF EXISTS verse_entities')
    cursor.execute('DROP TABLE IF EXISTS entities')
    cursor.execute('DROP TABLE IF EXISTS purports')
    cursor.execute('DROP TABLE IF EXISTS verses')
    cursor.execute('DROP TABLE IF EXISTS chapters')
    cursor.execute('DROP TABLE IF EXISTS cantos')
    cursor.execute('DROP TABLE IF EXISTS authors')
    cursor.execute('DROP TABLE IF EXISTS books')
    
    conn.commit()

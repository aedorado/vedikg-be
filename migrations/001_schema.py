"""001_schema - Full schema: base tables, AI tables, and verse concepts

Revision ID: 001
Revises: None
Create Date: 2026-05-31

Consolidates: 001_initial_schema, 002_ai_tables, 003_add_mention_source, 004_add_themes_and_concepts
"""


def upgrade(conn):
    cursor = conn.cursor()

    # ── Core tables ───────────────────────────────────────────────────────────

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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS authors (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(100) NOT NULL UNIQUE
        )
    ''')

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

    # cursor.execute('''
    #     CREATE TABLE IF NOT EXISTS entities (
    #         id SERIAL PRIMARY KEY,
    #         name VARCHAR(255) NOT NULL UNIQUE,
    #         normalized_name VARCHAR(255),
    #         entity_type VARCHAR(50),
    #         description TEXT,
    #         aliases_json TEXT,
    #         image_url VARCHAR(500),
    #         first_appearance_verse_id INTEGER,
    #         CONSTRAINT fk_entities_verse FOREIGN KEY (first_appearance_verse_id) REFERENCES verses(id)
    #     )
    # ''')

    # cursor.execute('''
    #     CREATE TABLE IF NOT EXISTS verse_entities (
    #         id SERIAL PRIMARY KEY,
    #         verse_id INTEGER,
    #         entity_id INTEGER,
    #         mention_location VARCHAR(50),
    #         mention_text TEXT,
    #         context_summary TEXT,
    #         confidence_score FLOAT DEFAULT 1.0,
    #         CONSTRAINT fk_verse_entities_verse FOREIGN KEY (verse_id) REFERENCES verses(id),
    #         CONSTRAINT fk_verse_entities_entity FOREIGN KEY (entity_id) REFERENCES entities(id)
    #     )
    # ''')

    # cursor.execute('''
    #     CREATE TABLE IF NOT EXISTS relationships (
    #         id SERIAL PRIMARY KEY,
    #         source_entity_id INTEGER,
    #         target_entity_id INTEGER,
    #         relationship_type VARCHAR(50),
    #         source_verse_id INTEGER,
    #         confidence_score FLOAT DEFAULT 1.0,
    #         CONSTRAINT fk_relationships_source FOREIGN KEY (source_entity_id) REFERENCES entities(id),
    #         CONSTRAINT fk_relationships_target FOREIGN KEY (target_entity_id) REFERENCES entities(id),
    #         CONSTRAINT fk_relationships_verse FOREIGN KEY (source_verse_id) REFERENCES verses(id)
    #     )
    # ''')

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

    # ── AI tables ─────────────────────────────────────────────────────────────

    # cursor.execute('''
    #     CREATE TABLE IF NOT EXISTS ai_entities (
    #         id SERIAL PRIMARY KEY,
    #         name VARCHAR(255) NOT NULL,
    #         normalized_name VARCHAR(255) NOT NULL UNIQUE,
    #         entity_type VARCHAR(50),
    #         description TEXT,
    #         aliases_json TEXT,
    #         sanskrit_name VARCHAR(255),
    #         first_seen_verse_id INTEGER,
    #         mention_count INTEGER DEFAULT 1,
    #         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    #         CONSTRAINT fk_ai_entities_verse FOREIGN KEY (first_seen_verse_id) REFERENCES verses(id)
    #     )
    # ''')

    # cursor.execute('''
    #     CREATE TABLE IF NOT EXISTS ai_relationships (
    #         id SERIAL PRIMARY KEY,
    #         source_entity_id INTEGER NOT NULL,
    #         target_entity_id INTEGER NOT NULL,
    #         relationship_type VARCHAR(50),
    #         context TEXT,
    #         source_verse_id INTEGER,
    #         confidence FLOAT DEFAULT 1.0,
    #         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    #         CONSTRAINT fk_ai_rel_source FOREIGN KEY (source_entity_id) REFERENCES ai_entities(id),
    #         CONSTRAINT fk_ai_rel_target FOREIGN KEY (target_entity_id) REFERENCES ai_entities(id),
    #         CONSTRAINT fk_ai_rel_verse FOREIGN KEY (source_verse_id) REFERENCES verses(id),
    #         CONSTRAINT unique_ai_relationship UNIQUE(source_entity_id, target_entity_id, relationship_type)
    #     )
    # ''')

    # cursor.execute('''
    #     CREATE TABLE IF NOT EXISTS ai_verse_entities (
    #         id SERIAL PRIMARY KEY,
    #         verse_id INTEGER NOT NULL,
    #         entity_id INTEGER NOT NULL,
    #         confidence FLOAT DEFAULT 1.0,
    #         mention_source VARCHAR(20) DEFAULT 'verse',
    #         CONSTRAINT fk_ai_ve_verse FOREIGN KEY (verse_id) REFERENCES verses(id),
    #         CONSTRAINT fk_ai_ve_entity FOREIGN KEY (entity_id) REFERENCES ai_entities(id),
    #         CONSTRAINT unique_ai_verse_entity UNIQUE(verse_id, entity_id)
    #     )
    # ''')

    # cursor.execute('''
    #     CREATE TABLE IF NOT EXISTS ai_verse_concepts (
    #         id SERIAL PRIMARY KEY,
    #         verse_id INTEGER NOT NULL,
    #         concept VARCHAR(255) NOT NULL,
    #         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    #         CONSTRAINT fk_ai_verse_concepts_verse FOREIGN KEY (verse_id) REFERENCES verses(id) ON DELETE CASCADE
    #     )
    # ''')

    # ── Indexes ───────────────────────────────────────────────────────────────

    cursor.execute('CREATE INDEX IF NOT EXISTS ix_verses_full_reference ON verses(full_reference)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_verses_book_id ON verses(book_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_chapters_canto_id ON chapters(canto_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_purports_verse_id ON purports(verse_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_verse_entities_verse_id ON verse_entities(verse_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_verse_entities_entity_id ON verse_entities(entity_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_relationships_source ON relationships(source_entity_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_relationships_target ON relationships(target_entity_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_entities_normalized ON ai_entities(normalized_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_entities_type ON ai_entities(entity_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_relationships_source ON ai_relationships(source_entity_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_relationships_target ON ai_relationships(target_entity_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_verse_entities_verse ON ai_verse_entities(verse_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_verse_entities_entity ON ai_verse_entities(entity_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_verse_concepts_verse ON ai_verse_concepts(verse_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS ix_ai_verse_concepts_concept ON ai_verse_concepts(concept)')

    conn.commit()


def downgrade(conn):
    cursor = conn.cursor()

    cursor.execute('DROP TABLE IF EXISTS ai_verse_concepts')
    cursor.execute('DROP TABLE IF EXISTS ai_verse_entities')
    cursor.execute('DROP TABLE IF EXISTS ai_relationships')
    cursor.execute('DROP TABLE IF EXISTS ai_entities')
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

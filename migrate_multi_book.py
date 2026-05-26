"""
Migration: Add multi-book support (SB + CC + future).

Changes:
  - New tables: books, authors, purports
  - cantos: add book_id, section_label; replace unique(number) → unique(book_id, number)
  - verses: add language ('sa'|'bn'|'en'), book_id (denormalized)
  - scrape_jobs: add book_code

Run once:
  cd backend && venv/bin/python migrate_multi_book.py
"""
import sqlite3, sys
from pathlib import Path

# Using PostgreSQL via db.py wrapper
from db import get_conn

def run():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=OFF")

    # ── 1. books ──────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        VARCHAR(10)  NOT NULL UNIQUE,
            title       VARCHAR(255) NOT NULL,
            url_prefix  VARCHAR(255)
        )
    """)
    cur.execute("INSERT OR IGNORE INTO books (code,title,url_prefix) VALUES (?,?,?)",
                ("SB","Śrīmad-Bhāgavatam","https://vedabase.io/en/library/sb/"))
    cur.execute("INSERT OR IGNORE INTO books (code,title,url_prefix) VALUES (?,?,?)",
                ("CC","Caitanya-caritāmṛta","https://vedabase.io/en/library/cc/"))

    sb_id = cur.execute("SELECT id FROM books WHERE code='SB'").fetchone()[0]
    cc_id = cur.execute("SELECT id FROM books WHERE code='CC'").fetchone()[0]
    print(f"books: SB={sb_id}, CC={cc_id}")

    # ── 2. authors ────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS authors (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  VARCHAR(255) NOT NULL,
            slug  VARCHAR(100) NOT NULL UNIQUE
        )
    """)
    cur.execute("INSERT OR IGNORE INTO authors (name,slug) VALUES (?,?)",
                ("Śrīla Prabhupāda","srila-prabhupada"))
    prabhu_id = cur.execute("SELECT id FROM authors WHERE slug='srila-prabhupada'").fetchone()[0]
    print(f"authors: Prabhupāda={prabhu_id}")

    # ── 3. purports ───────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purports (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            verse_id   INTEGER NOT NULL REFERENCES verses(id),
            author_id  INTEGER NOT NULL REFERENCES authors(id),
            body_html  TEXT,
            body_text  TEXT,
            language   VARCHAR(5) DEFAULT 'en'
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_purports_verse_id ON purports(verse_id)")

    # Migrate existing verses.purport_text → purports table
    existing = cur.execute("SELECT COUNT(*) FROM purports").fetchone()[0]
    if existing == 0:
        cur.execute("""
            INSERT INTO purports (verse_id, author_id, body_html, body_text, language)
            SELECT id, ?, purport_html, purport_text, 'en'
            FROM verses
            WHERE purport_text IS NOT NULL AND purport_text != ''
        """, (prabhu_id,))
        print(f"Migrated {cur.rowcount} purports from verses table")
    else:
        print(f"purports already has {existing} rows, skipping migration")

    # ── 4. cantos: add book_id + section_label ────────────────────────────────
    cols = [r[1] for r in cur.execute("PRAGMA table_info(cantos)").fetchall()]
    if "book_id" not in cols:
        cur.execute("ALTER TABLE cantos ADD COLUMN book_id INTEGER REFERENCES books(id)")
        cur.execute("ALTER TABLE cantos ADD COLUMN section_label VARCHAR(100)")
        # All existing cantos are SB; set section_label = "Canto N"
        cur.execute("UPDATE cantos SET book_id=? WHERE book_id IS NULL", (sb_id,))
        cur.execute("""
            UPDATE cantos SET section_label = 'Canto ' || number
            WHERE section_label IS NULL
        """)
        print("cantos: added book_id, section_label")

    # Recreate cantos with unique(book_id, number) instead of unique(number)
    # SQLite can't drop constraints, so we check if the old unique index exists
    old_idx = cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='index' AND name='ix_cantos_number'
    """).fetchone()
    if old_idx:
        print("Recreating cantos table to fix unique constraint…")
        cur.executescript("""
            CREATE TABLE cantos_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                number        INTEGER NOT NULL,
                title         VARCHAR(255),
                slug          VARCHAR(255),
                summary       TEXT,
                book_id       INTEGER REFERENCES books(id),
                section_label VARCHAR(100),
                UNIQUE(book_id, number)
            );
            INSERT INTO cantos_new SELECT id,number,title,slug,summary,book_id,section_label FROM cantos;
            DROP TABLE cantos;
            ALTER TABLE cantos_new RENAME TO cantos;
            CREATE INDEX ix_cantos_id ON cantos(id);
        """)
        print("cantos: unique constraint updated to (book_id, number)")

    # ── 5. verses: add language + book_id ────────────────────────────────────
    cols = [r[1] for r in cur.execute("PRAGMA table_info(verses)").fetchall()]
    if "language" not in cols:
        cur.execute("ALTER TABLE verses ADD COLUMN language VARCHAR(5) DEFAULT 'sa'")
        print("verses: added language column (default 'sa')")
    if "book_id" not in cols:
        cur.execute("ALTER TABLE verses ADD COLUMN book_id INTEGER REFERENCES books(id)")
        # Denormalize: set book_id on all verses from their chapter → canto chain
        cur.execute("""
            UPDATE verses SET book_id = (
                SELECT c.book_id FROM chapters ch
                JOIN cantos c ON ch.canto_id = c.id
                WHERE ch.id = verses.chapter_id
            )
            WHERE book_id IS NULL
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS ix_verses_book_id ON verses(book_id)")
        print("verses: added book_id, backfilled from cantos")

    # ── 6. scrape_jobs: add book_code ─────────────────────────────────────────
    cols = [r[1] for r in cur.execute("PRAGMA table_info(scrape_jobs)").fetchall()]
    if "book_code" not in cols:
        cur.execute("ALTER TABLE scrape_jobs ADD COLUMN book_code VARCHAR(10) DEFAULT 'SB'")
        print("scrape_jobs: added book_code column")

    cur.execute("PRAGMA foreign_keys=ON")
    con.commit()
    con.close()
    print("\nMigration complete.")

if __name__ == "__main__":
    run()

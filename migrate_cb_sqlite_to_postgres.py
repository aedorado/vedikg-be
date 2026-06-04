#!/usr/bin/env python3
"""
Migrate CB verses from SQLite → Postgres.

Usage:
  python migrate_cb_sqlite_to_postgres.py
  python migrate_cb_sqlite_to_postgres.py --db /path/to/bhagavatam_cb_backup.db
"""
import argparse
import sqlite3
import sys
from pathlib import Path

from tqdm import tqdm

from dotenv import load_dotenv
load_dotenv()

from app.db.base import SessionLocal
from app.models.models import Book, Canto, Chapter, Verse

DEFAULT_DB = Path(__file__).parent.parent / "dbfiles" / "bhagavatam_cb_backup.db"


def migrate(sqlite_path: Path):
    if not sqlite_path.exists():
        print(f"❌ SQLite file not found: {sqlite_path}")
        sys.exit(1)

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    cur = src.cursor()

    db = SessionLocal()

    try:
        # ── Book ──────────────────────────────────────────────────────────────
        pg_book = db.query(Book).filter_by(code="CB").first()
        if not pg_book:
            row = cur.execute("SELECT * FROM books WHERE code='CB'").fetchone()
            pg_book = Book(
                code=row["code"],
                title=row["title"],
                url_prefix=row.get("url_prefix"),
            )
            db.add(pg_book)
            db.flush()
            print(f"  Created book: {pg_book.title}")
        else:
            print(f"  Book exists: {pg_book.title}")

        # ── Cantos ────────────────────────────────────────────────────────────
        canto_id_map: dict[int, int] = {}   # sqlite_id → postgres_id
        for row in cur.execute("SELECT * FROM cantos ORDER BY number"):
            pg_canto = db.query(Canto).filter_by(
                book_id=pg_book.id, number=row["number"]
            ).first()
            if not pg_canto:
                pg_canto = Canto(
                    book_id=pg_book.id,
                    number=row["number"],
                    title=row["title"],
                    slug=row["slug"],
                    summary=row["summary"],
                    section_label=row["section_label"],
                )
                db.add(pg_canto)
                db.flush()
                print(f"  Created canto: {pg_canto.title}")
            canto_id_map[row["id"]] = pg_canto.id

        # ── Chapters ──────────────────────────────────────────────────────────
        chapter_id_map: dict[int, int] = {}
        chapters = cur.execute("SELECT * FROM chapters ORDER BY id").fetchall()
        for row in chapters:
            pg_canto_id = canto_id_map.get(row["canto_id"])
            if not pg_canto_id:
                print(f"  ⚠️  Skipping chapter {row['id']} — canto not mapped")
                continue
            pg_ch = db.query(Chapter).filter_by(
                canto_id=pg_canto_id, chapter_number=row["chapter_number"]
            ).first()
            if not pg_ch:
                pg_ch = Chapter(
                    canto_id=pg_canto_id,
                    chapter_number=row["chapter_number"],
                    title=row["title"],
                    slug=row["slug"],
                    summary=row["summary"],
                    source_url=row["source_url"],
                )
                db.add(pg_ch)
                db.flush()
            chapter_id_map[row["id"]] = pg_ch.id

        print(f"  Chapters mapped: {len(chapter_id_map)}")

        # ── Verses ────────────────────────────────────────────────────────────
        verses = cur.execute("SELECT * FROM verses ORDER BY id").fetchall()
        print(f"  Migrating {len(verses)} verses...")

        # Find already-existing (chapter_id, verse_number) pairs to skip
        existing = {
            (r[0], r[1]) for r in
            db.query(Verse.chapter_id, Verse.verse_number)
              .filter(Verse.book_id == pg_book.id).all()
        }

        BATCH = 1000
        batch: list[dict] = []
        inserted = skipped = 0

        def flush(bar):
            nonlocal inserted
            if batch:
                db.bulk_insert_mappings(Verse, batch)
                db.commit()
                inserted += len(batch)
                batch.clear()
            bar.set_postfix(inserted=inserted, skipped=skipped)

        with tqdm(total=len(verses), unit="verse", ncols=80) as bar:
            for row in verses:
                pg_ch_id = chapter_id_map.get(row["chapter_id"])
                if not pg_ch_id or (pg_ch_id, row["verse_number"]) in existing:
                    skipped += 1
                    bar.update(1)
                    continue

                batch.append(dict(
                    chapter_id=pg_ch_id,
                    verse_number=row["verse_number"],
                    full_reference=row["full_reference"],
                    source_url=row["source_url"],
                    devanagari=row["devanagari"],
                    transliteration=row["transliteration"],
                    translation=row["translation"],
                    synonyms_raw=row["synonyms_raw"],
                    purport_html=row["purport_html"],
                    purport_text=row["purport_text"],
                    chanda=row["chanda"],
                    chanda_json=row["chanda_json"],
                    language=row["language"],
                    book_id=pg_book.id,
                    scraped_at=row["scraped_at"],
                ))
                bar.update(1)

                if len(batch) >= BATCH:
                    flush(bar)

            flush(bar)  # remaining

        print(f"\n✅ Done — {inserted} inserted, {skipped} skipped")

    except Exception as e:
        db.rollback()
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        db.close()
        src.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate CB verses from SQLite to Postgres")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"Path to SQLite file (default: {DEFAULT_DB})")
    args = parser.parse_args()
    print(f"📂 Source: {args.db}")
    migrate(args.db)


if __name__ == "__main__":
    main()

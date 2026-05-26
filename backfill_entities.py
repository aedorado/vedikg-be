"""
backfill_entities.py
Re-scans all scraped verses and creates missing Entity / VerseEntity records.
Run this after adding new entries to alias_resolver.ENTITY_ALIASES / PLACE_ALIASES.

Usage:
    cd backend
    venv/bin/python backfill_entities.py [--dry-run] [--canto N]
"""
import sys
import argparse
import logging
from sqlalchemy.orm import Session

# ── path setup ────────────────────────────────────────────────────────────────
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from app.db.base import SessionLocal
from app.models.models import Verse, Entity, VerseEntity, MentionLocation, Chapter, Canto
from app.nlp.relationship_extractor import RelationshipExtractor
from app.scraper.vedabase import _infer_entity_type

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

extractor = RelationshipExtractor()


def backfill(db: Session, dry_run: bool = False, canto_filter: int | None = None):
    query = db.query(Verse)
    if canto_filter:
        query = (
            query.join(Chapter, Verse.chapter_id == Chapter.id)
                 .join(Canto, Chapter.canto_id == Canto.id)
                 .filter(Canto.number == canto_filter)
        )

    verses = query.all()
    log.info(f"Processing {len(verses)} verses (dry_run={dry_run})")

    new_entities = 0
    new_links = 0

    for verse in verses:
        text = " ".join(filter(None, [verse.translation, verse.purport_text]))
        if not text.strip():
            continue

        found = extractor.extract_all_entities(text)

        for canonical_name in found:
            if not canonical_name or len(canonical_name) < 2:
                continue

            etype = _infer_entity_type(canonical_name)

            # Get or create Entity
            entity = db.query(Entity).filter(
                Entity.name == canonical_name
            ).first()

            if entity is None:
                if dry_run:
                    log.info(f"  [DRY] Would create entity: {canonical_name!r} ({etype})")
                    new_entities += 1
                else:
                    entity = Entity(
                        name=canonical_name,
                        entity_type=etype,
                        description="",
                    )
                    db.add(entity)
                    db.flush()
                    log.info(f"  Created entity: {canonical_name!r} ({etype})")
                    new_entities += 1
            elif entity.entity_type != etype and etype in ('place', 'river'):
                # Fix wrongly-typed existing entities (e.g. places typed as 'person')
                if dry_run:
                    log.info(f"  [DRY] Would fix type: {canonical_name!r} {entity.entity_type!r} → {etype!r}")
                else:
                    log.info(f"  Fixed type: {canonical_name!r} {entity.entity_type!r} → {etype!r}")
                    entity.entity_type = etype

            if dry_run or entity is None:
                continue

            # Check if VerseEntity link already exists
            existing_link = db.query(VerseEntity).filter(
                VerseEntity.verse_id == verse.id,
                VerseEntity.entity_id == entity.id,
            ).first()

            if existing_link is None:
                link = VerseEntity(
                    verse_id=verse.id,
                    entity_id=entity.id,
                    mention_location=MentionLocation.VERSE_TEXT,
                )
                db.add(link)
                new_links += 1

    if not dry_run:
        db.commit()

    log.info(f"Done. New entities: {new_entities}, New verse-entity links: {new_links}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--canto", type=int, default=None, help="Limit to a single canto number")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        backfill(db, dry_run=args.dry_run, canto_filter=args.canto)
    finally:
        db.close()

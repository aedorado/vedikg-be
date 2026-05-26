#!/usr/bin/env python3
"""Backfill entities for existing CC verses."""

import logging
from app.db.base import SessionLocal
from app.models.models import Verse, Entity, VerseEntity, Book
from app.nlp.relationship_extractor import RelationshipExtractor
from app.scraper.vedabase import _infer_entity_type, resolve_alias

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

db = SessionLocal()
rel_extractor = RelationshipExtractor()

# Get CC book
cc_book = db.query(Book).filter_by(code='CC').first()
if not cc_book:
    logger.error("CC book not found")
    exit(1)

# Get all CC verses without VerseEntity links
cc_verses = db.query(Verse).filter_by(book_id=cc_book.id).all()
logger.info(f"Found {len(cc_verses)} CC verses to process")

created_entities = 0
created_links = 0

for i, verse in enumerate(cc_verses, 1):
    if i % 100 == 0:
        logger.info(f"Processed {i}/{len(cc_verses)} verses")
    
    combined = (verse.translation or "") + " " + (verse.purport_text or "")
    if not combined.strip():
        continue
    
    try:
        entity_names = rel_extractor.extract_all_entities(combined)
        if not entity_names:
            continue
        
        for entity_name in entity_names:
            # Find or create entity
            entity = db.query(Entity).filter_by(normalized_name=entity_name.lower()).first()
            if not entity:
                entity = Entity(
                    name=entity_name,
                    normalized_name=entity_name.lower(),
                    entity_type=_infer_entity_type(entity_name),
                )
                db.add(entity)
                db.flush()
                created_entities += 1
            
            # Check if mention location can be determined
            verse_mention = verse.translation and entity_name.lower() in verse.translation.lower()
            purport_mention = verse.purport_text and entity_name.lower() in verse.purport_text.lower()
            
            if not (verse_mention or purport_mention):
                continue
            
            # Create VerseEntity link if it doesn't exist
            existing = db.query(VerseEntity).filter_by(
                verse_id=verse.id, entity_id=entity.id
            ).first()
            if not existing:
                location = "both" if (verse_mention and purport_mention) else ("verse_text" if verse_mention else "purport_text")
                db.add(VerseEntity(
                    verse_id=verse.id, entity_id=entity.id,
                    mention_location=location, confidence_score=0.9
                ))
                created_links += 1
    
    except Exception as e:
        logger.error(f"Error processing verse {verse.id}: {e}")

db.commit()
logger.info(f"Done. Created {created_entities} entities and {created_links} VerseEntity links")

# Show final entity count
final_count = db.query(Entity).filter(
    db.query(VerseEntity).filter_by(verse_id=Verse.id).exists()
).filter(Verse.book_id == cc_book.id).distinct().count()
print(f"\nFinal CC entities with mentions: {final_count}")

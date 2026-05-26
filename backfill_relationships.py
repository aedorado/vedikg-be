#!/usr/bin/env python3
"""
Re-extract relationships from all verses and update database with verse_id references.
This ensures all relationships are linked to their source verses.
"""

import logging
from app.db.base import SessionLocal
from app.models.models import Verse, Relationship, Entity, VerseEntity
from app.nlp.relationship_extractor import RelationshipExtractor
from app.nlp.alias_resolver import resolve_alias

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def backfill_relationships():
    db = SessionLocal()
    try:
        # Get all verses with text
        verses = db.query(Verse).filter(
            Verse.translation != None, 
            Verse.translation != ''
        ).all()
        logger.info(f"Processing {len(verses)} verses...")
        
        updated_count = 0
        created_count = 0
        skipped_count = 0
        
        extractor = RelationshipExtractor()
        
        for verse in verses:
            try:
                # Extract relationships from this verse
                rels = extractor.extract_relationships(verse.translation)
                
                if not rels:
                    skipped_count += 1
                    continue
                
                for subj_name, obj_name, rel_type in rels:
                    # Resolve names to entity IDs
                    subj_canonical, _ = resolve_alias(subj_name)
                    obj_canonical, _ = resolve_alias(obj_name)
                    
                    # Find or create entities
                    subj_entity = db.query(Entity).filter(Entity.name == subj_canonical).first()
                    obj_entity = db.query(Entity).filter(Entity.name == obj_canonical).first()
                    
                    if not subj_entity or not obj_entity:
                        continue  # Skip if entities don't exist
                    
                    # Find or create relationship
                    existing = db.query(Relationship).filter(
                        Relationship.source_entity_id == subj_entity.id,
                        Relationship.target_entity_id == obj_entity.id,
                        Relationship.relationship_type == rel_type
                    ).first()
                    
                    if existing:
                        # Update if verse_id is missing
                        if not existing.source_verse_id:
                            existing.source_verse_id = verse.id
                            updated_count += 1
                    else:
                        # Create new relationship
                        new_rel = Relationship(
                            source_entity_id=subj_entity.id,
                            target_entity_id=obj_entity.id,
                            relationship_type=rel_type,
                            source_verse_id=verse.id,
                            confidence_score=1.0
                        )
                        db.add(new_rel)
                        created_count += 1
                
            except Exception as e:
                logger.warning(f"Error processing {verse.full_reference}: {e}")
                continue
        
        db.commit()
        logger.info(f"✓ Backfill complete:")
        logger.info(f"  Updated: {updated_count} relationships")
        logger.info(f"  Created: {created_count} new relationships")
        logger.info(f"  Skipped: {skipped_count} verses with no relationships")
        
    finally:
        db.close()

if __name__ == "__main__":
    backfill_relationships()

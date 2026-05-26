"""
Backfill chanda detection for all verses in the database.
Uses the updated chanda_detector with fuzzy matching enabled.
"""

import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from app.db.base import SessionLocal
from app.models.models import Verse
from app.nlp.chanda_detector import detect_chanda_detail
from datetime import datetime

def backfill_chanda():
    """Update all verses with corrected chanda detection."""
    db = SessionLocal()
    
    try:
        # Get all verses with transliteration
        verses = db.query(Verse).filter(
            Verse.transliteration != None,
            Verse.transliteration != ""
        ).all()
        
        total = len(verses)
        print(f"Processing {total} verses...")
        
        updated_count = 0
        error_count = 0
        
        for i, verse in enumerate(verses, 1):
            try:
                # Run detection on transliteration
                result = detect_chanda_detail(verse.transliteration)
                
                if result:
                    verse.chanda = result.get("name")
                    verse.chanda_json = json.dumps(result, ensure_ascii=False)
                    verse.processed_at = datetime.utcnow()
                    updated_count += 1
                    
                    # Progress indicator every 50 verses
                    if i % 50 == 0:
                        print(f"  [{i}/{total}] Updated: {updated_count}, Errors: {error_count}")
                else:
                    verse.chanda = None
                    verse.chanda_json = None
                    verse.processed_at = datetime.utcnow()
                    updated_count += 1
                    
            except Exception as e:
                print(f"  ERROR on verse {verse.full_reference} (ID {verse.id}): {str(e)}")
                error_count += 1
        
        # Commit all changes
        db.commit()
        
        print(f"\n✓ Backfill complete!")
        print(f"  Total verses: {total}")
        print(f"  Updated: {updated_count}")
        print(f"  Errors: {error_count}")
        
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    backfill_chanda()

#!/usr/bin/env python3
"""
Show chanda detector input and output for sample verses.
Usage: venv/bin/python show_chanda_io.py
"""
import json
from app.db.base import SessionLocal
from app.models.models import Verse
from app.nlp.chanda_detector import detect_chanda_detail

db = SessionLocal()

# Get a few verses
verse_ids = [2028, 2052, 2030, 4731, 5515, 5218]
verses = db.query(Verse).filter(Verse.id.in_(verse_ids)).all()

output = []

for v in verses:
    print(f"\n{'='*80}")
    print(f"Verse: {v.full_reference} (ID: {v.id})")
    print(f"{'='*80}")
    
    # INPUT
    print(f"\nINPUT (IAST transliteration):")
    print(v.transliteration)
    
    # OUTPUT from chanda detector
    print(f"\nOUTPUT from detect_chanda_detail():")
    result = detect_chanda_detail(v.transliteration)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    output.append({
        "reference": v.full_reference,
        "id": v.id,
        "input": v.transliteration,
        "output": result
    })

db.close()

# Save to file
with open('/tmp/chanda_io.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\n\n✓ Saved detailed output to: /tmp/chanda_io.json")

from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.models import Entity, Relationship, VerseEntity, Verse
from typing import List, Dict
import json
import difflib


def _reference_to_slug(full_reference: str) -> str:
    """Convert 'SB 1.1.3' or 'SB 10.64.14-15' → '1/1/3' or '10/64/14-15'"""
    # Remove 'SB ' prefix and replace dots with slashes
    return full_reference.replace("SB ", "").replace(".", "/")


def _normalize_concept_name(name: str) -> str:
    """
    Normalize concept names to canonical forms.
    Examples:
      "expansion of the lord" → "expansion"
      "vilasa forms" → "vilasa"
      "expansion of godhead" → "expansion"
    """
    name_lower = name.lower().strip()
    
    # Remove common suffixes/modifiers
    suffixes = [
        " of the lord",
        " of godhead", 
        " of god",
        " forms",
        " form",
        " aspect",
        " aspects",
        " type",
        " types",
        " divine",
    ]
    
    for suffix in suffixes:
        if name_lower.endswith(suffix):
            return name_lower.replace(suffix, "").strip()
    
    return name_lower


def _find_similar_entity(db: Session, name: str, entity_type: str = None, threshold: float = 0.75) -> Entity:
    """
    Find a similar existing entity using fuzzy matching.
    Returns the best match if similarity >= threshold, otherwise None.
    """
    normalized_input = _normalize_concept_name(name)
    
    # First try exact normalized match
    query = db.query(Entity).filter_by(normalized_name=normalized_input)
    if entity_type:
        query = query.filter_by(entity_type=entity_type)
    exact_match = query.first()
    if exact_match:
        return exact_match
    
    # Get all entities of same type
    if entity_type:
        candidates = db.query(Entity).filter_by(entity_type=entity_type).all()
    else:
        candidates = db.query(Entity).all()
    
    best_match = None
    best_ratio = threshold
    
    for candidate in candidates:
        # Check against canonical name
        ratio = difflib.SequenceMatcher(None, normalized_input, candidate.normalized_name).ratio()
        
        # Also check against aliases
        if candidate.aliases_json:
            try:
                aliases = json.loads(candidate.aliases_json)
                for alias in aliases:
                    alias_normalized = _normalize_concept_name(alias)
                    alias_ratio = difflib.SequenceMatcher(None, normalized_input, alias_normalized).ratio()
                    if alias_ratio > ratio:
                        ratio = alias_ratio
            except (json.JSONDecodeError, TypeError):
                pass
        
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = candidate
    
    return best_match


def _add_alias_to_entity(db: Session, entity: Entity, new_alias: str) -> None:
    """Add a new alias to an entity if it doesn't already exist."""
    if not new_alias or new_alias.lower() == entity.name.lower():
        return
    
    try:
        aliases = json.loads(entity.aliases_json or "[]")
    except (json.JSONDecodeError, TypeError):
        aliases = []
    
    # Normalize before comparing
    new_alias_normalized = _normalize_concept_name(new_alias)
    existing_normalized = [_normalize_concept_name(a) for a in aliases]
    
    if new_alias_normalized not in existing_normalized:
        aliases.append(new_alias)
        entity.aliases_json = json.dumps(aliases)
        db.add(entity)


class EntityService:
    @staticmethod
    def get_all_entities(db: Session) -> List[Entity]:
        return db.query(Entity).all()

    @staticmethod
    def get_entity_by_id(db: Session, entity_id: int) -> Entity:
        return db.query(Entity).filter_by(id=entity_id).first()

    @staticmethod
    def get_entity_mentions(db: Session, entity_id: int) -> Dict:
        """Get all verses where entity is mentioned"""
        entity = db.query(Entity).filter_by(id=entity_id).first()
        if not entity:
            return None

        mentions = db.query(VerseEntity).filter_by(entity_id=entity_id).all()

        # Deduplicate: merge all mention_sources per verse_id
        verse_location: dict = {}
        for m in mentions:
            vid = m.verse_id
            loc = m.mention_source or "verse"
            if vid not in verse_location:
                verse_location[vid] = loc
            elif verse_location[vid] != loc:
                verse_location[vid] = "both"

        verses_raw = db.query(Verse).filter(Verse.id.in_(list(verse_location.keys()))).all()

        # Also deduplicate by full_reference (same verse scraped multiple times)
        seen_refs: set = set()
        verses = []
        for v in verses_raw:
            if v.full_reference not in seen_refs:
                seen_refs.add(v.full_reference)
                verses.append(v)

        locs = [verse_location[v.id] for v in verses]
        verse_text_count = sum(1 for l in locs if l in ("verse", "both", "text"))
        purport_count = sum(1 for l in locs if l in ("purport", "both"))

        return {
            "entity_id": entity_id,
            "name": entity.name,
            "entity_type": entity.entity_type,
            "total_mentions": len(verses),
            "in_verse_text": verse_text_count,
            "in_purport": purport_count,
            "verses": [
                {
                    "id": v.id,
                    "reference": v.full_reference,
                    "verse_slug": _reference_to_slug(v.full_reference),
                    "translation": v.translation,
                    "mention_source": verse_location.get(v.id),
                }
                for v in verses
            ],
        }

    @staticmethod
    def get_entity_relationships(db: Session, entity_id: int) -> Dict:
        """Get relationships for entity (as source or target)"""
        entity = db.query(Entity).filter_by(id=entity_id).first()
        if not entity:
            return None

        # Get where entity is source
        outgoing = db.query(Relationship).filter_by(source_entity_id=entity_id).all()
        # Get where entity is target
        incoming = db.query(Relationship).filter_by(target_entity_id=entity_id).all()

        relationships = {
            "family": [],
            "other": [],
        }

        # Build verse reference map
        verse_map = {}
        if outgoing or incoming:
            all_verse_ids = [r.source_verse_id for r in outgoing if r.source_verse_id]
            all_verse_ids += [r.source_verse_id for r in incoming if r.source_verse_id]
            if all_verse_ids:
                from app.models.models import Verse
                verses = db.query(Verse).filter(Verse.id.in_(set(all_verse_ids))).all()
                verse_map = {v.id: v.full_reference for v in verses}

        for rel in outgoing:
            target = db.query(Entity).filter_by(id=rel.target_entity_id).first()
            rel_data = {
                "target_id": target.id,
                "target_name": target.name,
                "relationship": rel.relationship_type,
                "direction": "outgoing",
                "verse_id": rel.source_verse_id,
                "verse_ref": verse_map.get(rel.source_verse_id) if rel.source_verse_id else None,
            }
            if "of" in rel.relationship_type:
                relationships["family"].append(rel_data)
            else:
                relationships["other"].append(rel_data)

        for rel in incoming:
            source = db.query(Entity).filter_by(id=rel.source_entity_id).first()
            rel_data = {
                "source_id": source.id,
                "source_name": source.name,
                "relationship": rel.relationship_type,
                "direction": "incoming",
                "verse_id": rel.source_verse_id,
                "verse_ref": verse_map.get(rel.source_verse_id) if rel.source_verse_id else None,
            }
            if "of" in rel.relationship_type:
                relationships["family"].append(rel_data)
            else:
                relationships["other"].append(rel_data)

        return {
            "entity_id": entity_id,
            "name": entity.name,
            "relationships": relationships,
        }

    @staticmethod
    def get_entity_graph(db: Session, entity_id: int, depth: int = 1) -> Dict:
        """Get relationship graph for visualization (React Flow format) - familial relationships only"""
        entity = db.query(Entity).filter_by(id=entity_id).first()
        if not entity:
            return None

        nodes = [{"id": str(entity.id), "label": entity.name, "type": "primary"}]
        edges = []
        visited = {entity.id}

        def traverse(ent_id: int, current_depth: int):
            if current_depth > depth:
                return

            rels = db.query(Relationship).filter(
                ((Relationship.source_entity_id == ent_id) | (Relationship.target_entity_id == ent_id)),
                Relationship.relationship_type.contains("of")
            ).all()

            for rel in rels:
                other_id = rel.target_entity_id if rel.source_entity_id == ent_id else rel.source_entity_id
                if other_id not in visited:
                    other_entity = db.query(Entity).filter_by(id=other_id).first()
                    if other_entity and other_entity.entity_type == "person":
                        visited.add(other_id)
                        nodes.append({"id": str(other_id), "label": other_entity.name})
                        edges.append(
                            {
                                "source": str(rel.source_entity_id),
                                "target": str(rel.target_entity_id),
                                "label": rel.relationship_type.replace("_", " "),
                            }
                        )
                        traverse(other_id, current_depth + 1)

        traverse(entity_id, 1)
        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def get_or_create_entity_normalized(
        db: Session,
        name: str,
        entity_type: str,
        similarity_threshold: float = 0.75
    ) -> Entity:
        """
        Get or create an entity with smart normalization and deduplication.
        
        - First tries exact normalized name match
        - Then uses fuzzy matching to find similar entities
        - If found similar: adds new name as alias to that entity
        - If not found: creates new entity with normalized name
        
        Returns the canonical entity object.
        """
        if not name or not name.strip():
            return None
        
        name = name.strip()
        normalized = _normalize_concept_name(name)
        
        # Try exact match on normalized name
        exact = db.query(Entity).filter_by(
            normalized_name=normalized,
            entity_type=entity_type
        ).first()
        if exact:
            # Add input name as alias if different from canonical
            if name.lower() != exact.name.lower():
                _add_alias_to_entity(db, exact, name)
            return exact
        
        # Try fuzzy match against similar entities
        similar = _find_similar_entity(db, name, entity_type, similarity_threshold)
        if similar:
            # Add the input name as an alias
            _add_alias_to_entity(db, similar, name)
            return similar
        
        # No match found, create new entity
        new_entity = Entity(
            name=name,
            normalized_name=normalized,
            entity_type=entity_type,
            aliases_json=json.dumps([])
        )
        db.add(new_entity)
        db.flush()
        return new_entity

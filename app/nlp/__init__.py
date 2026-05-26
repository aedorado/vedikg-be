"""NLP module for entity and relationship extraction."""

from app.nlp.alias_resolver import (
    resolve_alias,
    get_all_known_entities,
    get_aliases_for_entity,
)
from app.nlp.relationship_extractor import RelationshipExtractor

__all__ = [
    "resolve_alias",
    "get_all_known_entities",
    "get_aliases_for_entity",
    "RelationshipExtractor",
]

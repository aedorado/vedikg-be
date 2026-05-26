"""
Relationship extraction from Bhagavata Purana text.
Extracts family relationships using patterns and NLP heuristics.

Entity extraction uses two layers:
  1. Alias resolver  — maps known variant spellings to canonical names.
  2. Auto-discovery  — finds NEW proper nouns via title-patterns and
                       diacritic-bearing capitalised words (Sanskrit names
                       almost always carry diacritics; common English words
                       never do).  This means we don't need a pre-defined
                       list for every personality in the SB.
"""

import re
import logging
from typing import List, Tuple, Dict, Optional
from app.nlp.alias_resolver import resolve_alias, ALIAS_TO_ENTITY, get_aliases_for_entity

logger = logging.getLogger(__name__)

# ── Stop-words: capitalised in Vedic texts but NOT personal names ─────────────
_STOP = {
    # English function words
    "the", "a", "an", "and", "or", "but", "for", "with", "from", "that",
    "this", "these", "those", "it", "he", "she", "they", "we", "you", "i",
    "is", "are", "was", "were", "be", "been", "have", "has", "had",
    "do", "does", "did", "will", "would", "shall", "should", "may",
    "might", "can", "could", "must", "in", "on", "at", "to", "of",
    "him", "his", "her", "its", "them", "their", "my", "our", "your",
    "by", "as", "so", "if", "not", "also", "thus", "hence", "therefore",
    "however", "although", "because", "indeed", "moreover",
    # Vedic philosophical concepts (not names)
    "supreme", "absolute", "truth", "brahman", "godhead", "personality",
    "transcendental", "material", "spiritual", "devotional", "liberation",
    "mukti", "moksha", "karma", "dharma", "yoga", "bhakti", "jnana",
    "deva", "asura", "rasa", "sattva", "rajas", "tamas", "maya",
    "atma", "paramatma", "jivatma", "prakrti", "prakriti",
    # Titles / honorifics used standalone (not part of a name)
    "lord", "king", "queen", "prince", "princess", "muni", "sage",
    "saint", "maharaja", "mahārāja", "gosvami", "gosvāmī", "svami",
    "svāmī", "acarya", "ācārya", "prabhu", "śrīla", "srila",
    # Sanskrit honorific prefixes — NEVER standalone entities
    "śrī", "sri", "śrīman", "sriman", "śrīmad", "srimad",
    # Common Sanskrit words that are NOT personal names
    "ślokas", "śloka", "kali",
    # Scriptures / generic nouns
    "veda", "vedas", "upanishad", "gita", "purana", "bhagavatam",
    "great", "divine", "holy", "sacred", "pure", "good", "evil",
    "one", "two", "three", "many", "all", "some", "any", "no",
    "time", "world", "earth", "heaven", "nature", "creation",
    "god", "soul", "life", "death", "body", "mind", "heart",
}

# Sanskrit diacritic characters — their PRESENCE strongly signals a Sanskrit word
_DIACRITICS_RE = re.compile(r'[āĀīĪūŪṛṚṭṬḍḌṇṆṅṄḥḤṃṂṁṀśŚṣṢñÑḷḶ]')

# Title prefixes that reliably precede a personal name
_TITLE_RE = re.compile(
    r'\b(?:Mahārāja|Maharaja|King|Queen|Prince|Princess|Lord|Lady|'
    r'Muni|Ṛṣi|R[sṣ]i|Sage|Saint|'
    r'Gosvāmī|Gosvami|Svāmī|Svami|Swami|'
    r'Ācārya|Acarya|Prabhu|Śrīla|Srila|'
    r'Śrī|Sri|O)\s+'                            # "O Name" = vocative
    r'([A-ZĀĪŪŚṢ][^\s,\.;:!\?\"\']{1,40})',    # capture the name that follows
    re.UNICODE
)

# Bare capitalised Sanskrit word (must contain a diacritic → almost certainly a name)
_DIACRITIC_NAME_RE = re.compile(
    r'\b([A-ZĀĪŪŚṢ][a-zA-ZāĀīĪūŪṛṚṭṬḍḌṇṆṅṄḥḤṃṂṁṀśŚṣṢñÑḷḶ\-]{2,})\b',
    re.UNICODE
)


# Title words that can appear as prefix OR suffix of a proper name
# e.g. "King Viśvasaha" → "Viśvasaha", "Sagara Mahārāja" → "Sagara"
_TITLE_AFFIXES = {
    'king', 'queen', 'prince', 'princess', 'lord', 'lady', 'sir',
    'maharaja', 'mahārāja', 'muni', 'sage', 'saint', 'ṛṣi',
    'gosvami', 'gosvāmī', 'svāmi', 'svāmī', 'swami',
    'prabhu', 'śrīla', 'srila', 'śrī', 'sri', 'o',
    'great', 'famous', 'the',
    # Sentence-opening connectives that look capitalised but are NOT names
    'then', 'thereafter', 'thus', 'once', 'later', 'after', 'before',
    'when', 'while', 'now', 'next', 'also', 'because', 'although',
}


def _strip_title_affixes(name: str) -> str:
    """Remove leading/trailing title words: 'King Viśvasaha' → 'Viśvasaha',
    'Sagara Mahārāja' → 'Sagara', 'Mahārāja Khaṭvāṅga' → 'Khaṭvāṅga'."""
    parts = name.split()
    while parts and parts[0].lower() in _TITLE_AFFIXES:
        parts = parts[1:]
    while parts and parts[-1].lower() in _TITLE_AFFIXES:
        parts = parts[:-1]
    return ' '.join(parts) if parts else name


def _is_valid_candidate(name: str) -> bool:
    """Return True if `name` looks like a personal name rather than a common word."""
    if not name or len(name) < 3:
        return False
    if name.lower() in _STOP:
        return False
    # Must start with an uppercase letter
    if not name[0].isupper():
        return False
    # Reject pure-digit strings
    if name.replace('-', '').replace(' ', '').isdigit():
        return False
    # Reject over-hyphenated compounds (e.g. "Ābrahma-bhuvanāl") — these are
    # Sanskrit grammatical forms, not personal names.
    if name.count('-') > 1:
        return False
    # For hyphenated names, every component must start with an uppercase letter
    # (e.g. "Śrīmad-Bhāgavatam" is valid; "Ābrahma-bhuvanāl" is NOT because
    # "bhuvanāl" starts lowercase).
    if '-' in name:
        if not all(part and part[0].isupper() for part in name.split('-')):
            return False
    return True


class RelationshipExtractor:
    """Extract entities and family relationships from verse / purport text."""

    def extract_all_entities(self, text: str) -> List[str]:
        """
        Return canonical entity names found in *text*.

        Layer 1 — alias lookup  : fast, exact, handles diacritics variants.
        Layer 2 — auto-discovery: title-pattern + diacritic-bearing proper nouns.
        Layer 3 — relationship patterns: names captured from genealogy sentences,
                  works even for names WITHOUT diacritics (e.g. Purukutsa).
        New names are returned as-is so the scraper creates Entity rows on the fly.
        """
        entities: set = set()

        # ── Layer 1: alias resolver ───────────────────────────────────────────
        for alias_key, entity_name in ALIAS_TO_ENTITY.items():
            pattern = r'\b' + re.escape(alias_key) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                entities.add(entity_name)

        # ── Layer 2: title-pattern + diacritic words ──────────────────────────
        candidates: set = set()
        for m in _TITLE_RE.finditer(text):
            raw = m.group(1).strip().rstrip('.,;:!?')
            if _is_valid_candidate(raw):
                candidates.add(raw)
        for m in _DIACRITIC_NAME_RE.finditer(text):
            raw = m.group(1)
            if _is_valid_candidate(raw) and _DIACRITICS_RE.search(raw):
                candidates.add(raw)
        for candidate in candidates:
            canonical, _ = resolve_alias(candidate)
            entities.add(canonical)

        # ── Layer 3: names extracted from relationship patterns ───────────────
        for name1, name2, _ in self.extract_relationships_direct(text):
            entities.add(name1)
            entities.add(name2)

        return sorted(entities)

    def extract_relationships(self, text: str) -> List[Tuple[str, str, str]]:
        """Extract family relationships. Combines direct-pattern scan with
        pairwise alias matching for maximum coverage."""
        results: set = set()
        # Direct scan (primary — works for all names incl. no-diacritic)
        for rel in self.extract_relationships_direct(text):
            results.add(rel)
        # Pairwise alias matching (catches complex sentence structures)
        known = [e for e in self.extract_all_entities(text)]
        for entity1 in known:
            aliases1 = get_aliases_for_entity(entity1) or [entity1]
            for entity2 in known:
                if entity1 == entity2:
                    continue
                aliases2 = get_aliases_for_entity(entity2) or [entity2]
                for a1 in aliases1:
                    for a2 in aliases2:
                        for rel in self._find_relationships_between_aliases(text, a1, a2, entity1, entity2):
                            results.add(rel)
        return list(results)

    def extract_relationships_direct(self, text: str) -> List[Tuple[str, str, str]]:
        """
        Scan text for genealogy/family sentences and extract (name1, name2, rel_type).
        Works for names WITH and WITHOUT diacritics because names are captured
        from well-defined relationship contexts, not discovered by spelling alone.
        """
        # Captures a capitalised Sanskrit name (1–2 words), including ṅ, ñ, ṁ, ḷ
        N = (r'([A-ZĀĪŪṚṬḌṆḤṂŚṢ]'
             r'[a-zA-ZāĀīĪūŪṛṚṭṬḍḌṇṆṅṄḥḤṃṂṁṀśŚṣṢñÑḷḶ\-]+'
             r'(?:\s+[A-ZĀĪŪṚṬḌṆḤṂŚṢ]'
             r'[a-zA-ZāĀīĪūŪṛṚṭṬḍḌṇṆṅṄḥḤṃṂṁṀśŚṣṢñÑḷḶ\-]+)?)')

        # (pattern, rel_type, subj_group, obj_group)
        # subj=the person the rel_type belongs TO (e.g. father_of: subj is the father)
        patterns = [
            (rf'{N}\s+(?:was|is)\s+(?:the\s+)?father\s+of\s+{N}',    'father_of',   1, 2),
            (rf'{N}\s+(?:was|is)\s+(?:the\s+)?mother\s+of\s+{N}',    'mother_of',   1, 2),
            (rf'{N}\s+(?:was|is)\s+(?:the\s+)?son\s+of\s+{N}',       'son_of',      1, 2),
            (rf'{N}\s+(?:was|is)\s+(?:the\s+)?daughter\s+of\s+{N}',  'daughter_of', 1, 2),
            (rf'{N}\s+(?:was|is)\s+(?:the\s+)?(?:wife|consort|spouse)\s+of\s+{N}', 'spouse_of', 1, 2),
            (rf'{N}\s+(?:was|is)\s+(?:the\s+)?brother\s+of\s+{N}',   'brother_of',  1, 2),
            (rf'{N}\s+(?:was|is)\s+(?:the\s+)?sister\s+of\s+{N}',    'sister_of',   1, 2),
            # "son/daughter/father of X was Y"  → Y has that relation to X
            (rf'\bson\s+of\s+{N}\s+was\s+{N}',       'son_of',      2, 1),
            # Allow up to 3 filler words between "was" and the name:
            # e.g. "son of King Viśvasaha was the famous Mahārāja Khaṭvāṅga"
            (rf'\bson\s+of\s+{N}\s+was\s+(?:\w+\s+){{1,3}}{N}', 'son_of', 2, 1),
            # "son of X was known/celebrated/called as Y"
            (rf'\bson\s+of\s+{N}\s+was\s+(?:known|celebrated|called)\s+as\s+{N}',
             'son_of', 2, 1),
            (rf'\bdaughter\s+of\s+{N}\s+was\s+{N}',  'daughter_of', 2, 1),
            (rf'\bfather\s+of\s+{N}\s+was\s+{N}',    'father_of',   2, 1),
            (rf'\bmother\s+of\s+{N}\s+was\s+{N}',    'mother_of',   2, 1),
            # Possessive: "X's son/daughter/wife was Y" and "X's son, Y" (appositive)
            (rf"{N}'s\s+son\s+(?:was|is)\s+{N}",       'son_of',    2, 1),
            (rf"{N}'s\s+son,\s+{N}",                   'father_of', 1, 2),
            (rf"{N}'s\s+daughter\s+(?:was|is)\s+{N}",  'daughter_of', 2, 1),
            (rf"{N}'s\s+wife\s+(?:was|is)\s+{N}",      'spouse_of', 2, 1),
            (rf"{N}'s\s+husband\s+(?:was|is)\s+{N}",   'spouse_of', 1, 2),
            # Appositive: "X, the father/son of Y"
            (rf'{N},\s+(?:the\s+)?father\s+of\s+{N}',   'father_of',   1, 2),
            (rf'{N},\s+(?:the\s+)?son\s+of\s+{N}',      'son_of',      1, 2),
            (rf'{N},\s+(?:the\s+)?daughter\s+of\s+{N}', 'daughter_of', 1, 2),
            # Relative clause: "X, who was the father/son/etc. of Y"
            (rf'{N},\s+who\s+was\s+(?:the\s+)?father\s+of\s+{N}',    'father_of',   1, 2),
            (rf'{N},\s+who\s+was\s+(?:the\s+)?son\s+of\s+{N}',       'son_of',      1, 2),
            (rf'{N},\s+who\s+was\s+(?:the\s+)?mother\s+of\s+{N}',    'mother_of',   1, 2),
            (rf'{N},\s+who\s+was\s+(?:the\s+)?daughter\s+of\s+{N}',  'daughter_of', 1, 2),
            (rf'{N},\s+who\s+was\s+(?:the\s+)?(?:wife|consort)\s+of\s+{N}', 'spouse_of', 1, 2),
            # Begetting / birth
            (rf'{N}\s+begot\s+{N}',                           'father_of', 1, 2),
            (rf'{N}\s+begot\s+a\s+son\s+named\s+{N}',        'father_of', 1, 2),
            (rf'{N}\s+had\s+a\s+son\s+named\s+{N}',          'father_of', 1, 2),
            (rf'{N}\s+gave\s+birth\s+to\s+{N}',              'mother_of', 1, 2),
            (rf'{N}\s+was\s+born\s+(?:of|to|from)\s+{N}',   'son_of',    1, 2),
            # "From X came [a son named] Y"  — succession form used throughout 9.8/9.9
            (rf'[Ff]rom\s+{N}\s+came\s+(?:a\s+son\s+named\s+)?{N}', 'son_of', 2, 1),
            # "From X, Y took birth" (SB 9.9.40: "From Aśmaka, Bālika took birth")
            (rf'[Ff]rom\s+{N},?\s+{N}\s+took\s+birth', 'son_of', 2, 1),
            # "X took birth from Y"
            (rf'{N}\s+took\s+birth\s+from\s+{N}', 'son_of', 1, 2),
            # "sons of X ... celebrated/known/called as Y"
            # Handles: "most prominent among the sons of Māndhātā was he who is
            #           celebrated as Ambarīṣa"
            (rf'sons?\s+of\s+{N}.{{0,250}}?(?:celebrated|known|called)\s+as\s+{N}',
             'son_of', 2, 1),
            # "from X came sons/daughters, named Y" — direct genealogy (higher priority for false positive avoidance)
            # Matches: "from Mitrāyu came four sons, named Cyavana"
            (rf'[Ff]rom\s+{N}\s+came\s+(?:\w+\s+)*(?:sons?|daughters?),?\s+named\s+{N}', 'son_of', 2, 1),
            # "sons of X ... one named Y" (SB 9.8.14: "sons of Sagara…one named Asamañjasa")
            # Reduced span to 100 chars to avoid matching across multiple lineages
            (rf'sons?\s+of\s+{N}.{{0,100}}?(?:one\s+)?named\s+{N}', 'son_of', 2, 1),
            # Marriage
            (rf'{N}\s+married\s+{N}',   'spouse_of', 1, 2),
            # "X accepted/chose/took Y as her/his husband"
            (rf'{N}\s+accepted\s+{N}\s+as\s+(?:her|his)\s+husband', 'spouse_of', 2, 1),
            (rf'{N}\s+accepted\s+{N}\s+as\s+(?:her|his)\s+wife',    'spouse_of', 1, 2),
            (rf'{N}\s+(?:chose|selected|took)\s+{N}\s+as\s+(?:her|his)\s+husband', 'spouse_of', 2, 1),
            (rf'{N}\s+(?:chose|selected|took)\s+{N}\s+as\s+(?:her|his)\s+wife',    'spouse_of', 1, 2),
            # Future tense genealogy: "son of X will be Y"
            (rf'\bson\s+of\s+{N}\s+will\s+be\s+{N}',       'son_of',      2, 1),
            (rf'\bdaughter\s+of\s+{N}\s+will\s+be\s+{N}',  'daughter_of', 2, 1),
            # "From X will come [a son named] Y"
            (rf'[Ff]rom\s+{N}\s+will\s+come\s+(?:a\s+son\s+named\s+)?{N}', 'son_of', 2, 1),
            # Short-form genealogy chain "from X, Y" (e.g. "from Medhāvī, Nṛpañjaya; from Nṛpañjaya, Dūrva")
            (rf'[Ff]rom\s+{N},\s+{N}', 'son_of', 2, 1),
            # "daughters named X" / "X had daughters named Y" 
            (rf'{N}\s+had\s+(?:\w+\s+)?daughters?,\s+named\s+{N}',  'daughter_of', 2, 1),
            (rf'{N}\s+had\s+(?:\w+\s+)?sons?,\s+named\s+{N}',       'son_of',      2, 1),
            # "X gave birth to ... a daughter known/named as Y"
            (rf'{N}\s+gave\s+birth\s+to\s+.{{0,80}}?daughter\s+(?:known\s+as|named)\s+{N}', 'mother_of', 1, 2),
            # Womb/semen birth patterns
            # "in the womb of X ... Y took birth"
            (rf'womb\s+of\s+{N}.{{0,120}}?{N}\s+took\s+birth', 'mother_of', 1, 2),
            # "semen of X in the womb of Y ... Z took birth"
            (rf'semen\s+of\s+{N}.{{0,120}}?{N}\s+took\s+birth', 'father_of', 1, 2),
        ]

        seen: set = set()
        results = []
        # Normalise curly apostrophes from HTML scrapers → straight apostrophe
        text = text.replace('\u2019', "'").replace('\u2018', "'")
        for pattern, rel_type, g_subj, g_obj in patterns:
            for m in re.finditer(pattern, text, re.UNICODE):
                name1 = _strip_title_affixes(m.group(g_subj).strip())
                name2 = _strip_title_affixes(m.group(g_obj).strip())
                if not _is_valid_candidate(name1) or not _is_valid_candidate(name2):
                    continue
                if name1.lower() in _STOP or name2.lower() in _STOP:
                    continue
                # Normalise via alias resolver
                can1, _ = resolve_alias(name1)
                can2, _ = resolve_alias(name2)
                key = (can1, can2, rel_type)
                if key not in seen:
                    seen.add(key)
                    results.append((can1, can2, rel_type))
        return results

        """
        Return canonical entity names found in *text*.

        Layer 1 — alias lookup  : fast, exact, handles diacritics variants.
        Layer 2 — auto-discovery: title-pattern + diacritic-bearing proper nouns.
        New names discovered in layer 2 are returned as-is so the scraper can
        create Entity rows on the fly — no pre-registration needed.
        """
        entities: set = set()

        # ── Layer 1: alias resolver (known entities) ─────────────────────────
        for alias_key, entity_name in ALIAS_TO_ENTITY.items():
            pattern = r'\b' + re.escape(alias_key) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                entities.add(entity_name)

        # ── Layer 2: auto-discover unknown proper nouns ──────────────────────
        candidates: set = set()

        # 2a. Title + Name  (e.g. "King Hariścandra", "Muni Viśvāmitra")
        for m in _TITLE_RE.finditer(text):
            raw = m.group(1).strip().rstrip('.,;:!?')
            # May be "Name Gosvāmī" — keep full form as canonical
            if _is_valid_candidate(raw):
                candidates.add(raw)

        # 2b. Capitalised word that contains at least one Sanskrit diacritic
        for m in _DIACRITIC_NAME_RE.finditer(text):
            raw = m.group(1)
            if _is_valid_candidate(raw) and _DIACRITICS_RE.search(raw):
                candidates.add(raw)

        # For each candidate: resolve via alias resolver first, else keep as-is
        for candidate in candidates:
            canonical, is_known = resolve_alias(candidate)
            if is_known:
                entities.add(canonical)
            else:
                # Genuine new name — add it so the scraper creates an entity
                entities.add(candidate)

        return sorted(entities)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _find_relationships_between_aliases(
        self,
        text: str,
        alias1: str,
        alias2: str,
        entity1: str,
        entity2: str
    ) -> List[Tuple[str, str, str]]:
        # Word boundaries prevent short aliases like "Hari" matching inside "Hariścandra"
        a1 = r'(?<![\w])' + re.escape(alias1) + r'(?![\w])'
        a2 = r'(?<![\w])' + re.escape(alias2) + r'(?![\w])'
        patterns = [
            (rf"{a1}\s+(?:is\s+)?(?:the\s+)?father\s+of\s+{a2}", "father_of"),
            (rf"{a1}\s+(?:is\s+)?(?:the\s+)?mother\s+of\s+{a2}", "mother_of"),
            (rf"{a1}\s+(?:is\s+)?(?:the\s+)?son\s+of\s+{a2}",    "son_of"),
            (rf"{a1}\s+(?:is\s+)?(?:the\s+)?daughter\s+of\s+{a2}","daughter_of"),
            (rf"{a1}\s+(?:is\s+)?(?:the\s+)?(?:wife|spouse|consort)\s+of\s+{a2}", "spouse_of"),
            (rf"{a1}\s+(?:is\s+)?(?:the\s+)?brother\s+of\s+{a2}", "brother_of"),
            (rf"{a1}\s+(?:is\s+)?(?:the\s+)?sister\s+of\s+{a2}",  "sister_of"),
            (rf"(?:the\s+)?father\s+of\s+{a2}\s+(?:is|was)\s+{a1}", "father_of"),
            (rf"(?:the\s+)?mother\s+of\s+{a2}\s+(?:is|was)\s+{a1}", "mother_of"),
            (rf"(?:the\s+)?son\s+of\s+{a2}\s+(?:is|was)\s+{a1}",    "son_of"),
            (rf"(?:the\s+)?daughter\s+of\s+{a2}\s+(?:is|was)\s+{a1}","daughter_of"),
            (rf"{a2}\s+(?:is\s+)?(?:the\s+)?father\s+of\s+{a1}", "son_of"),
            (rf"{a2}\s+(?:is\s+)?(?:the\s+)?mother\s+of\s+{a1}", "daughter_of"),
            (rf"{a2}\s+(?:is\s+)?(?:the\s+)?son\s+of\s+{a1}",    "father_of"),
            (rf"{a2}\s+(?:is\s+)?(?:the\s+)?daughter\s+of\s+{a1}","mother_of"),
        ]
        results = []
        for pattern, rel_type in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                results.append((entity1, entity2, rel_type))
                break
        return results


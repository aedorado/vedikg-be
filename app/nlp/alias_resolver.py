"""
Alias resolution for Bhagavata Purana entities.
Maps aliases, titles, and descriptive names to canonical entity names.
"""

# Canonical names use proper Sanskrit diacritics.
# SPECIFIC aliases: directly identify a person → used for entity extraction.
# GENERIC aliases: philosophical/general titles → NOT used for extraction
#   (to avoid false positives when a concept is discussed, not a person).

ENTITY_ALIASES = {
    "Kṛṣṇa": {
        "aliases": [
            "Kṛṣṇa", "Krishna", "Krsna",
            "Lord Kṛṣṇa", "Lord Krishna", "Śrī Kṛṣṇa",
            "Hari", "Mukunda", "Govinda", "Madhava",
            "Devakī-nandana", "Devaki-nandana",
            "Yadu-nandana",
            # Titles meaning 'praised by excellent hymns'
            "Uttamaśloka", "Uttamaḥśloka", "Uttama-śloka",
            # "Absolute Truth" explicitly requested by user
            "Absolute Truth",
        ],
        "generic_aliases": [
            "Supreme Personality of Godhead", "Personality of Godhead",
            "Supreme Lord", "The Lord",
            "Bhagavān", "Bhagavan",
        ]
    },
    "Arjuna": {
        "aliases": [
            "Arjuna", "Arjun",
            "Dhanañjaya", "Dhananjaya", "Savyasācī",
            "Pārtha", "Partha",
            "Kuntī-putra",
        ]
    },
    "Vyāsadeva": {
        "aliases": [
            "Vyāsadeva", "Vyasadeva", "Vyāsa", "Vyasa",
            "Vedavyāsa", "Vedavyasa", "Veda-vyāsa", "Veda Vyasa",
            "Dvaipāyana", "Dvaipayana",
            "Kṛṣṇa-dvaipāyana", "Krishnadvaipyana",
            "Śrīla Vyāsadeva",
        ]
    },
    "Brahmā": {
        "aliases": [
            "Brahmā", "Brahma", "Brahma Deva",
            "Lord Brahmā", "Lord Brahma",
            "Hiraṇyagarbha", "Hiranyagarbha",
        ],
        "generic_aliases": [
            "Brahman", "Creator",
        ]
    },
    "Śiva": {
        "aliases": [
            "Śiva", "Shiva", "Śiva Deva",
            "Lord Śiva", "Lord Shiva",
            "Mahādeva", "Mahadev", "Rudra", "Maheśvara",
        ]
    },
    "Indra": {
        "aliases": [
            "Indra", "Lord Indra",
            "Maghavān", "Śakra", "Sakra",
        ],
        "generic_aliases": [
            "King of Heaven", "King of the demigods",
        ]
    },
    "Candra": {
        "aliases": [
            "Candra", "Chandra", "Candramā",
            "Soma", "Indu",
        ],
        "generic_aliases": [
            "Moon", "Moon-god",
        ]
    },
    "Sūrya": {
        "aliases": [
            "Sūrya", "Surya", "Ādityā", "Āditya", "Ravi",
        ],
        "generic_aliases": [
            "Sun", "Sun-god",
        ]
    },
    "Buddha": {
        "aliases": [
            "Buddha", "Gautama Buddha", "Siddhartha",
        ]
    },
    "Nārada": {
        "aliases": [
            "Nārada", "Narada",
            "Nārada Muni", "Narada Muni",
            "Devarṣi Nārada", "Devarshi",
            "Sage Nārada",
        ]
    },
    "Śukadeva Gosvāmī": {
        "aliases": [
            "Śukadeva Gosvāmī", "Sukadeva Gosvami",
            "Śukadeva", "Sukadeva",
            "Śrī Śukadeva Gosvāmī",
            "Śukadeva Gosvāmī", "Sukadev",
        ]
    },
    "Sūta Gosvāmī": {
        "aliases": [
            "Sūta Gosvāmī", "Suta Gosvami",
            "Sūta", "Suta",
            "Romaharṣaṇa", "Lomaharsana",
            "Śrī Sūta Gosvāmī",
        ]
    },
    "Śrīmad-Bhāgavatam": {
        "aliases": [
            "Śrīmad-Bhāgavatam", "Srimad-Bhagavatam",
            "Bhāgavatam", "Bhagavatam",
            "Śrīmad Bhāgavatam",
        ]
    },
    "Kuntī": {
        "aliases": [
            "Kuntī", "Kunti", "Pṛthā", "Pritha",
        ]
    },
    "Draupadī": {
        "aliases": [
            "Draupadī", "Draupadi",
            "Pāñcālī", "Panchali",
        ]
    },
    "Bhīma": {
        "aliases": [
            "Bhīma", "Bhima", "Bhīmasena",
        ]
    },
    "Yudhiṣṭhira": {
        "aliases": [
            "Yudhiṣṭhira", "Yudhishthira",
            "Dharmarāja", "Dharma-raja",
        ]
    },
    "Parīkṣit": {
        "aliases": [
            "Parīkṣit", "Parikshit",
            "King Parīkṣit", "Mahārāja Parīkṣit",
            "Mahārāja Parīkṣit",
        ]
    },
    "Hiraṇyakaśipu": {
        "aliases": [
            "Hiraṇyakaśipu", "Hiranyakashipu",
        ]
    },
    "Hiraṇyākṣa": {
        "aliases": [
            "Hiraṇyākṣa", "Hiranyaksha",
        ]
    },
    "Prahlāda": {
        "aliases": [
            "Prahlāda", "Prahlada", "Prahlāda Mahārāja",
        ]
    },
    "Devakī": {
        "aliases": [
            "Devakī", "Devaki",
        ]
    },
    "Vasudeva": {
        "aliases": [
            "Vasudeva", "Śrī Vasudeva",
        ]
    },
    "Kaṁsa": {
        "aliases": [
            "Kaṁsa", "Kamsa", "Kaṃsa",
            "King Kaṁsa",
        ]
    },
    "Rāvaṇa": {
        "aliases": [
            "Rāvaṇa", "Ravana",
            "Daśānana",
        ]
    },
    "Rāma": {
        "aliases": [
            "Rāma", "Rama",
            "Lord Rāma", "Śrī Rāma",
            "Rāmacandra", "Ramachandra",
        ]
    },
    "Bali": {
        "aliases": [
            "Bali", "Bali Mahārāja",
            "Mahārāja Bali", "Balī",
        ]
    },
    "Dhruva": {
        "aliases": [
            "Dhruva", "Dhruva Mahārāja",
            "Mahārāja Dhruva",
        ]
    },
    "Uttānapāda": {
        "aliases": [
            "Uttānapāda", "Uttanapada",
            "King Uttānapāda",
        ]
    },
    "Nṛsiṁhadeva": {
        "aliases": [
            "Nṛsiṁha", "Nrsimha",
            "Nṛsiṁhadeva", "Narasimha",
            "Lord Nṛsiṁha",
        ]
    },
    "Vāmana": {
        "aliases": [
            "Vāmana", "Vamana",
            "Lord Vāmana",
        ]
    },
    "Śaunaka": {
        "aliases": [
            "Śaunaka", "Saunaka",
            "Śaunaka Ṛṣi", "Saunaka Rishi",
        ]
    },
    "Maitreya": {
        "aliases": [
            "Maitreya", "Maitreya Muni",
        ]
    },
    "Balarāma": {
        "aliases": [
            "Balarāma", "Balarama", "Balarāmajī",
            "Baladeva", "Baladeva Prabhu",
            "Saṅkarṣaṇa", "Sankarsana",
            "Rohiṇī-suta", "Rohini-suta",
            "Lord Balarāma", "Lord Baladeva",
        ]
    },
    "Rohiṇī": {
        "aliases": [
            "Rohiṇī", "Rohini",
            "Rohiṇīdevī", "Rohinidevī",
            "Mother Rohiṇī",
        ]
    },
    "Subhadrā": {
        "aliases": [
            "Subhadrā", "Subhadra",
        ]
    },
    "Vidura": {
        "aliases": [
            "Vidura",
        ]
    },
    "Śrīla Prabhupāda": {
        "aliases": [
            "Prabhupāda", "Prabhupada",
            "Śrīla Prabhupāda", "Srila Prabhupada",
            "A.C. Bhaktivedanta Swami",
        ]
    },
    # SB 9.7 / Solar dynasty kings
    "Hariścandra": {
        "aliases": [
            "Hariścandra", "Hariscandra", "Mahārāja Hariścandra",
        ]
    },
    "Triśaṅku": {
        "aliases": [
            "Triśaṅku", "Trisanku", "Triśanku",
            "Satyavrata",  # same person — called Satyavrata before his transformation
        ]
    },
    "Rohita": {
        "aliases": ["Rohita", "Rohitāśva"]
    },
    "Naimiṣāraṇya": {
        "aliases": [
            "Naimiṣāraṇya", "Naimisaranya",
            "Naimiṣa", "Naimisa",
            "forest of Naimiṣāraṇya",
        ]
    },

    # ── Places / Cosmological locations ──────────────────────────────────────

    # Hellish planets — 28 listed in SB 5.26.7
    "Tāmisra": {"aliases": ["Tāmisra", "Tamisra"]},
    "Andhatāmisra": {"aliases": ["Andhatāmisra", "Andhatamisra"]},
    "Raurava": {"aliases": ["Raurava"]},
    "Mahāraurava": {"aliases": ["Mahāraurava", "Maharaurava"]},
    "Kumbhīpāka": {"aliases": ["Kumbhīpāka", "Kumbhipaka"]},
    "Kālasūtra": {"aliases": ["Kālasūtra", "Kalasutra"]},
    "Asipatravana": {"aliases": ["Asipatravana", "Asi-patravana", "Asipatra-vana"]},
    "Sūkaramukha": {"aliases": ["Sūkaramukha", "Sukaramukha"]},
    "Andhakūpa": {"aliases": ["Andhakūpa", "Andhakupa"]},
    "Kṛmibhojana": {"aliases": ["Kṛmibhojana", "Krmibhojana"]},
    "Sandaṁśa": {"aliases": ["Sandaṁśa", "Sandamsa"]},
    "Taptasūrmi": {"aliases": ["Taptasūrmi", "Taptasurmi"]},
    "Vajrakaṇṭaka-śālmalī": {"aliases": ["Vajrakaṇṭaka-śālmalī", "Vajrakantaka-salmali", "Vajrakaṇṭakaśālmalī"]},
    "Vaitaraṇī": {"aliases": ["Vaitaraṇī", "Vaitarani"]},
    "Pūyoda": {"aliases": ["Pūyoda", "Puyoda"]},
    "Prāṇarodha": {"aliases": ["Prāṇarodha", "Pranarodha"]},
    "Viśasana": {"aliases": ["Viśasana", "Visasana"]},
    "Lālābhakṣa": {"aliases": ["Lālābhakṣa", "Lalabhaksa"]},
    "Sārameyādana": {"aliases": ["Sārameyādana", "Saramey adana", "Saramey-adana"]},
    "Avīci": {"aliases": ["Avīci", "Avici", "Avīcimat", "Avicimat"]},
    "Ayaḥpāna": {"aliases": ["Ayaḥpāna", "Ayahpana"]},
    "Kṣārakardama": {"aliases": ["Kṣārakardama", "Ksarakardama"]},
    "Rakṣogaṇa-bhojana": {"aliases": ["Rakṣogaṇa-bhojana", "Raksogana-bhojana"]},
    "Śūlaprota": {"aliases": ["Śūlaprota", "Sulaprota"]},
    "Dandaśūka": {"aliases": ["Dandaśūka", "Dandasuka"]},
    "Avaṭa-nirodhana": {"aliases": ["Avaṭa-nirodhana", "Avata-nirodhana"]},
    "Paryāvartana": {"aliases": ["Paryāvartana", "Paryavartana"]},
    "Sūcīmukha": {"aliases": ["Sūcīmukha", "Sucimukha"]},

    # Upper planetary systems (lokas)
    "Bhūloka": {"aliases": ["Bhūloka", "Bhuloka", "Bhū-loka"]},
    "Bhuvarloka": {"aliases": ["Bhuvarloka", "Bhuvar-loka"]},
    "Svargaloka": {"aliases": ["Svargaloka", "Swargaloka", "Svarga-loka"]},
    "Maharloka": {"aliases": ["Maharloka", "Mahar-loka"]},
    "Janaloka": {"aliases": ["Janaloka", "Jana-loka"]},
    "Tapoloka": {"aliases": ["Tapoloka", "Tapo-loka"]},
    "Satyaloka": {"aliases": ["Satyaloka", "Satya-loka"]},
    "Vaikuṇṭha": {"aliases": ["Vaikuṇṭha", "Vaikuntha", "Vaikuṇṭhaloka", "Vaikunthaloka"]},
    "Pitṛloka": {"aliases": ["Pitṛloka", "Pitrloka", "Pitṛ-loka"]},

    # Lower planetary systems
    "Atala": {"aliases": ["Atala"]},
    "Vitala": {"aliases": ["Vitala"]},
    "Sutala": {"aliases": ["Sutala"]},
    "Talātala": {"aliases": ["Talātala", "Talatala"]},
    "Mahātala": {"aliases": ["Mahātala", "Mahatala"]},
    "Rasātala": {"aliases": ["Rasātala", "Rasatala"]},
    "Pātāla": {"aliases": ["Pātāla", "Patala"]},

    # Cosmological
    "Bhū-maṇḍala": {"aliases": ["Bhū-maṇḍala", "Bhūmaṇḍala", "Bhu-mandala", "Bhumandala"]},
    "Garbhodaka": {"aliases": ["Garbhodaka", "Garbhodaka Ocean"]},
    "Kailāsa": {"aliases": ["Kailāsa", "Kailasa", "Kailash", "Mount Kailāsa", "Mount Kailash"]},

    # Sacred/geographic places
    "Vṛndāvana": {"aliases": ["Vṛndāvana", "Vrindavana", "Vrindavan", "Vrindaban"]},
    "Mathurā": {"aliases": ["Mathurā", "Mathura"]},
    "Dvārakā": {"aliases": ["Dvārakā", "Dvaraka", "Dwarka"]},
    "Kurukṣetra": {"aliases": ["Kurukṣetra", "Kurukshetra"]},
    "Hastināpura": {"aliases": ["Hastināpura", "Hastinapura", "Hastinapur"]},
    "Indraprastha": {"aliases": ["Indraprastha"]},
    "Ayodhyā": {"aliases": ["Ayodhyā", "Ayodhya"]},
    "Laṅkā": {"aliases": ["Laṅkā", "Lanka"]},
    "Kiṣkindhā": {"aliases": ["Kiṣkindhā", "Kishkindha"]},
    "Prabhāsa": {"aliases": ["Prabhāsa", "Prabhasa"]},
    "Prayāga": {"aliases": ["Prayāga", "Prayaga"]},
    "Kāśī": {"aliases": ["Kāśī", "Kasi", "Vārāṇasī", "Varanasi"]},
    "Badarikāśrama": {"aliases": ["Badarikāśrama", "Badarikasrama", "Badarī", "Badari", "Badrinath"]},
    "Puṣkara": {"aliases": ["Puṣkara", "Pushkara"]},
    "Bharata-varṣa": {"aliases": ["Bharata-varṣa", "Bharatavarsa", "Bhārata-varṣa"]},
    "Jambūdvīpa": {"aliases": ["Jambūdvīpa", "Jambudvipa"]},

    # Rivers
    "Gaṅgā": {"aliases": ["Gaṅgā", "Ganga", "Ganges", "river Gaṅgā", "river Ganga"]},
    "Yamunā": {"aliases": ["Yamunā", "Yamuna", "Kālindī", "Kalindi"]},
    "Sarasvatī": {"aliases": ["Sarasvatī", "Sarasvati", "Saraswati", "river Sarasvatī"]},
    "Narmadā": {"aliases": ["Narmadā", "Narmada"]},
    "Godāvarī": {"aliases": ["Godāvarī", "Godavari"]},
    "Sindhu": {"aliases": ["Sindhu"]},
    "Kāverī": {"aliases": ["Kāverī", "Kaveri"]},
}

# Build reverse lookup: alias -> canonical name (ONLY SPECIFIC ALIASES)
ALIAS_TO_ENTITY = {}
for entity_name, entity_data in ENTITY_ALIASES.items():
    # Only add specific aliases, not generic ones
    for alias in entity_data.get("aliases", []):
        ALIAS_TO_ENTITY[alias.lower()] = entity_name

def get_aliases_for_entity(entity_name: str, include_generic: bool = False) -> list[str]:
    """
    Get aliases for a given canonical entity name.
    
    Args:
        entity_name: The canonical entity name
        include_generic: If True, include generic aliases (default: False for extraction)
        
    Returns:
        List of aliases for the entity
    """
    if entity_name not in ENTITY_ALIASES:
        return []
    
    aliases = ENTITY_ALIASES[entity_name].get("aliases", [])
    if include_generic:
        aliases = aliases + ENTITY_ALIASES[entity_name].get("generic_aliases", [])
    return aliases

def resolve_alias(text: str) -> tuple[str, bool]:
    """
    Resolve an alias or name to canonical entity name.
    Uses only SPECIFIC aliases for resolution.
    
    Args:
        text: Text to resolve (may be an alias)
        
    Returns:
        Tuple of (canonical_entity_name, is_known)
        - canonical_entity_name: The main entity name if found, else the original text
        - is_known: Whether this was a recognized alias/entity
    """
    import re as _re
    text_lower = text.strip().lower()
    
    # Direct lookup
    if text_lower in ALIAS_TO_ENTITY:
        return ALIAS_TO_ENTITY[text_lower], True
    
    # Whole-word phrase matching (for multi-word aliases like "Lord Kṛṣṇa").
    # Use \b word boundaries to prevent "hari" from matching inside "Hariścandra".
    for alias_key, entity_name in ALIAS_TO_ENTITY.items():
        if len(alias_key) <= 3:
            continue
        pattern = r'(?<!\w)' + _re.escape(alias_key) + r'(?!\w)'
        if _re.search(pattern, text_lower):
            return entity_name, True
    
    return text, False

def get_all_known_entities() -> list[str]:
    """Get list of all canonical entity names."""
    return list(ENTITY_ALIASES.keys())

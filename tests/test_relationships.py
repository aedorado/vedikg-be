"""
Comprehensive relationship-extraction tests derived from SB 9.7, 9.8, 9.9 translations.

Each test case specifies:
  - chapter / text number
  - the exact translation text (as provided by Śrīla Prabhupāda)
  - expected (parent, child) pairs regardless of how the extractor labels the direction

Run:
    cd backend && venv/bin/python tests/test_relationships.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.nlp.relationship_extractor import RelationshipExtractor

extractor = RelationshipExtractor()

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize(rels):
    """Convert (a, b, rel_type) tuples → set of canonical (parent, child) pairs."""
    result = set()
    for a, b, rel in rels:
        if rel in ('son_of', 'daughter_of'):
            result.add((b, a))   # (parent, child)
        elif rel in ('father_of', 'mother_of'):
            result.add((a, b))   # (parent, child)
        elif rel == 'spouse_of':
            result.add(('SPOUSE', frozenset([a, b])))
    return result


# ── Test cases ────────────────────────────────────────────────────────────────
# Format: {"ref": "SB X.Y.Z", "text": "...", "expected": [(parent, child), ...]}
# "expected" uses canonical names from alias_resolver where applicable.

TEST_CASES = [

    # ── Chapter 9.7 ──────────────────────────────────────────────────────────

    {
        "ref": "SB 9.7.1",
        "text": (
            "Śukadeva Gosvāmī said: The most prominent among the sons of Māndhātā "
            "was he who is celebrated as Ambarīṣa. Ambarīṣa was accepted as son by "
            "his grandfather Yuvanāśva. Ambarīṣa's son was Yauvanāśva, and "
            "Yauvanāśva's son was Hārīta. In Māndhātā's dynasty, Ambarīṣa, Hārīta "
            "and Yauvanāśva were very prominent."
        ),
        "expected": [
            ("Māndhātā",  "Ambarīṣa"),    # sons of Māndhātā … celebrated as Ambarīṣa
            ("Ambarīṣa",  "Yauvanāśva"),  # Ambarīṣa's son was Yauvanāśva
            ("Yauvanāśva", "Hārīta"),      # Yauvanāśva's son was Hārīta
        ],
    },

    {
        "ref": "SB 9.7.4",
        "text": (
            "The son of Purukutsa was Trasaddasyu, who was the father of Anaraṇya. "
            "Anaraṇya's son was Haryaśva, the father of Prāruṇa. "
            "Prāruṇa was the father of Tribandhana."
        ),
        "expected": [
            ("Purukutsa",   "Trasaddasyu"),
            ("Trasaddasyu", "Anaraṇya"),
            ("Anaraṇya",    "Haryaśva"),
            ("Haryaśva",    "Prāruṇa"),
            ("Prāruṇa",     "Tribandhana"),
        ],
    },

    {
        "ref": "SB 9.7.5-6",
        "text": (
            "The son of Tribandhana was Satyavrata, who is celebrated by the name "
            "Triśaṅku. Because he kidnapped the daughter of a brāhmaṇa when she was "
            "being married, his father cursed him to become a caṇḍāla, lower than a "
            "śūdra."
        ),
        "expected": [
            ("Tribandhana", "Triśaṅku"),  # Satyavrata alias = Triśaṅku
        ],
    },

    {
        "ref": "SB 9.7.7",
        "text": (
            "The son of Triśaṅku was Hariścandra. Because of Hariścandra there was a "
            "quarrel between Viśvāmitra and Vasiṣṭha, who for many years fought one "
            "another, having been transformed into birds."
        ),
        "expected": [
            ("Triśaṅku", "Hariścandra"),
        ],
    },

    {
        "ref": "SB 9.7.9",
        "text": (
            "O King Parīkṣit, Hariścandra begged Varuṇa, 'My lord, if a son is born "
            "to me, with that son I shall perform a sacrifice for your satisfaction.' "
            "When Hariścandra said this, Varuṇa replied, 'Let it be so.' Because of "
            "Varuṇa's benediction, Hariścandra begot a son named Rohita."
        ),
        "expected": [
            ("Hariścandra", "Rohita"),
        ],
    },

    # ── Chapter 9.8 ──────────────────────────────────────────────────────────

    {
        "ref": "SB 9.8.1",
        "text": (
            "Śukadeva Gosvāmī continued: The son of Rohita was Harita, and Harita's "
            "son was Campa, who constructed the town of Campāpurī. The son of Campa "
            "was Sudeva, and his son was Vijaya."
        ),
        "expected": [
            ("Rohita", "Harita"),
            ("Harita", "Campa"),
            ("Campa",  "Sudeva"),
            # ("Sudeva", "Vijaya"),  # "his son" — pronoun, skip
        ],
        "skip_reason": "Vijaya pronoun ref requires context",
    },

    {
        "ref": "SB 9.8.2",
        "text": (
            "The son of Vijaya was Bharuka, Bharuka's son was Vṛka, and Vṛka's son "
            "was Bāhuka. The enemies of King Bāhuka took away all his possessions, "
            "and therefore the King entered the order of vānaprastha and went to the "
            "forest with his wife."
        ),
        "expected": [
            ("Vijaya",  "Bharuka"),
            ("Bharuka", "Vṛka"),
            ("Vṛka",    "Bāhuka"),
        ],
    },

    {
        "ref": "SB 9.8.14",
        "text": (
            "Among the sons of Sagara Mahārāja was one named Asamañjasa, who was born "
            "from the King's second wife, Keśinī. The son of Asamañjasa was known as "
            "Aṁśumān, and he was always engaged in working for the good of Sagara "
            "Mahārāja, his grandfather."
        ),
        "expected": [
            ("Sagara",    "Asamañjasa"),
            ("Asamañjasa", "Aṁśumān"),
        ],
    },

    {
        "ref": "SB 9.8.41",
        "text": (
            "From Bālika came a son named Daśaratha, from Daśaratha came a son named "
            "Aiḍaviḍi, and from Aiḍaviḍi came King Viśvasaha. The son of King "
            "Viśvasaha was the famous Mahārāja Khaṭvāṅga."
        ),
        "expected": [
            ("Bālika",    "Daśaratha"),
            ("Daśaratha", "Aiḍaviḍi"),
            ("Aiḍaviḍi",  "Viśvasaha"),
            ("Viśvasaha",  "Khaṭvāṅga"),
        ],
    },

    # ── Chapter 9.9 ──────────────────────────────────────────────────────────

    {
        "ref": "SB 9.9.2",
        "text": (
            "Like Aṁśumān himself, Dilīpa, his son, was unable to bring the Ganges "
            "to this material world, and he also became a victim of death in due "
            "course of time. Then Dilīpa's son, Bhagīratha, performed very severe "
            "austerities to bring the Ganges to this material world."
        ),
        "expected": [
            # ("Aṁśumān", "Dilīpa"),  # "his son" pronoun — skip
            ("Dilīpa", "Bhagīratha"),  # Dilīpa's son, Bhagīratha
        ],
    },

    {
        "ref": "SB 9.9.16-17",
        "text": (
            "Bhagīratha had a son named Śruta, whose son was Nābha. This son was "
            "different from the Nābha previously described. Nābha had a son named "
            "Sindhudvīpa, from Sindhudvīpa came Ayutāyu, and from Ayutāyu came "
            "Ṛtūparṇa, who became a friend of Nalarāja. Ṛtūparṇa taught Nalarāja "
            "the art of gambling, and Nalarāja gave Ṛtūparṇa lessons in controlling "
            "and maintaining horses. The son of Ṛtūparṇa was Sarvakāma."
        ),
        "expected": [
            ("Bhagīratha",  "Śruta"),
            # ("Śruta",       "Nābha"),    # "whose son" pronoun — skip
            ("Nābha",       "Sindhudvīpa"),
            ("Sindhudvīpa", "Ayutāyu"),
            ("Ayutāyu",     "Ṛtūparṇa"),
            ("Ṛtūparṇa",    "Sarvakāma"),
        ],
    },

    {
        "ref": "SB 9.9.18",
        "text": (
            "Sarvakāma had a son named Sudāsa, whose son, known as Saudāsa, was the "
            "husband of Damayantī. Saudāsa is sometimes known as Mitrasaha or "
            "Kalmāṣapāda. Because of his own misdeed, Mitrasaha was sonless and was "
            "cursed by Vasiṣṭha to become a man-eater [Rākṣasa]."
        ),
        "expected": [
            ("Sarvakāma", "Sudāsa"),
            # ("Sudāsa", "Saudāsa"),  # "whose son" pronoun — skip
        ],
    },

    {
        "ref": "SB 9.9.40",
        "text": (
            "From Aśmaka, Bālika took birth. Because Bālika was surrounded by women "
            "and was therefore saved from the anger of Paraśurāma, he was known as "
            "Nārīkavaca. When Paraśurāma vanquished all the kṣatriyas, Bālika became "
            "the progenitor of more kṣatriyas. Therefore he was known as Mūlaka, the "
            "root of the kṣatriya dynasty."
        ),
        "expected": [
            ("Aśmaka", "Bālika"),
        ],
    },

    {
        "ref": "SB 9.9.41",
        "text": (
            "From Bālika came a son named Daśaratha, from Daśaratha came a son named "
            "Aiḍaviḍi, and from Aiḍaviḍi came King Viśvasaha. The son of King "
            "Viśvasaha was the famous Mahārāja Khaṭvāṅga."
        ),
        "expected": [
            ("Bālika",    "Daśaratha"),
            ("Daśaratha", "Aiḍaviḍi"),
            ("Aiḍaviḍi",  "Viśvasaha"),
            ("Viśvasaha",  "Khaṭvāṅga"),
        ],
    },
]

# ── Runner ────────────────────────────────────────────────────────────────────

def run_tests():
    total_expected = 0
    total_found = 0
    missed_cases = []

    print("=" * 70)
    print(f"{'REF':<20} {'EXPECTED':>8} {'FOUND':>6}  DETAIL")
    print("=" * 70)

    for tc in TEST_CASES:
        rels = extractor.extract_relationships(tc["text"])
        found_pairs = normalize(rels)

        expected = tc["expected"]
        tc_found = 0
        tc_missed = []

        for parent, child in expected:
            total_expected += 1
            # Check both (parent, child) and (child, parent, spouse-style)
            if (parent, child) in found_pairs:
                tc_found += 1
                total_found += 1
            else:
                tc_missed.append(f"  MISS: {parent} → {child}")
                missed_cases.append((tc["ref"], parent, child))

        status = "✓" if tc_found == len(expected) else f"{tc_found}/{len(expected)}"
        print(f"{tc['ref']:<20} {len(expected):>8} {tc_found:>6}  {status}")
        for m in tc_missed:
            print(m)

        if rels and tc_found < len(expected):
            extra = [(a, b, r) for a, b, r in rels]
            print(f"   extracted: {extra}")

    print("=" * 70)
    pct = 100 * total_found / total_expected if total_expected else 0
    print(f"TOTAL: {total_found}/{total_expected} = {pct:.0f}%")

    if missed_cases:
        print(f"\nMISSED ({len(missed_cases)}):")
        for ref, p, c in missed_cases:
            print(f"  [{ref}] {p} → {c}")

if __name__ == "__main__":
    run_tests()

"""
EPUB Parser Service for Chaitanya Bhagavata

Handles extraction of verses, translations, purports, and chapter summaries
from EPUB files.
"""

import zipfile
from pathlib import Path
from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Tuple
import re
from dataclasses import dataclass


@dataclass
class Verse:
    """Represents a single verse with all its components"""
    verse_num: int
    sanskrit_text: str
    transliteration: str
    translation: str
    purport: str
    chapter_num: int
    chapter_summary: Optional[str] = None


@dataclass
class Chapter:
    """Represents a chapter with metadata"""
    chapter_num: int
    khanda: str  # 'adi', 'madhya', 'antya'
    summary: Optional[str] = None
    verses: List[Verse] = None

    def __post_init__(self):
        if self.verses is None:
            self.verses = []


class EPUBParser:
    """Parser for Chaitanya Bhagavata EPUB files"""

    def __init__(self, epub_path: str):
        self.epub_path = Path(epub_path)
        if not self.epub_path.exists():
            raise FileNotFoundError(f"EPUB file not found: {epub_path}")

    def extract_all_verses(self) -> List[Dict]:
        """
        Extract all verses from the EPUB file.
        Properly maintains chapter state across HTML files, avoiding duplicate chapter headers.
        CB chapters appear as paragraph text like "Chapter One", "Chapter Two", etc.
        """
        verses = []
        current_chapter_num = 0
        current_chapter_title = None
        current_chapter_summary = None
        last_chapter_heading = None  # Track to avoid counting duplicates

        with zipfile.ZipFile(self.epub_path, "r") as zip_ref:
            html_files = self._get_html_files(zip_ref)

            for html_file in html_files:
                content = zip_ref.read(html_file).decode("utf-8")
                soup = BeautifulSoup(content, "html.parser")

                # Look for chapter headers in paragraphs (CB format)
                for para in soup.find_all("p"):
                    para_text = para.get_text().strip()
                    chapter_match = re.search(
                        r"^Chapter\s+([A-Za-z]+|[0-9]+)", para_text, re.IGNORECASE
                    )

                    if chapter_match and para_text != last_chapter_heading:
                        # New chapter (not a duplicate heading)
                        current_chapter_num += 1
                        last_chapter_heading = para_text

                        # Para immediately after "Chapter X" = chapter title
                        # (e.g. "Summary of Lord Caitanya's Pastimes")
                        title_para = para.find_next("p")
                        current_chapter_title = title_para.get_text().strip() if title_para else None

                        # The REAL chapter summary is the English prose paragraphs
                        # that follow the title, up to the first Sanskrit paragraph,
                        # a "Gauḍīya-bhāṣya" label, or "TEXT 1".
                        summary_parts = []
                        if title_para:
                            cur = title_para.find_next("p")
                            while cur:
                                t = cur.get_text().strip()
                                if not t:
                                    cur = cur.find_next("p")
                                    continue
                                # Stop at verse marker, Gaudiya-bhashya label, or Sanskrit
                                if (re.match(r"TEXT\s+\d", t) or
                                        t == "Gauḍīya-bhāṣya" or
                                        not self._is_english_text(t)):
                                    break
                                summary_parts.append(t)
                                cur = cur.find_next("p")

                        current_chapter_summary = "\n\n".join(summary_parts) if summary_parts else None

                # Extract verses from this file
                file_verses = self._extract_verses_from_paragraphs(
                    soup, current_chapter_num, current_chapter_title, current_chapter_summary
                )
                verses.extend(file_verses)

        return verses

    def _extract_verses_from_paragraphs(
        self, soup: BeautifulSoup, current_chapter_num: int,
        chapter_title: Optional[str] = None, chapter_summary: Optional[str] = None
    ) -> List[Dict]:
        """
        Extract verses from all paragraphs.
        Chapter state is already set by extract_all_verses(), so we just extract verses here.
        Do NOT re-detect chapter headers here to avoid double-incrementing.
        """
        verses = []
        chapter_num = current_chapter_num or 1
        local_title = chapter_title
        local_summary = chapter_summary

        for para in soup.find_all("p"):
            text = para.get_text().strip()
            if not text:
                continue

            # Look for TEXT marker (e.g., "TEXT 1", "TEXT 2-5")
            text_match = re.match(r"TEXT\s+([\d\-]+)", text)
            if text_match:
                verse_range = text_match.group(1)

                # For multi-verse blocks like "TEXT 2-5", use the first number
                if "-" in verse_range:
                    verse_num = int(verse_range.split("-")[0])
                else:
                    verse_num = int(verse_range)

                verse_dict = self._extract_verse_components(
                    para, chapter_num, verse_num, local_title, local_summary
                )
                if verse_dict:
                    verses.append(verse_dict)
                    # Only attach title/summary to the first verse per chapter
                    local_title = None
                    local_summary = None

        return verses

    def extract_metadata(self) -> Dict:
        """Extract book metadata from EPUB"""
        metadata = {
            "author": "Vṛndāvana dāsa Ṭhākura",
            "translator": "Bhūmipati Dāsa",
            "commentary_name": "Gauḍīya-bhāṣya",
            "commentary_author": "Bhaktisiddhānta Sarasvatī Gosvāmī Mahārāja",
        }

        with zipfile.ZipFile(self.epub_path, "r") as zip_ref:
            # Try to extract from OPF metadata
            opf_files = [f for f in zip_ref.namelist() if f.endswith(".opf")]
            if opf_files:
                opf_content = zip_ref.read(opf_files[0]).decode("utf-8")
                soup = BeautifulSoup(opf_content, "xml")

                # Extract title to determine khanda
                title_elem = soup.find("dc:title")
                if title_elem:
                    title = title_elem.get_text()
                    metadata["title"] = title
                    if "Adi" in title or "Ādi" in title:
                        metadata["khanda"] = "adi"
                    elif "Madhya" in title:
                        metadata["khanda"] = "madhya"
                    elif "Antya" in title:
                        metadata["khanda"] = "antya"

        return metadata

    def _get_html_files(self, zip_ref) -> List[str]:
        """Get ordered list of HTML content files"""
        html_files = [
            f
            for f in zip_ref.namelist()
            if f.endswith((".html", ".xhtml")) and "index" in f
        ]
        return sorted(html_files)

    def _extract_chapter_summary(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract chapter summary from HTML.
        Chapter summaries appear as paragraph text describing the chapter content.
        """
        # Look for "Chapter" heading followed by a summary paragraph
        for heading in soup.find_all(["h1", "h2", "h3"]):
            text = heading.get_text().strip()
            if "Chapter" in text:
                # Get the next paragraph(s) until we hit a verse
                summary_parts = []
                sibling = heading.find_next("p")

                while sibling:
                    sibling_text = sibling.get_text().strip()

                    # Stop if we hit verse marker
                    if "TEXT" in sibling_text or "VERSE" in sibling_text:
                        break

                    # Stop if we hit Sanskrit text (italicized)
                    if sibling.find("span", class_="italic"):
                        break

                    if sibling_text and len(sibling_text) > 20:
                        summary_parts.append(sibling_text)

                    sibling = sibling.find_next("p", recursive=False)

                if summary_parts:
                    return " ".join(summary_parts)

        return None

    def _extract_verses_from_html(
        self, soup: BeautifulSoup, chapter_num: int, chapter_summary: Optional[str] = None
    ) -> List[Dict]:
        """Extract all verses from a single HTML file"""
        verses = []
        verse_num = 1

        # Find all verse markers (e.g., "TEXT 55")
        for para in soup.find_all("p"):
            text = para.get_text().strip()

            # Look for verse marker
            if text.startswith("TEXT ") or text.startswith("VERSE "):
                # Extract verse number
                verse_num_match = re.search(r"(?:TEXT|VERSE)\s+(\d+)", text)
                if verse_num_match:
                    verse_num = int(verse_num_match.group(1))

                # Get next siblings for Sanskrit, transliteration, translation, purport
                verse_dict = self._extract_verse_components(
                    para, chapter_num, verse_num, chapter_summary
                )
                if verse_dict:
                    verses.append(verse_dict)

        return verses

    def _extract_verse_components(
        self, marker_para, chapter_num: int, verse_num: int,
        chapter_title: Optional[str] = None, chapter_summary: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Extract individual components of a verse for CB.
        Strategy: Collect all content until next TEXT marker, then parse backwards:
        - Last parts are purport (longest explanatory text)
        - English translation is in the middle
        - Sanskrit lines are at the start
        """
        components = {
            "verse_num": verse_num,
            "chapter_num": chapter_num,
            "chapter_title": chapter_title,
            "chapter_summary": chapter_summary,
            "sanskrit_text": "",
            "transliteration": "",
            "translation": "",
            "purport": "",
        }

        # Collect all content paragraphs until next TEXT marker
        content_paras = []
        current = marker_para.find_next("p")
        
        while current:
            # Replace <br> tags with \n before extracting text, so only actual
            # line breaks (not inline <em>/<strong> etc.) become newlines
            import copy as _copy
            para_copy = _copy.copy(current)
            for br in para_copy.find_all('br'):
                br.replace_with('\n')
            text = para_copy.get_text().strip()
            
            if not text:
                current = current.find_next("p")
                continue
            
            # Stop at next verse or chapter
            if (text.startswith("TEXT ") or text.startswith("VERSE ") or 
                text.startswith("Chapter ")):
                break
            
            content_paras.append(text)
            current = current.find_next("p")
        
        if not content_paras:
            return None
        
        # Now parse the collected paragraphs
        # Strategy: Find where English translation starts, split there
        translation_idx = None
        for i, para in enumerate(content_paras):
            if self._is_english_text(para):
                translation_idx = i
                break
        
        if translation_idx is None:
            # No English found, put all in Sanskrit - PRESERVE line breaks
            components["sanskrit_text"] = "\n".join(content_paras)
        else:
            # Sanskrit is everything before translation - PRESERVE line breaks
            if translation_idx > 0:
                components["sanskrit_text"] = "\n".join(content_paras[:translation_idx])
            
            # Translation is first English section (usually just one paragraph)
            components["translation"] = content_paras[translation_idx]
            
            # Purport is everything after translation - PRESERVE paragraph breaks with \n\n
            if translation_idx + 1 < len(content_paras):
                components["purport"] = "\n\n".join(content_paras[translation_idx + 1:])
        
        # Only return if we have Sanskrit
        if components["sanskrit_text"]:
            return components
        
        return None

    def _is_english_text(self, text: str) -> bool:
        """
        Detect if text is English rather than Sanskrit.
        Require actual English word patterns, not just low diacritics.
        """
        if not text or len(text) < 10:
            return False
        
        # English word patterns to look for (case-insensitive)
        english_indicators = [
            'the ', ' and ', ' is ', ' are ', ' or ', ' of ', ' to ', ' in ',
            ' a ', ' an ', ' that ', ' this ', ' from ', ' with ', ' for ',
            ' on ', ' at ', ' as ', ' by ', ' his ', ' her ', ' who ', ' whom',
            'offering', 'offer', 'obeisances', 'unto', 'brahmin', 'brāhmaṇ',
            'mercy', 'glor', 'worship', 'respect',
            'even ', 'any ', 'person ', 'when ', 'does ', 'know ', 'said'
        ]
        
        text_lower = text.lower()
        
        # Count how many English indicators are found
        english_count = 0
        for indicator in english_indicators:
            if indicator in text_lower:
                english_count += 1
        
        # If has multiple English indicators, it's definitely English
        if english_count >= 2:
            return True
        
        # If starts with uppercase letter and has at least ONE English indicator
        if text[0].isupper() and english_count >= 1:
            return True
        
        # If starts with common English word starters
        if any(text.lower().startswith(w) for w in ['i ', 'the ', 'this ', 'that ', 'all ', 'even ', 'any ', 'as ', 'in ', 'with ', 'by ']):
            return True
        
        # Only use ASCII percentage check if COMBINED with English word indicators
        # This prevents Sanskrit verses with mostly ASCII characters from being misidentified as English
        if english_count >= 1 and len(text) > 30:
            non_ascii_pct = sum(1 for c in text if ord(c) > 127) / len(text) * 100
            if non_ascii_pct < 8:
                return True
        
        # Default to Sanskrit
        return False

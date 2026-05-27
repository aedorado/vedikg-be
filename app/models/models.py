from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum, Float, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.db.base import Base


class Book(Base):
    __tablename__ = "books"

    id                  = Column(Integer, primary_key=True, index=True)
    code                = Column(String(10), unique=True, nullable=False)   # 'SB', 'CC', 'CB'
    title               = Column(String(255), nullable=False)
    url_prefix          = Column(String(255), nullable=True)
    author              = Column(String(255), nullable=True)
    translator          = Column(String(255), nullable=True)
    commentary_name     = Column(String(255), nullable=True)
    commentary_author   = Column(String(255), nullable=True)

    cantos = relationship("Canto", back_populates="book")


class Author(Base):
    __tablename__ = "authors"

    id   = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)

    purports = relationship("Purport", back_populates="author")


class Purport(Base):
    __tablename__ = "purports"

    id        = Column(Integer, primary_key=True, index=True)
    verse_id  = Column(Integer, ForeignKey("verses.id"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("authors.id"), nullable=False)
    body_html = Column(Text, nullable=True)
    body_text = Column(Text, nullable=True)
    language  = Column(String(5), default="en")

    verse  = relationship("Verse", back_populates="purports")
    author = relationship("Author", back_populates="purports")


class EntityType(str, enum.Enum):
    PERSON = "person"
    PLACE = "place"
    SAGE = "sage"
    DEMON = "demon"
    DEVA = "deva"
    RIVER = "river"
    MOUNTAIN = "mountain"
    KINGDOM = "kingdom"
    DYNASTY = "dynasty"
    CONCEPT = "concept"
    PASTIME = "pastime"


class RelationshipType(str, enum.Enum):
    FATHER_OF = "father_of"
    MOTHER_OF = "mother_of"
    SON_OF = "son_of"
    DAUGHTER_OF = "daughter_of"
    BROTHER_OF = "brother_of"
    SISTER_OF = "sister_of"
    SPOUSE_OF = "spouse_of"
    DISCIPLE_OF = "disciple_of"
    FRIEND_OF = "friend_of"
    ENEMY_OF = "enemy_of"
    INCARNATION_OF = "incarnation_of"
    EXPANSION_OF = "expansion_of"
    DEVOTEE_OF = "devotee_of"
    RESIDENT_OF = "resident_of"
    INTERACTED_WITH = "interacted_with"


class MentionLocation(str, enum.Enum):
    VERSE_TEXT = "verse_text"
    PURPORT_TEXT = "purport_text"
    BOTH = "both"


class ScrapeStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ERROR = "error"


class Canto(Base):
    __tablename__ = "cantos"
    __table_args__ = (UniqueConstraint("book_id", "number"),)

    id            = Column(Integer, primary_key=True, index=True)
    number        = Column(Integer, nullable=False)
    title         = Column(String(255))
    slug          = Column(String(255), unique=True)
    summary       = Column(Text, nullable=True)
    book_id       = Column(Integer, ForeignKey("books.id"), nullable=True)
    section_label = Column(String(100), nullable=True)  # "Canto 1" / "Ādi-līlā" etc.

    book     = relationship("Book", back_populates="cantos")
    chapters = relationship("Chapter", back_populates="canto")


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, index=True)
    canto_id = Column(Integer, ForeignKey("cantos.id"))
    chapter_number = Column(Integer)
    title = Column(String(255))
    slug = Column(String(255))
    summary = Column(Text, nullable=True)
    source_url = Column(String(500), nullable=True)

    canto = relationship("Canto", back_populates="chapters")
    verses = relationship("Verse", back_populates="chapter")


class Verse(Base):
    __tablename__ = "verses"

    id = Column(Integer, primary_key=True, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"))
    verse_number = Column(Integer)
    full_reference = Column(String(50), index=True)
    source_url = Column(String(500), nullable=True)

    devanagari = Column(Text, nullable=True)
    transliteration = Column(Text, nullable=True)
    translation = Column(Text)
    synonyms_raw = Column(Text, nullable=True)
    purport_html = Column(Text, nullable=True)
    purport_text = Column(Text, nullable=True)

    previous_verse_id = Column(Integer, ForeignKey("verses.id"), nullable=True)
    next_verse_id = Column(Integer, ForeignKey("verses.id"), nullable=True)
    chanda      = Column(String(255), nullable=True)
    chanda_json = Column(Text, nullable=True)
    language    = Column(String(5), default="sa")  # 'sa' | 'bn' | 'en'
    book_id     = Column(Integer, ForeignKey("books.id"), nullable=True, index=True)

    scraped_at   = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
    ai_processed = Column(Integer, default=0)

    chapter  = relationship("Chapter", back_populates="verses")
    entities = relationship("VerseEntity", back_populates="verse")
    purports = relationship("Purport", back_populates="verse", order_by="Purport.id")


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, index=True)
    normalized_name = Column(String(255), index=True)
    entity_type = Column(String(50))
    description = Column(Text, nullable=True)
    aliases_json = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    first_appearance_verse_id = Column(Integer, ForeignKey("verses.id"), nullable=True)

    verse_entities = relationship("VerseEntity", back_populates="entity")


class VerseEntity(Base):
    __tablename__ = "verse_entities"

    id = Column(Integer, primary_key=True, index=True)
    verse_id = Column(Integer, ForeignKey("verses.id"), index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), index=True)
    mention_location = Column(String(50))
    mention_text = Column(Text, nullable=True)
    context_summary = Column(Text, nullable=True)
    confidence_score = Column(Float, default=1.0)

    verse = relationship("Verse", back_populates="entities")
    entity = relationship("Entity", back_populates="verse_entities")


class Relationship(Base):
    __tablename__ = "relationships"

    id = Column(Integer, primary_key=True, index=True)
    source_entity_id = Column(Integer, ForeignKey("entities.id"), index=True)
    target_entity_id = Column(Integer, ForeignKey("entities.id"), index=True)
    relationship_type = Column(String(50), index=True)
    source_verse_id = Column(Integer, ForeignKey("verses.id"), nullable=True)
    confidence_score = Column(Float, default=1.0)


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id = Column(Integer, primary_key=True, index=True)
    canto_number = Column(Integer)
    chapter_number = Column(Integer)
    status = Column(String(50), default="pending")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    last_processed_verse = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)


class VerseConcept(Base):
    __tablename__ = "ai_verse_concepts"

    id = Column(Integer, primary_key=True, index=True)
    verse_id = Column(Integer, ForeignKey("verses.id"), index=True)
    concept = Column(String(255), index=True)  # e.g., "bhakti", "karma", "maya", "humility", "tolerance", "cleanliness"

    verse = relationship("Verse", foreign_keys=[verse_id])

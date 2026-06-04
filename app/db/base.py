from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os
from pathlib import Path
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

# Load .env from project root, not current directory
project_root = Path(__file__).parent.parent.parent
env_file = project_root / ".env"
load_dotenv(env_file)

# Use PostgreSQL - required, no SQLite fallback
DATABASE_URL = os.getenv("POSTGRES_URL")
if not DATABASE_URL:
    raise ValueError(
        f"POSTGRES_URL not found in {env_file}. "
        "Please ensure your .env file contains: POSTGRES_URL=postgresql://..."
    )

# Convert postgresql:// to psycopg:// for psycopg3
DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# Log database connection info
logger.info(f"📡 Using database: {DATABASE_URL[:80]}...")

engine = create_engine(
    DATABASE_URL,
    connect_args={"prepare_threshold": None},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

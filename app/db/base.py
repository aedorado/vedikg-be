from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

# Use PostgreSQL if available, else fall back to SQLite
DATABASE_URL = os.getenv("POSTGRES_URL")
if DATABASE_URL:
    # Convert postgresql:// to psycopg:// for psycopg3
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
# else:
    # _DB_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # DATABASE_URL = f"sqlite:///{os.path.join(_DB_DIR, 'bhagavatam.db')}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

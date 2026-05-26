"""Initialize database schema only. Entities and relationships are built from scraping."""
from app.db.base import engine, Base
import app.models.models  # noqa: F401 - must import to register all ORM models


def init_db():
    Base.metadata.create_all(bind=engine)
    print("✓ Database schema initialized")


if __name__ == "__main__":
    init_db()

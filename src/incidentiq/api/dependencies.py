from collections.abc import Generator
from sqlalchemy.orm import Session
from incidentiq.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Give each request a database session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

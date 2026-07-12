"""Configuração de banco de dados via SQLAlchemy."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """Dependency: fornece sessão de banco para requisição."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

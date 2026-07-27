from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def normalize_database_url(url: str) -> str:
    # Compatibilidad con URLs antiguas que comienzan con postgres://
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def create_database(database_url: str):
    engine = create_engine(
        normalize_database_url(database_url),
        pool_pre_ping=True,
    )
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, SessionLocal

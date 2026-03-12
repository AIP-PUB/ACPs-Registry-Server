from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlmodel import SQLModel

from app.core.config import settings

# Create synchronous engine for non-async operations
sync_engine = create_engine(
    settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql"), future=True
)

# Create async engine for async operations
async_engine = create_async_engine(settings.DATABASE_URL)

# Create session factories
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
AsyncSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=async_engine
)

Base = declarative_base()


def get_db():
    """
    Dependency function that yields db sessions
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db():
    """
    Dependency function that yields async db sessions
    """
    async with AsyncSessionLocal() as db:
        yield db


def create_db_and_tables():
    """
    Initialize database tables on startup (synchronous)
    """
    SQLModel.metadata.create_all(sync_engine)


async def create_db_and_tables_async():
    """
    Initialize database tables on startup (async)
    """
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

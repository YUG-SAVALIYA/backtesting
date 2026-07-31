import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Hardcode the DB URL to point to the local Tradesignal Postgres
DEFAULT_DB_URL = "postgresql://postgres:postgres@localhost:5432/trade_signal"
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DB_URL)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============================================================
# GREEN App — Database Setup
# SQLite + SQLAlchemy ORM configuration.
# Creates the engine, session factory, and declarative base.
# ============================================================

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL

# ---- Engine -------------------------------------------------
# connect_args={"check_same_thread": False} is required for
# SQLite because FastAPI uses multiple threads.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False  # Set True to log SQL queries for debugging
)

# ---- Session Factory ----------------------------------------
# Each request gets its own session (opened/closed in dependency).
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# ---- Declarative Base ----------------------------------------
# All ORM models inherit from this base class.
Base = declarative_base()


# ---- Dependency ---------------------------------------------
def get_db():
    """
    FastAPI dependency: yields a DB session per request,
    then closes it when the request is done.

    Usage in a route:
        @router.get("/something")
        def my_route(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

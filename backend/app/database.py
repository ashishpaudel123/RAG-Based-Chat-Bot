from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        db_path = url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_conn, _):  # enforce ON DELETE CASCADE in SQLite
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> list[str]:
    """Create tables and add any columns that are missing from an older database.

    Returns the "table.column" names that were added, so callers can run
    follow-up work (e.g. refreshing vector metadata) after an upgrade.
    """
    from app import models  # noqa: F401  (register models)

    Base.metadata.create_all(bind=engine)
    return _add_missing_columns()


def _add_missing_columns(bind=None) -> list[str]:
    """Minimal forward-only migration: ALTER TABLE ... ADD COLUMN for new nullable
    or server-defaulted columns. Good enough for this project's additive schema
    changes without a migration framework."""
    from sqlalchemy import inspect, text

    bind = bind or engine
    inspector = inspect(bind)
    added: list[str] = []
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(dialect=bind.dialect)
                ddl = f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}'
                if column.server_default is not None:
                    default = column.server_default.arg
                    default = default.text if hasattr(default, "text") else str(default)
                    ddl += f" DEFAULT '{default}'" if not default.isdigit() else f" DEFAULT {default}"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
    return added

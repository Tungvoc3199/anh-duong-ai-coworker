from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.db.session import create_db_engine, session_scope


class ProbeBase(DeclarativeBase):
    pass


class ProbeRow(ProbeBase):
    __tablename__ = "probe_rows"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)


def test_sqlite_engine_enables_required_pragmas(tmp_path) -> None:
    engine = create_db_engine(f"sqlite+pysqlite:///{tmp_path}/test.db")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
        assert connection.execute(text("PRAGMA synchronous")).scalar_one() == 1
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000


def test_wal_supports_short_concurrent_writes(tmp_path) -> None:
    engine = create_db_engine(f"sqlite+pysqlite:///{tmp_path}/concurrent.db")
    ProbeBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def insert_rows(worker: int) -> None:
        for index in range(5):
            with session_scope(factory) as session:
                session.add(ProbeRow(id=f"{worker}-{index}-{uuid4().hex}"))

    with ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(insert_rows, range(5)))

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM probe_rows")).scalar_one() == 25

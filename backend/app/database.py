from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings
from .services.secret_service import ENCRYPTED_PREFIX, get_secret_service


settings = get_settings()
db_path = Path(settings.sqlite_path)
db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{db_path.resolve()}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
    except Exception:
        pass
    finally:
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def ensure_sqlite_schema() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    _ensure_dispatch_tables(table_names)
    if "friends" not in table_names:
        return

    friend_columns = {column["name"] for column in inspector.get_columns("friends")}
    statements: list[str] = []

    if "schedule_window" not in friend_columns:
        statements.append(
            "ALTER TABLE friends ADD COLUMN schedule_window VARCHAR(20) DEFAULT '06:00-08:00'"
        )
    if "frequency_days" not in friend_columns:
        statements.append("ALTER TABLE friends ADD COLUMN frequency_days INTEGER DEFAULT 1")
    if "cooldown_minutes" not in friend_columns:
        statements.append("ALTER TABLE friends ADD COLUMN cooldown_minutes INTEGER DEFAULT 0")
    if "retry_limit" not in friend_columns:
        statements.append("ALTER TABLE friends ADD COLUMN retry_limit INTEGER DEFAULT 2")
    if "retry_cooldown_minutes" not in friend_columns:
        statements.append("ALTER TABLE friends ADD COLUMN retry_cooldown_minutes INTEGER DEFAULT 30")
    if "consecutive_failures" not in friend_columns:
        statements.append("ALTER TABLE friends ADD COLUMN consecutive_failures INTEGER DEFAULT 0")
    if "next_run_at" not in friend_columns:
        statements.append("ALTER TABLE friends ADD COLUMN next_run_at DATETIME")
    if "last_run_at" not in friend_columns:
        statements.append("ALTER TABLE friends ADD COLUMN last_run_at DATETIME")

    if "accounts" in table_names:
        account_columns = {column["name"] for column in inspector.get_columns("accounts")}
        if "cookie_expires_at" not in account_columns:
            statements.append("ALTER TABLE accounts ADD COLUMN cookie_expires_at DATETIME")
        if "cookie_updated_at" not in account_columns:
            statements.append("ALTER TABLE accounts ADD COLUMN cookie_updated_at DATETIME")

    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
            connection.execute(
                text(
                    "UPDATE friends "
                    "SET schedule_window = '06:00-08:00', "
                    "frequency_days = COALESCE(frequency_days, 1), "
                    "cooldown_minutes = COALESCE(cooldown_minutes, 0), "
                    "retry_limit = COALESCE(retry_limit, 2), "
                    "retry_cooldown_minutes = COALESCE(retry_cooldown_minutes, 30), "
                    "consecutive_failures = COALESCE(consecutive_failures, 0) "
                    "WHERE schedule_window IS NULL OR schedule_window = '' "
                    "OR frequency_days IS NULL "
                    "OR cooldown_minutes IS NULL "
                    "OR retry_limit IS NULL "
                    "OR retry_cooldown_minutes IS NULL "
                    "OR consecutive_failures IS NULL"
                )
            )

    if "run_logs" not in table_names or "app_settings" not in table_names:
        _finish_migrations()
        return

    with engine.begin() as connection:
        migrated = connection.execute(
            text("SELECT value FROM app_settings WHERE key = 'run_logs_timezone_migrated_v1'")
        ).scalar_one_or_none()
        if migrated == "done":
            _finish_migrations()
            return

        connection.execute(
            text(
                "UPDATE run_logs "
                "SET created_at = datetime(created_at, '+8 hours') "
                "WHERE created_at IS NOT NULL"
            )
        )
        connection.execute(
            text(
                "INSERT INTO app_settings(key, value) VALUES ('run_logs_timezone_migrated_v1', 'done') "
                "ON CONFLICT(key) DO UPDATE SET value = 'done'"
            )
        )
    _finish_migrations()


def _finish_migrations() -> None:
    _encrypt_plaintext_cookies()
    _migrate_utc_timestamps_to_beijing()


def _encrypt_plaintext_cookies() -> None:
    inspector = inspect(engine)
    if "accounts" not in inspector.get_table_names():
        return
    account_columns = {column["name"] for column in inspector.get_columns("accounts")}
    if "cookie_text" not in account_columns:
        return

    secret_service = get_secret_service()
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT id, cookie_text FROM accounts")).mappings().all()
        for row in rows:
            cookie_text = row["cookie_text"] or ""
            if not cookie_text or cookie_text.startswith(ENCRYPTED_PREFIX):
                continue
            connection.execute(
                text("UPDATE accounts SET cookie_text = :cookie_text WHERE id = :id"),
                {"id": row["id"], "cookie_text": secret_service.encrypt(cookie_text)},
            )


TIMESTAMPS_UNIFIED_KEY = "timestamps_unified_v1"


def _migrate_utc_timestamps_to_beijing() -> None:
    """把历史 UTC naive 时间戳迁移为北京时间 naive。

    项目统一约定：数据库所有时间字段为北京时间（UTC+8）naive。
    本次迁移只影响 accounts / friends / messages 的 created_at / updated_at。
    """
    inspector = inspect(engine)
    if "app_settings" not in inspector.get_table_names():
        return

    with engine.begin() as connection:
        migrated = connection.execute(
            text("SELECT value FROM app_settings WHERE key = :key"),
            {"key": TIMESTAMPS_UNIFIED_KEY},
        ).scalar_one_or_none()
        if migrated == "done":
            return

        for table in ("accounts", "friends", "messages"):
            if table not in inspector.get_table_names():
                continue
            columns = {column["name"] for column in inspector.get_columns(table)}
            for column in ("created_at", "updated_at"):
                if column not in columns:
                    continue
                connection.execute(
                    text(
                        f"UPDATE {table} SET {column} = datetime({column}, '+8 hours') "
                        f"WHERE {column} IS NOT NULL"
                    )
                )

        connection.execute(
            text(
                "INSERT INTO app_settings(key, value) VALUES (:key, 'done') "
                "ON CONFLICT(key) DO UPDATE SET value = 'done'"
            ),
            {"key": TIMESTAMPS_UNIFIED_KEY},
        )


def _ensure_dispatch_tables(table_names: list[str]) -> None:
    statements: list[str] = []
    if "dispatch_tasks" not in table_names:
        statements.extend(
            [
                """
                CREATE TABLE dispatch_tasks (
                    id INTEGER NOT NULL PRIMARY KEY,
                    friend_id INTEGER NOT NULL,
                    source VARCHAR(6) NOT NULL,
                    status VARCHAR(13) NOT NULL,
                    idempotency_key VARCHAR(160) NOT NULL UNIQUE,
                    scheduled_for DATETIME,
                    started_at DATETIME,
                    finished_at DATETIME,
                    summary VARCHAR(255) DEFAULT '',
                    details TEXT DEFAULT '',
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(friend_id) REFERENCES friends (id)
                )
                """,
                "CREATE INDEX ix_dispatch_tasks_friend_id ON dispatch_tasks(friend_id)",
                "CREATE INDEX ix_dispatch_tasks_status ON dispatch_tasks(status)",
                "CREATE INDEX ix_dispatch_tasks_scheduled_for ON dispatch_tasks(scheduled_for)",
                "CREATE UNIQUE INDEX ix_dispatch_tasks_idempotency_key ON dispatch_tasks(idempotency_key)",
            ]
        )
    if "dispatch_locks" not in table_names:
        statements.extend(
            [
                """
                CREATE TABLE dispatch_locks (
                    name VARCHAR(80) NOT NULL PRIMARY KEY,
                    owner VARCHAR(120) DEFAULT '',
                    acquired_at DATETIME NOT NULL,
                    expires_at DATETIME NOT NULL
                )
                """,
                "CREATE INDEX ix_dispatch_locks_expires_at ON dispatch_locks(expires_at)",
            ]
        )

    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from pathlib import Path
import os
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "scheduler.db"

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    hashtags TEXT DEFAULT '',
    platform TEXT NOT NULL,
    content_format TEXT NOT NULL DEFAULT 'Feed Post',
    rss_item_id INTEGER,
    source_type TEXT NOT NULL DEFAULT 'Regular',
    scheduled_at TEXT,
    status TEXT NOT NULL DEFAULT 'Draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER,
    level TEXT NOT NULL DEFAULT 'INFO',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS media_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    public_url TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rss_feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    target_platforms TEXT NOT NULL,
    default_hashtags TEXT DEFAULT '',
    copy_template TEXT DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'Regular',
    is_active INTEGER NOT NULL DEFAULT 1,
    last_checked_at TEXT,
    last_check_status TEXT NOT NULL DEFAULT 'Never checked',
    last_check_message TEXT DEFAULT '',
    last_created_count INTEGER NOT NULL DEFAULT 0,
    last_skipped_count INTEGER NOT NULL DEFAULT 0,
    last_error_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rss_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id INTEGER NOT NULL,
    item_guid TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    image_url TEXT DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'Regular',
    post_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(feed_id, item_guid),
    FOREIGN KEY (feed_id) REFERENCES rss_feeds(id) ON DELETE CASCADE,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS post_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    scheduled_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Scheduled',
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS social_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL UNIQUE,
    account_label TEXT DEFAULT '',
    account_handle TEXT DEFAULT '',
    auth_type TEXT NOT NULL DEFAULT 'api_keys',
    encrypted_credentials TEXT NOT NULL,
    connection_status TEXT NOT NULL DEFAULT 'Needs verification',
    last_verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    hashtags TEXT DEFAULT '',
    platform TEXT NOT NULL,
    content_format TEXT NOT NULL DEFAULT 'Feed Post',
    rss_item_id INTEGER,
    source_type TEXT NOT NULL DEFAULT 'Regular',
    scheduled_at TEXT,
    status TEXT NOT NULL DEFAULT 'Draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS logs (
    id SERIAL PRIMARY KEY,
    post_id INTEGER,
    level TEXT NOT NULL DEFAULT 'INFO',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS media_assets (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    public_url TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rss_feeds (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    target_platforms TEXT NOT NULL,
    default_hashtags TEXT DEFAULT '',
    copy_template TEXT DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'Regular',
    is_active INTEGER NOT NULL DEFAULT 1,
    last_checked_at TEXT,
    last_check_status TEXT NOT NULL DEFAULT 'Never checked',
    last_check_message TEXT DEFAULT '',
    last_created_count INTEGER NOT NULL DEFAULT 0,
    last_skipped_count INTEGER NOT NULL DEFAULT 0,
    last_error_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rss_items (
    id SERIAL PRIMARY KEY,
    feed_id INTEGER NOT NULL,
    item_guid TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    image_url TEXT DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'Regular',
    post_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(feed_id, item_guid),
    FOREIGN KEY (feed_id) REFERENCES rss_feeds(id) ON DELETE CASCADE,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS post_schedules (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL,
    scheduled_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Scheduled',
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS social_accounts (
    id SERIAL PRIMARY KEY,
    platform TEXT NOT NULL UNIQUE,
    account_label TEXT DEFAULT '',
    account_handle TEXT DEFAULT '',
    auth_type TEXT NOT NULL DEFAULT 'api_keys',
    encrypted_credentials TEXT NOT NULL,
    connection_status TEXT NOT NULL DEFAULT 'Needs verification',
    last_verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class DatabaseConnection:
    def __init__(self, raw_connection, dialect):
        self.raw_connection = raw_connection
        self.dialect = dialect

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.raw_connection.commit()
        else:
            self.raw_connection.rollback()
        self.raw_connection.close()

    def execute(self, query, params=()):
        if self.dialect == "postgres":
            query = _translate_placeholders(query)
        return self.raw_connection.execute(query, params)

    def executescript(self, script):
        if self.dialect == "sqlite":
            return self.raw_connection.executescript(script)
        for statement in _split_sql_script(script):
            self.execute(statement)
        return None


def get_connection(db_path=None):
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return _postgres_connection(database_url)
    return _sqlite_connection(db_path or DEFAULT_DB_PATH)


def insert_and_get_id(conn, query, params=()):
    if conn.dialect == "postgres":
        cursor = conn.execute(f"{query.strip()} RETURNING id", params)
        return cursor.fetchone()["id"]
    cursor = conn.execute(query, params)
    return cursor.lastrowid


def init_db(db_path=None):
    with get_connection(db_path) as conn:
        conn.executescript(POSTGRES_SCHEMA if conn.dialect == "postgres" else SQLITE_SCHEMA)
        _ensure_column(conn, "posts", "content_format", "TEXT NOT NULL DEFAULT 'Feed Post'")
        _ensure_column(conn, "posts", "rss_item_id", "INTEGER")
        _ensure_column(conn, "posts", "source_type", "TEXT NOT NULL DEFAULT 'Regular'")
        _ensure_column(conn, "media_assets", "public_url", "TEXT DEFAULT ''")
        _ensure_column(conn, "rss_feeds", "content_type", "TEXT NOT NULL DEFAULT 'Regular'")
        _ensure_column(conn, "rss_feeds", "copy_template", "TEXT DEFAULT ''")
        _ensure_column(conn, "rss_feeds", "last_check_status", "TEXT NOT NULL DEFAULT 'Never checked'")
        _ensure_column(conn, "rss_feeds", "last_check_message", "TEXT DEFAULT ''")
        _ensure_column(conn, "rss_feeds", "last_created_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "rss_feeds", "last_skipped_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "rss_feeds", "last_error_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "rss_items", "content_type", "TEXT NOT NULL DEFAULT 'Regular'")
        _ensure_column(conn, "rss_items", "image_url", "TEXT DEFAULT ''")
        _ensure_column(conn, "social_accounts", "account_label", "TEXT DEFAULT ''")
        _ensure_column(conn, "social_accounts", "account_handle", "TEXT DEFAULT ''")
        _ensure_column(conn, "social_accounts", "auth_type", "TEXT NOT NULL DEFAULT 'api_keys'")
        _ensure_column(conn, "social_accounts", "encrypted_credentials", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "social_accounts", "connection_status", "TEXT NOT NULL DEFAULT 'Needs verification'")
        _ensure_column(conn, "social_accounts", "last_verified_at", "TEXT")


def _ensure_column(conn, table_name, column_name, column_definition):
    if conn.dialect == "postgres":
        columns = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ?
            """,
            (table_name,),
        ).fetchall()
    else:
        columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()

    if column_name not in {column["column_name"] if conn.dialect == "postgres" else column["name"] for column in columns}:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def _sqlite_connection(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    raw_connection = sqlite3.connect(db_path)
    raw_connection.row_factory = sqlite3.Row
    raw_connection.execute("PRAGMA foreign_keys = ON")
    return DatabaseConnection(raw_connection, "sqlite")


def _postgres_connection(database_url):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Install psycopg to use DATABASE_URL/Postgres.") from exc

    raw_connection = psycopg.connect(database_url, row_factory=dict_row)
    return DatabaseConnection(raw_connection, "postgres")


def _translate_placeholders(query):
    return query.replace("?", "%s").replace("CURRENT_TIMESTAMP", "(CURRENT_TIMESTAMP::TEXT)")


def _split_sql_script(script):
    return [statement.strip() for statement in script.split(";") if statement.strip()]

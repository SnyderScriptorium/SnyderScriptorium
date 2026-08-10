import os
import sqlite3
from contextlib import contextmanager


DATABASE = os.path.join(os.path.abspath(os.path.dirname(__file__)), "scriptorium.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


class PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor
        self._lastrowid = None

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)


class PostgresConnection:
    """Small compatibility layer so the existing app can use PostgreSQL."""

    def __init__(self, connection):
        self._connection = connection

    def _translate(self, sql):
        return sql.replace("?", "%s")

    def execute(self, sql, params=()):
        normalized = sql.strip()

        if normalized.upper().startswith("PRAGMA TABLE_INFO("):
            table = normalized[normalized.find("(") + 1:normalized.rfind(")")].strip().strip('"')
            sql = "SELECT column_name AS name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position"
            cursor = self._connection.cursor()
            cursor.execute(sql, (table,))
            return PostgresCursor(cursor)

        sql = self._translate(sql)
        upper = normalized.upper()
        wants_id = (
            upper.startswith("INSERT INTO")
            and any(f"INSERT INTO {table}" in upper for table in (
                "DRAFTS", "PUBLISHED_POSTS", "MANUSCRIPTS", "MANUSCRIPT_BOOKS",
                "MANUSCRIPT_CHAPTERS", "MEMBERS", "SUBSCRIPTIONS"
            ))
            and "RETURNING" not in upper
        )
        if wants_id:
            sql = sql.rstrip().rstrip(";") + " RETURNING id"

        cursor = self._connection.cursor()
        cursor.execute(sql, params)
        result = PostgresCursor(cursor)
        if wants_id:
            row = cursor.fetchone()
            result._lastrowid = row["id"] if row else None
        return result

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def using_postgres():
    return bool(DATABASE_URL)


def get_db():
    if not using_postgres():
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    conn.execute("SET TIME ZONE 'UTC'")
    return PostgresConnection(conn)


def postgres_init_db(conn):
    statements = [
        """
        CREATE TABLE IF NOT EXISTS drafts (
            id BIGSERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            date_created TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS published_posts (
            id BIGSERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            category_name TEXT NOT NULL,
            content TEXT NOT NULL,
            date_published TEXT NOT NULL,
            access_level TEXT NOT NULL DEFAULT 'public'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS manuscripts (
            id BIGSERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            date_created TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS manuscript_books (
            id BIGSERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            date_created TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            access_level TEXT NOT NULL DEFAULT 'members'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS manuscript_chapters (
            id BIGSERIAL PRIMARY KEY,
            book_id BIGINT NOT NULL REFERENCES manuscript_books(id) ON DELETE CASCADE,
            chapter_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            date_created TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            published INTEGER NOT NULL DEFAULT 0,
            UNIQUE(book_id, chapter_number)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS members (
            id BIGSERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            subscription_status TEXT NOT NULL DEFAULT 'inactive',
            date_created TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            id BIGSERIAL PRIMARY KEY,
            member_id BIGINT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            provider TEXT,
            subscription_id TEXT,
            status TEXT NOT NULL DEFAULT 'inactive',
            date_started TEXT,
            date_ends TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS site_content (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS page_views (
            id BIGSERIAL PRIMARY KEY,
            path TEXT NOT NULL,
            page_type TEXT NOT NULL DEFAULT 'page',
            content_id BIGINT,
            category TEXT,
            viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]
    for statement in statements:
        conn.execute(statement)
    conn.execute(
        """
        INSERT INTO site_content(key, value, updated_at)
        VALUES (%s, %s, %s)
        ON CONFLICT(key) DO NOTHING
        """,
        (
            "about_content",
            "The Snyder Scriptorium is a growing home for books, writing, curiosity, and the stories that bring people together.",
            "01/01/1970 12:00 AM",
        ),
    )
    conn.commit()


def init_db():
    conn = get_db()
    if using_postgres():
        postgres_init_db(conn)
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                page_type TEXT NOT NULL DEFAULT 'page',
                content_id INTEGER,
                category TEXT,
                viewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
        return
    conn.close()


def migrate_sqlite_to_postgres():
    """Copy an existing local SQLite database into Postgres without deleting Postgres data."""
    if not using_postgres() or not os.path.exists(DATABASE):
        return False

    sqlite_conn = sqlite3.connect(DATABASE)
    sqlite_conn.row_factory = sqlite3.Row
    pg = get_db()
    try:
        tables = [
            "drafts", "published_posts", "manuscripts", "manuscript_books",
            "manuscript_chapters", "members", "subscriptions", "site_content"
        ]
        for table in tables:
            rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                data = dict(row)
                columns = list(data.keys())
                values = [data[column] for column in columns]
                placeholders = ", ".join(["%s"] * len(columns))
                quoted_columns = ", ".join(columns)
                if table == "site_content":
                    sql = f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders}) ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at"
                else:
                    sql = f"INSERT INTO {table} ({quoted_columns}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                pg.execute(sql, values)
        pg.commit()
        sqlite_conn.close()
        pg.close()
        return True
    except Exception:
        pg.rollback()
        sqlite_conn.close()
        pg.close()
        raise


# Kept here for callers that need to catch a database uniqueness error.
try:
    from psycopg import IntegrityError
except ImportError:
    IntegrityError = sqlite3.IntegrityError

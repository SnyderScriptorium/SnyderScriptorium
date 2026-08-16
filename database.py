import os
import sqlite3

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
    def __init__(self, connection):
        self._connection = connection

    def _translate(self, sql):
        return sql.replace("?", "%s")

    def execute(self, sql, params=()):
        normalized = sql.strip()
        upper = normalized.upper()

        if upper.startswith("PRAGMA TABLE_INFO("):
            table = normalized[normalized.find("(") + 1:normalized.rfind(")")].strip().strip('"')
            cursor = self._connection.cursor()
            cursor.execute(
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
                (table,),
            )
            return PostgresCursor(cursor)

        translated = self._translate(sql)
        wants_id = (
            upper.startswith("INSERT INTO")
            and any(f"INSERT INTO {table}" in upper for table in (
                "DRAFTS", "PUBLISHED_POSTS", "MANUSCRIPT_BOOKS", "MANUSCRIPT_CHAPTERS", "MEMBERS", "SUBSCRIPTIONS"
            ))
            and "RETURNING" not in upper
        )
        if wants_id:
            translated = translated.rstrip().rstrip(";") + " RETURNING id"

        cursor = self._connection.cursor()
        cursor.execute(translated, params)
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


def _normalize_legacy_data(conn):
    conn.execute(
        "UPDATE published_posts SET category = 'kwsnyderwriting', "
        "category_name = 'K. W. Snyder Writing', access_level = 'members' "
        "WHERE LOWER(COALESCE(category, '')) = 'journal' "
        "OR LOWER(COALESCE(category_name, '')) = 'journal'"
    )
    conn.execute("UPDATE drafts SET category = 'kwsnyderwriting' WHERE LOWER(COALESCE(category, '')) = 'journal'")
    conn.execute("UPDATE page_views SET category = 'kwsnyderwriting' WHERE LOWER(COALESCE(category, '')) = 'journal'")


def _install_access_triggers(conn):
    if using_postgres():
        conn.execute(
            """CREATE OR REPLACE FUNCTION force_kw_members_access() RETURNS trigger AS $$
            BEGIN
                IF NEW.category IN ('kwsnyderwriting','kw_short_stories','kw_poems','kw_vignettes')
                THEN NEW.access_level := 'members';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql"""
        )
        conn.execute("DROP TRIGGER IF EXISTS trg_force_kw_members_access ON published_posts")
        conn.execute(
            """CREATE TRIGGER trg_force_kw_members_access
            BEFORE INSERT OR UPDATE OF category, access_level ON published_posts
            FOR EACH ROW EXECUTE FUNCTION force_kw_members_access()"""
        )
    else:
        conn.execute("DROP TRIGGER IF EXISTS trg_force_kw_members_access_insert")
        conn.execute("DROP TRIGGER IF EXISTS trg_force_kw_members_access_update")
        conn.execute(
            """CREATE TRIGGER trg_force_kw_members_access_insert
            AFTER INSERT ON published_posts
            WHEN NEW.category IN ('kwsnyderwriting','kw_short_stories','kw_poems','kw_vignettes')
            AND NEW.access_level != 'members'
            BEGIN UPDATE published_posts SET access_level='members' WHERE id=NEW.id; END"""
        )
        conn.execute(
            """CREATE TRIGGER trg_force_kw_members_access_update
            AFTER UPDATE OF category, access_level ON published_posts
            WHEN NEW.category IN ('kwsnyderwriting','kw_short_stories','kw_poems','kw_vignettes')
            AND NEW.access_level != 'members'
            BEGIN UPDATE published_posts SET access_level='members' WHERE id=NEW.id; END"""
        )


def init_db():
    conn = get_db()
    try:
        if using_postgres():
            statements = [
                "CREATE TABLE IF NOT EXISTS drafts (id BIGSERIAL PRIMARY KEY,title TEXT NOT NULL,category TEXT NOT NULL,content TEXT NOT NULL,date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS published_posts (id BIGSERIAL PRIMARY KEY,title TEXT NOT NULL,category TEXT NOT NULL,category_name TEXT NOT NULL,content TEXT NOT NULL,date_published TEXT NOT NULL,access_level TEXT NOT NULL DEFAULT 'public')",
                "CREATE TABLE IF NOT EXISTS manuscript_books (id BIGSERIAL PRIMARY KEY,title TEXT NOT NULL,description TEXT DEFAULT '',date_created TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,access_level TEXT NOT NULL DEFAULT 'members')",
                "CREATE TABLE IF NOT EXISTS manuscript_chapters (id BIGSERIAL PRIMARY KEY,book_id BIGINT NOT NULL REFERENCES manuscript_books(id) ON DELETE CASCADE,chapter_number INTEGER NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL,date_created TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,published INTEGER NOT NULL DEFAULT 0,UNIQUE(book_id, chapter_number))",
                "CREATE TABLE IF NOT EXISTS members (id BIGSERIAL PRIMARY KEY,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,subscription_status TEXT NOT NULL DEFAULT 'inactive',date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS subscriptions (id BIGSERIAL PRIMARY KEY,member_id BIGINT NOT NULL REFERENCES members(id) ON DELETE CASCADE,provider TEXT,subscription_id TEXT,status TEXT NOT NULL DEFAULT 'inactive',date_started TEXT,date_ends TEXT)",
                "CREATE TABLE IF NOT EXISTS inbox_messages (id BIGSERIAL PRIMARY KEY,message_type TEXT NOT NULL DEFAULT 'contact',name TEXT NOT NULL DEFAULT '',email TEXT NOT NULL DEFAULT '',subject TEXT NOT NULL DEFAULT '',message TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'new',is_read INTEGER NOT NULL DEFAULT 0,post_id BIGINT,book_id BIGINT,chapter_id BIGINT,member_id BIGINT,created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)",
                "CREATE TABLE IF NOT EXISTS site_content (key TEXT PRIMARY KEY,value TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text)",
                "CREATE TABLE IF NOT EXISTS page_views (id BIGSERIAL PRIMARY KEY,path TEXT NOT NULL,page_type TEXT NOT NULL DEFAULT 'page',content_id BIGINT,category TEXT,viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,visitor_key TEXT,referrer TEXT,traffic_source TEXT)",
            ]
            for statement in statements:
                conn.execute(statement)
            for statement in [
                "ALTER TABLE members ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'inactive'",
                "ALTER TABLE members ADD COLUMN IF NOT EXISTS date_created TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS provider TEXT",
                "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS subscription_id TEXT",
                "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'inactive'",
                "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS date_started TEXT",
                "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS date_ends TEXT",
                "ALTER TABLE page_views ADD COLUMN IF NOT EXISTS page_type TEXT NOT NULL DEFAULT 'page'",
                "ALTER TABLE page_views ADD COLUMN IF NOT EXISTS content_id BIGINT",
                "ALTER TABLE page_views ADD COLUMN IF NOT EXISTS category TEXT",
                "ALTER TABLE page_views ADD COLUMN IF NOT EXISTS viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP",
                "ALTER TABLE page_views ADD COLUMN IF NOT EXISTS visitor_key TEXT",
                "ALTER TABLE page_views ADD COLUMN IF NOT EXISTS referrer TEXT",
                "ALTER TABLE page_views ADD COLUMN IF NOT EXISTS traffic_source TEXT",
            ]:
                conn.execute(statement)
        else:
            conn.execute("CREATE TABLE IF NOT EXISTS drafts (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,category TEXT NOT NULL,content TEXT NOT NULL,date_created TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS published_posts (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,category TEXT NOT NULL,category_name TEXT NOT NULL,content TEXT NOT NULL,date_published TEXT NOT NULL,access_level TEXT NOT NULL DEFAULT 'public')")
            conn.execute("CREATE TABLE IF NOT EXISTS manuscript_books (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,description TEXT DEFAULT '',date_created TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,access_level TEXT NOT NULL DEFAULT 'members')")
            conn.execute("CREATE TABLE IF NOT EXISTS manuscript_chapters (id INTEGER PRIMARY KEY AUTOINCREMENT,book_id INTEGER NOT NULL,chapter_number INTEGER NOT NULL,title TEXT NOT NULL,content TEXT NOT NULL,date_created TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,published INTEGER NOT NULL DEFAULT 0,UNIQUE(book_id,chapter_number),FOREIGN KEY(book_id) REFERENCES manuscript_books(id) ON DELETE CASCADE)")
            conn.execute("CREATE TABLE IF NOT EXISTS members (id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,subscription_status TEXT NOT NULL DEFAULT 'inactive',date_created TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT,member_id INTEGER NOT NULL,provider TEXT,subscription_id TEXT,status TEXT NOT NULL DEFAULT 'inactive',date_started TEXT,date_ends TEXT,FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE)")
            conn.execute("CREATE TABLE IF NOT EXISTS inbox_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,message_type TEXT NOT NULL DEFAULT 'contact',name TEXT NOT NULL DEFAULT '',email TEXT NOT NULL DEFAULT '',subject TEXT NOT NULL DEFAULT '',message TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'new',is_read INTEGER NOT NULL DEFAULT 0,post_id INTEGER,book_id INTEGER,chapter_id INTEGER,member_id INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE IF NOT EXISTS site_content (key TEXT PRIMARY KEY,value TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE IF NOT EXISTS page_views (id INTEGER PRIMARY KEY AUTOINCREMENT,path TEXT NOT NULL,page_type TEXT NOT NULL DEFAULT 'page',content_id INTEGER,category TEXT,viewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,visitor_key TEXT,referrer TEXT,traffic_source TEXT)")

            def add_columns(table, columns):
                existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for name, definition in columns:
                    if name not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

            add_columns("members", [("subscription_status", "TEXT NOT NULL DEFAULT 'inactive'"), ("date_created", "TEXT NOT NULL DEFAULT ''")])
            add_columns("subscriptions", [("provider", "TEXT"), ("subscription_id", "TEXT"), ("status", "TEXT NOT NULL DEFAULT 'inactive'"), ("date_started", "TEXT"), ("date_ends", "TEXT")])
            add_columns("page_views", [("page_type", "TEXT NOT NULL DEFAULT 'page'"), ("content_id", "INTEGER"), ("category", "TEXT"), ("viewed_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"), ("visitor_key", "TEXT"), ("referrer", "TEXT"), ("traffic_source", "TEXT")])
            add_columns("site_content", [("updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")])

        conn.execute(
            "INSERT INTO site_content(key,value,updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO NOTHING",
            ("about_content", "The Snyder Scriptorium is a growing home for books, writing, curiosity, and the stories that bring people together.", "01/01/1970 12:00 AM"),
        )
        _normalize_legacy_data(conn)
        _install_access_triggers(conn)
        conn.commit()
    finally:
        conn.close()


try:
    from psycopg import IntegrityError
except ImportError:
    IntegrityError = sqlite3.IntegrityError

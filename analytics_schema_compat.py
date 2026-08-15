from database import get_db, using_postgres


def ensure_schema():
    conn = get_db()
    try:
        if using_postgres():
            statements = [
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
            ]
            for statement in statements:
                conn.execute(statement)
        else:
            def add_columns(table, columns):
                existing = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()}
                for name, definition in columns:
                    if name not in existing:
                        conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
            add_columns('members', [('subscription_status', "TEXT NOT NULL DEFAULT 'inactive'"), ('date_created', "TEXT NOT NULL DEFAULT ''")])
            add_columns('subscriptions', [('provider', 'TEXT'), ('subscription_id', 'TEXT'), ('status', "TEXT NOT NULL DEFAULT 'inactive'"), ('date_started', 'TEXT'), ('date_ends', 'TEXT')])
            add_columns('page_views', [('page_type', "TEXT NOT NULL DEFAULT 'page'"), ('content_id', 'INTEGER'), ('category', 'TEXT'), ('viewed_at', "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"), ('visitor_key', 'TEXT'), ('referrer', 'TEXT'), ('traffic_source', 'TEXT')])
        conn.commit()
    finally:
        conn.close()

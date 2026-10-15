#!/usr/bin/env python3
"""
One-time migration: copy all data from Neon (SOURCE_DATABASE_URL)
to new Render Postgres (TARGET_DATABASE_URL).

Run on Render via the web service Shell tab:
    python3 migrate_neon_to_render.py

Requires env vars:
    SOURCE_DATABASE_URL - Neon connection string
    TARGET_DATABASE_URL - new Render Postgres connection string (use Internal URL)
"""
import os
import sys

import psycopg
from psycopg.rows import dict_row

SOURCE_URL = os.environ.get("SOURCE_DATABASE_URL", "") or os.environ.get("DATABASE_URL", "")
TARGET_URL = os.environ.get("TARGET_DATABASE_URL", "")

if not SOURCE_URL or not TARGET_URL:
    print("ERROR: Set SOURCE_DATABASE_URL and TARGET_DATABASE_URL env vars first.")
    sys.exit(1)

# Tables in dependency order (parents before children for FK constraints)
TABLE_ORDER = [
    "drafts",
    "published_posts",
    "manuscript_books",
    "manuscript_chapters",
    "members",
    "subscriptions",
    "inbox_messages",
    "site_content",
    "page_views",
    "find_us_events",
    "blocked_senders",
    "push_subscriptions",
    "email_subscribers",
    "store_categories",
    "store_products",
    "store_orders",
    "store_order_items",
    "store_product_images",
    "store_images",
]


def get_tables(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "ORDER BY table_name"
        )
        return [r[0] for r in cur.fetchall()]


def copy_table(src, dst, table):
    with src.cursor() as scur:
        # Get column names in order
        scur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name=%s ORDER BY ordinal_position",
            (table,),
        )
        cols = [r[0] for r in scur.fetchall()]

    quoted_cols = ", ".join(f'"{c}"' for c in cols)

    with src.cursor() as scur, dst.cursor() as dcur:
        scur.execute(f'SELECT {quoted_cols} FROM "{table}"')
        rows = scur.fetchall()
        if not rows:
            print(f"  {table}: 0 rows (skipped)")
            return 0

        placeholders = ", ".join(["%s"] * len(cols))
        # Extract values in column order from dict rows
        data = [tuple(r[c] for c in cols) for r in rows]
        dcur.executemany(
            f'INSERT INTO "{table}" ({quoted_cols}) VALUES ({placeholders})',
            data,
        )
        print(f"  {table}: {len(rows)} rows copied")
        return len(rows)


def reset_sequences(dst):
    """Set each BIGSERIAL sequence to max(id)+1 so new inserts don't collide."""
    with dst.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        )
        tables = [r[0] for r in cur.fetchall()]
        for table in tables:
            try:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name=%s AND column_default LIKE 'nextval%%'",
                    (table,),
                )
                for (col,) in cur.fetchall():
                    cur.execute(
                        "SELECT pg_get_serial_sequence(%s, %s)", (table, col)
                    )
                    seq = cur.fetchone()[0]
                    if seq:
                        cur.execute(
                            f"SELECT setval('{seq}', COALESCE(MAX(\"{col}\"), 1)) FROM \"{table}\""
                        )
                        print(f"  sequence {seq} reset")
            except Exception as e:
                print(f"  sequence reset skipped for {table}: {e}")


def main():
    print("Connecting to source (Neon)...")
    src = psycopg.connect(SOURCE_URL, row_factory=dict_row, connect_timeout=30)
    print("Connecting to target (Render)...")
    dst = psycopg.connect(TARGET_URL, row_factory=dict_row, connect_timeout=30)

    # 1. Create schema on target using the app's own table definitions
    print("\nCreating schema on target...")
    # Temporarily point DATABASE_URL at target so init_db() builds there
    os.environ["DATABASE_URL"] = TARGET_URL
    # Import after env is set (database.py reads it at import time)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import database
    importlib_reload = __import__("importlib").reload
    importlib_reload(database)
    database.init_db()
    from store import ensure_store_tables
    ensure_store_tables()
    print("Schema created.")

    # 2. Copy data
    print("\nCopying data...")
    src_tables = set(get_tables(src))
    total = 0
    with dst:
        for table in TABLE_ORDER:
            if table not in src_tables:
                print(f"  {table}: not in source (skipped)")
                continue
            # Clear target table first (fresh migration)
            with dst.cursor() as cur:
                cur.execute(f'DELETE FROM "{table}"')
            total += copy_table(src, dst, table)
        print("\nResetting sequences...")
        reset_sequences(dst)
        dst.commit()

    # 3. Verify
    print("\nVerifying row counts...")
    mismatches = []
    for table in TABLE_ORDER:
        with src.cursor() as scur, dst.cursor() as dcur:
            scur.execute(f'SELECT COUNT(*) AS c FROM "{table}"')
            dcur.execute(f'SELECT COUNT(*) AS c FROM "{table}"')
            s, d = scur.fetchone()["c"], dcur.fetchone()["c"]
            status = "OK" if s == d else "MISMATCH!"
            if s != d:
                mismatches.append(table)
            print(f"  {table}: source={s} target={d} {status}")

    src.close()
    dst.close()

    print(f"\nDone. {total} total rows copied.")
    if mismatches:
        print(f"WARNING: mismatches in: {mismatches}")
        sys.exit(2)
    print("All tables verified — counts match.")


if __name__ == "__main__":
    main()

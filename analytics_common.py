"""Shared analytics helpers for the Scriptorium.

This module is the single home of two pieces of logic that used to be
duplicated:

- referrer -> traffic-source labels (was copied between
  canonical_analytics_tracker._source and analytics_dashboard_v3.source_label)
- URL path classification for page_views (canonical_analytics_tracker._classify)

It is intentionally dependency-free (stdlib only) so database.py can import
the backfill without creating an import cycle.
"""

import re

# ---------------------------------------------------------------------------
# Traffic sources
# ---------------------------------------------------------------------------

_SOURCE_PATTERNS = (
    ("facebook.com", "Facebook"),
    ("instagram.com", "Instagram"),
    ("threads.net", "Threads"),
    ("t.co", "X / Twitter"),
    ("twitter.", "X / Twitter"),
    ("x.com", "X / Twitter"),
    ("google.", "Google"),
    ("bing.", "Bing"),
    ("yahoo.", "Yahoo"),
    ("duckduckgo.com", "DuckDuckGo"),
    ("pinterest.", "Pinterest"),
    ("linkedin.", "LinkedIn"),
    ("reddit.com", "Reddit"),
    ("youtube.com", "YouTube"),
    ("tiktok.com", "TikTok"),
)


def traffic_source_label(referrer):
    """Map a referrer header/URL to a human-readable traffic source."""
    r = (referrer or "").lower()
    if not r:
        return "Direct"
    for key, label in _SOURCE_PATTERNS:
        if key in r:
            return label
    return "Referral"


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------

def classify_path(path, store_slug_to_id=None):
    """Classify a request path for page_views.

    Returns (page_type, category, content_id). ``store_slug_to_id`` is an
    optional slug->product-id map used to resolve /store/book/<slug> links;
    callers that have no map can pass None (content_id will be None then).

    Classifications mirror the historic canonical_analytics_tracker._classify
    behavior so stored values stay consistent across the refactor.
    """
    path = (path or "/").split("?")[0] or "/"
    if path in ("/", "/index"):
        return ("page", "site", None)
    if path in ("/about", "/about-us"):
        return ("page", "about", None)
    if path in ("/membership", "/membership-terms"):
        return ("page", "site", None)
    if path.startswith("/find-us"):
        return ("page", "site", None)
    if path == "/blog":
        return ("section", "blog", None)
    if path == "/blog/bookcurations":
        return ("section", "curations", None)
    if path == "/blog/bookreviews":
        return ("section", "reviews", None)
    if path == "/blog/curiosity_cabinet":
        return ("section", "curiosity", None)
    m = re.match(r"^/blog/post/(\d+)", path)
    if m:
        return ("post", "public_post", int(m.group(1)))
    if path in ("/store", "/store/"):
        return ("page", "store", None)
    m = re.match(r"^/store/book/([^/]+)$", path)
    if m:
        slug_map = store_slug_to_id or {}
        return ("store_book", "store", slug_map.get(m.group(1)))
    if path == "/kwsnyderwriting":
        return ("member_section", "kwsnyderwriting", None)
    m = re.match(r"^/kwsnyderwriting/section/([^/]+)$", path)
    if m:
        return ("post_list", "kwsnyderwriting", None)
    m = re.match(r"^/kwsnyderwriting/post/(\d+)", path)
    if m:
        return ("member_post", "kwsnyderwriting", int(m.group(1)))
    m = re.match(r"^/kwsnyderwriting/novel/(\d+)/chapter/(\d+)", path)
    if m:
        return ("chapter", "kwsnyderwriting", int(m.group(2)))
    m = re.match(r"^/kwsnyderwriting/novel/(\d+)", path)
    if m:
        return ("novel", "kwsnyderwriting", int(m.group(1)))
    if path in ("/account", "/checkout"):
        return ("page", "site", None)
    return ("page", "site", None)


# ---------------------------------------------------------------------------
# One-shot backfill
# ---------------------------------------------------------------------------

def _col(row, index, key):
    """Read a column by index (SQLite) or by key (psycopg dict_row)."""
    try:
        return row[index]
    except (KeyError, IndexError, TypeError):
        return row[key]


def backfill_page_view_classification(conn, limit=None):
    """Reclassify historical page_views rows that were saved without labels.

    Older rows (tracked before content_id existed) have content_id NULL. This
    re-runs classify_path() over their saved paths and fills in page_type,
    category, and content_id. One-shot: every processed row is marked
    classified=1, so a later run never re-scans it. (Keying off
    content_id IS NULL instead would re-process paths like "/" forever,
    because their classification legitimately has no content_id -- every
    run would re-update every one of those rows.)

    ``limit`` optionally caps how many distinct paths are processed in this
    call, so large histories can be backfilled in bounded batches. Callers
    that need the whole history loop until this returns 0.

    Returns the number of rows updated.
    """
    try:
        count_row = conn.execute("SELECT COUNT(*) AS n FROM page_views WHERE classified = 0").fetchone()
    except Exception:
        return 0
    if _col(count_row, 0, "n") == 0:
        return 0

    store_slug_to_id = {}
    try:
        for row in conn.execute("SELECT slug, id FROM store_products").fetchall():
            store_slug_to_id[_col(row, 0, "slug")] = _col(row, 1, "id")
    except Exception:
        # A failed statement aborts the whole transaction on psycopg, which
        # would poison every query below. Roll back so classification still
        # runs; a missing store_products table simply means no slug->id
        # resolution (store tables may not be installed yet).
        try:
            conn.rollback()
        except Exception:
            pass

    try:
        path_sql = "SELECT DISTINCT path FROM page_views WHERE classified = 0"
        if limit is not None:
            path_sql += f" LIMIT {int(limit)}"
        paths = [_col(row, 0, "path") for row in conn.execute(path_sql).fetchall()]
    except Exception:
        return 0

    total = 0
    for path in paths:
        page_type, category, content_id = classify_path(path, store_slug_to_id)
        result = conn.execute(
            "UPDATE page_views SET page_type=?, category=?, content_id=?, classified=1 "
            "WHERE classified = 0 AND path=?",
            (page_type, category, content_id, path),
        )
        total += result.rowcount or 0
    conn.commit()
    return total

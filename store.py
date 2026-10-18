import os
import re
import time
import threading
from datetime import datetime
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape as xml_escape

import requests
from flask import Blueprint, jsonify, make_response, redirect, render_template, request, session, url_for, abort

from database import get_db, using_postgres, IntegrityError

store_bp = Blueprint("store", __name__)
_store_request_schema_ready = False
_store_request_schema_lock = threading.Lock()

# --- Bookstore visibility -------------------------------------------------
STORE_VISIBLE = True

ALLOWED_STATUS = {"draft", "active", "archived"}
ALLOWED_CONDITIONS = {"new", "used"}
ALLOWED_SECTIONS = {"Antique", "Vintage", "Used", "New"}


def canonical_section(value):
    text = str(value or "").strip().lower()
    for section in ALLOWED_SECTIONS:
        if text == section.lower():
            return section
    return None

STORE_IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "store_images")
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def now_string():
    return datetime.now().strftime("%m/%d/%Y %I:%M %p")


def require_admin():
    return bool(
        session.get("admin_logged_in") is True
        and session.get("admin_auth_version") == "2026-08-16-1"
    )


def admin_required():
    if not require_admin():
        if request.path.startswith("/api/"):
            return jsonify({"error": "Admin session expired. Please log in again."}), 401
        return redirect(url_for("admin_login_page"))
    return None


STORE_MAINTENANCE_UNTIL = "2026-10-05T00:00:00+00:00"


def _store_under_maintenance():
    override = (os.environ.get("STORE_MAINTENANCE") or "").strip().lower()
    if override in ("0", "false", "off", "no"):
        return False
    if override in ("1", "true", "on", "yes"):
        return True
    try:
        from datetime import timezone
        until = datetime.fromisoformat(
            (os.environ.get("STORE_MAINTENANCE_UNTIL") or STORE_MAINTENANCE_UNTIL).strip())
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < until
    except Exception:
        return False


@store_bp.before_request
def _store_maintenance_curtain():
    path = request.path or ""
    is_storefront = path == "/store" or path.startswith(("/store/", "/api/store/paypal", "/api/store/products"))
    if not is_storefront:
        return None
    if require_admin():
        return None
    if not _store_under_maintenance():
        return None
    resp = make_response(render_template("store_maintenance.html"), 503)
    resp.headers["Retry-After"] = "172800"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def slugify(value):
    value = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return value or "book"


def ensure_store_tables():
    global _store_request_schema_ready
    conn = get_db()
    try:
        if using_postgres():
            statements = [
                "CREATE TABLE IF NOT EXISTS store_categories (id BIGSERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_products (id BIGSERIAL PRIMARY KEY, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, author TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL DEFAULT 0, format TEXT NOT NULL DEFAULT 'Paperback', isbn TEXT NOT NULL DEFAULT '', cover_image_url TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Books', language TEXT NOT NULL DEFAULT 'English', fulfillment_source TEXT NOT NULL DEFAULT 'Ingram Content Group', fulfillment_method TEXT NOT NULL DEFAULT 'Direct to Home', stock_quantity INTEGER NOT NULL DEFAULT 0, availability_status TEXT NOT NULL DEFAULT 'automatic', condition TEXT NOT NULL DEFAULT 'new', is_new_release INTEGER NOT NULL DEFAULT 0, is_kw_snyder INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_orders (id BIGSERIAL PRIMARY KEY, customer_name TEXT NOT NULL DEFAULT '', customer_email TEXT NOT NULL DEFAULT '', total_cents INTEGER NOT NULL DEFAULT 0, payment_status TEXT NOT NULL DEFAULT 'unpaid', order_status TEXT NOT NULL DEFAULT 'pending', provider TEXT NOT NULL DEFAULT '', provider_order_id TEXT NOT NULL DEFAULT '', ship_name TEXT NOT NULL DEFAULT '', ship_line1 TEXT NOT NULL DEFAULT '', ship_line2 TEXT NOT NULL DEFAULT '', ship_city TEXT NOT NULL DEFAULT '', ship_state TEXT NOT NULL DEFAULT '', ship_postal TEXT NOT NULL DEFAULT '', ship_country TEXT NOT NULL DEFAULT '', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_order_items (id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES store_orders(id) ON DELETE CASCADE, product_id BIGINT NOT NULL REFERENCES store_products(id), quantity INTEGER NOT NULL DEFAULT 1, unit_price_cents INTEGER NOT NULL DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS store_product_images (id BIGSERIAL PRIMARY KEY, product_id BIGINT NOT NULL REFERENCES store_products(id) ON DELETE CASCADE, image_url TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_images (id BIGSERIAL PRIMARY KEY, data BYTEA NOT NULL, mime TEXT NOT NULL DEFAULT 'image/jpeg', date_created TEXT NOT NULL)",
            ]
        else:
            statements = [
                "CREATE TABLE IF NOT EXISTS store_categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_products (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, author TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL DEFAULT 0, format TEXT NOT NULL DEFAULT 'Paperback', isbn TEXT NOT NULL DEFAULT '', cover_image_url TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Books', language TEXT NOT NULL DEFAULT 'English', fulfillment_source TEXT NOT NULL DEFAULT 'Ingram Content Group', fulfillment_method TEXT NOT NULL DEFAULT 'Direct to Home', stock_quantity INTEGER NOT NULL DEFAULT 0, availability_status TEXT NOT NULL DEFAULT 'automatic', condition TEXT NOT NULL DEFAULT 'new', is_new_release INTEGER NOT NULL DEFAULT 0, is_kw_snyder INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL DEFAULT '', customer_email TEXT NOT NULL DEFAULT '', total_cents INTEGER NOT NULL DEFAULT 0, payment_status TEXT NOT NULL DEFAULT 'unpaid', order_status TEXT NOT NULL DEFAULT 'pending', provider TEXT NOT NULL DEFAULT '', provider_order_id TEXT NOT NULL DEFAULT '', ship_name TEXT NOT NULL DEFAULT '', ship_line1 TEXT NOT NULL DEFAULT '', ship_line2 TEXT NOT NULL DEFAULT '', ship_city TEXT NOT NULL DEFAULT '', ship_state TEXT NOT NULL DEFAULT '', ship_postal TEXT NOT NULL DEFAULT '', ship_country TEXT NOT NULL DEFAULT '', date_created TEXT NOT NULL, date_updated TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_order_items (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES store_orders(id) ON DELETE CASCADE, product_id INTEGER NOT NULL REFERENCES store_products(id), quantity INTEGER NOT NULL DEFAULT 1, unit_price_cents INTEGER NOT NULL DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS store_product_images (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL REFERENCES store_products(id) ON DELETE CASCADE, image_url TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, date_created TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS store_images (id INTEGER PRIMARY KEY AUTOINCREMENT, data BLOB NOT NULL, mime TEXT NOT NULL DEFAULT 'image/jpeg', date_created TEXT NOT NULL)",
            ]
        for statement in statements:
            conn.execute(statement)

        if using_postgres():
            migrations = [
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'English'",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS fulfillment_source TEXT NOT NULL DEFAULT 'Ingram Content Group'",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS fulfillment_method TEXT NOT NULL DEFAULT 'Direct to Home'",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS availability_status TEXT NOT NULL DEFAULT 'automatic'",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS condition TEXT NOT NULL DEFAULT 'new'",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS is_new_release INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS is_kw_snyder INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS publisher TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS publication_year TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS edition TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS condition_notes TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_products ADD COLUMN IF NOT EXISTS genre TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_name TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_line1 TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_line2 TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_city TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_state TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_postal TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS ship_country TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE store_orders ADD COLUMN IF NOT EXISTS tracking_number TEXT NOT NULL DEFAULT ''",
            ]
        else:
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(store_products)").fetchall()}
            migrations = []
            for name, definition in [
                ("language", "TEXT NOT NULL DEFAULT 'English'"),
                ("fulfillment_source", "TEXT NOT NULL DEFAULT 'Ingram Content Group'"),
                ("fulfillment_method", "TEXT NOT NULL DEFAULT 'Direct to Home'"),
                ("availability_status", "TEXT NOT NULL DEFAULT 'automatic'"),
                ("condition", "TEXT NOT NULL DEFAULT 'new'"),
                ("is_new_release", "INTEGER NOT NULL DEFAULT 0"),
                ("is_kw_snyder", "INTEGER NOT NULL DEFAULT 0"),
                ("publisher", "TEXT NOT NULL DEFAULT ''"),
                ("publication_year", "TEXT NOT NULL DEFAULT ''"),
                ("edition", "TEXT NOT NULL DEFAULT ''"),
                ("condition_notes", "TEXT NOT NULL DEFAULT ''"),
                ("notes", "TEXT NOT NULL DEFAULT ''"),
                ("genre", "TEXT NOT NULL DEFAULT ''"),
            ]:
                if name not in existing:
                    migrations.append(f"ALTER TABLE store_products ADD COLUMN {name} {definition}")
            existing_orders = {row["name"] for row in conn.execute("PRAGMA table_info(store_orders)").fetchall()}
            for name in ("ship_name", "ship_line1", "ship_line2", "ship_city",
                         "ship_state", "ship_postal", "ship_country", "tracking_number"):
                if name not in existing_orders:
                    migrations.append(f"ALTER TABLE store_orders ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        for statement in migrations:
            conn.execute(statement)

        _migrate_local_store_images(conn)

        for seed_category in ("Books", "Antique", "Vintage", "Used", "New"):
            conn.execute(
                "INSERT INTO store_categories(name, date_created) VALUES (?, ?) ON CONFLICT(name) DO NOTHING",
                (seed_category, now_string()),
            )
        conn.commit()
        _store_request_schema_ready = True
    finally:
        conn.close()


def parse_price(value):
    try:
        amount = Decimal(str(value).strip()).quantize(Decimal("0.01"))
        if amount < 0:
            raise InvalidOperation
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise ValueError("Price must be a non-negative dollar amount.")


def product_payload(data):
    title = str(data.get("title", "")).strip()
    if not title:
        raise ValueError("A book title is required.")

    raw_price = data.get("price", "")
    if raw_price is None or str(raw_price).strip() == "":
        raise ValueError("A price is required.")
    price_cents = parse_price(raw_price)

    status = str(data.get("status", "draft")).strip().lower()
    if status not in ALLOWED_STATUS:
        raise ValueError("Invalid product status.")

    raw_section = str(data.get("category", "")).strip()
    section = canonical_section(raw_section) or raw_section or "Antique"

    try:
        stock_quantity = int(str(data.get("stock_quantity", "1") or "1").strip())
    except (TypeError, ValueError):
        raise ValueError("Stock quantity must be a whole number.")
    if stock_quantity < 0:
        raise ValueError("Stock quantity cannot be negative.")

    return {
        "title": title,
        "slug": slugify(data.get("slug") or title),
        "author": str(data.get("author", "")).strip(),
        "description": str(data.get("description", "")).strip(),
        "price_cents": price_cents,
        "format": str(data.get("format", "Hardcover")).strip() or "Hardcover",
        "isbn": str(data.get("isbn", "")).strip(),
        "cover_image_url": str(data.get("cover_image_url", "")).strip(),
        "category": section,
        "genre": str(data.get("genre", "")).strip(),
        "language": str(data.get("language", "English")).strip() or "English",
        "fulfillment_source": str(data.get("fulfillment_source", "In-house")).strip() or "In-house",
        "fulfillment_method": str(data.get("fulfillment_method", "Direct to Home")).strip() or "Direct to Home",
        "availability_status": str(data.get("availability_status", "automatic")).strip() or "automatic",
        "condition": "used",
        "is_new_release": 0,
        "is_kw_snyder": 0,
        "stock_quantity": stock_quantity,
        "status": status,
        "publisher": str(data.get("publisher", "")).strip(),
        "publication_year": str(data.get("publication_year", "")).strip(),
        "edition": str(data.get("edition", "")).strip(),
        "condition_notes": str(data.get("condition_notes", "")).strip(),
        "notes": str(data.get("notes", "")).strip(),
    }


def image_extension_for(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _validate_upload(storage):
    filename = (storage.filename or "").strip()
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Photo must be a PNG, JPG, GIF, or WebP file.")
    data = storage.read(MAX_IMAGE_BYTES + 1)
    if not data:
        raise ValueError("The uploaded photo was empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Photo must be smaller than 5 MB.")
    real_ext = image_extension_for(data)
    if not real_ext:
        raise ValueError("That file does not look like a real image.")
    mime = "image/" + ("jpeg" if real_ext == ".jpg" else real_ext[1:])
    return data, mime


def store_image_data(conn, data, mime):
    cur = conn.execute(
        "INSERT INTO store_images(data, mime, date_created) VALUES (?, ?, ?)",
        (bytes(data), mime, now_string()),
    )
    return "/store/image/%d" % cur.lastrowid


def save_product_photo(conn, storage):
    data, mime = _validate_upload(storage)
    return store_image_data(conn, data, mime)


MAX_GALLERY_IMAGES = 6


def save_gallery_photo(conn, storage):
    data, mime = _validate_upload(storage)
    return store_image_data(conn, data, mime)


def _image_id_from_url(url):
    if not url or not isinstance(url, str):
        return None
    prefix = "/store/image/"
    if not url.startswith(prefix):
        return None
    tail = url[len(prefix):]
    return int(tail) if tail.isdigit() else None


def delete_stored_image(conn, url):
    image_id = _image_id_from_url(url)
    if image_id:
        conn.execute("DELETE FROM store_images WHERE id = ?", (image_id,))
    else:
        _delete_local_cover_image(url)


_images_migrated = False


def _migrate_local_store_images(conn, limit=50):
    global _images_migrated
    if _images_migrated:
        return 0
    _images_migrated = True
    if not os.path.isdir(STORE_IMAGE_DIR):
        return 0
    migrated = 0
    try:
        targets = []
        for table, column in (("store_products", "cover_image_url"),
                              ("store_product_images", "image_url")):
            rows = conn.execute(
                "SELECT id, %s AS url FROM %s WHERE %s LIKE '/static/store_images/%%%%'" % (column, table, column)
            ).fetchall()
            targets.extend((table, column, r["id"], r["url"]) for r in rows)
    except Exception:
        return 0
    for table, column, row_id, url in targets:
        if migrated >= limit:
            break
        try:
            filename = url[len("/static/store_images/"):]
            if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
                continue
            path = os.path.join(STORE_IMAGE_DIR, filename)
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as handle:
                data = handle.read(MAX_IMAGE_BYTES + 1)
            if not data or len(data) > MAX_IMAGE_BYTES:
                continue
            real_ext = image_extension_for(data)
            if not real_ext:
                continue
            mime = "image/" + ("jpeg" if real_ext == ".jpg" else real_ext[1:])
            new_url = store_image_data(conn, data, mime)
            conn.execute("UPDATE %s SET %s = ? WHERE id = ?" % (table, column), (new_url, row_id))
            migrated += 1
        except Exception:
            continue
    return migrated


@store_bp.route("/store/image/<int:image_id>")
def serve_store_image(image_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT data, mime FROM store_images WHERE id = ?", (image_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        abort(404)
    data = row["data"]
    if isinstance(data, memoryview):
        data = data.tobytes()
    response = make_response(bytes(data))
    response.headers["Content-Type"] = row["mime"] or "image/jpeg"
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def get_product_images(conn, product_id):
    rows = conn.execute(
        "SELECT id, image_url FROM store_product_images WHERE product_id = ? ORDER BY position, id",
        (product_id,),
    ).fetchall()
    return [{"id": row["id"], "image_url": row["image_url"]} for row in rows]


def _request_gallery_photos():
    if request.is_json:
        return []
    photos = request.files.getlist("photos")
    return [p for p in photos if p and (p.filename or "").strip()]


def _sync_postgres_sequence_for_table(conn, table):
    """Make a PostgreSQL serial/bigserial sequence agree with its table.

    This is deliberately done immediately before an image-row insert as well
    as during startup. That protects the book-save flow from stale sequences
    left behind by older imports/migrations, including a sequence that became
    stale after a previous deployment.
    """
    if not using_postgres():
        return
    if table != "store_product_images":
        raise ValueError("Unsupported bookstore sequence table.")
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext('snyderscriptorium_store_product_images_sequence'))"
    )
    conn.execute(
        "SELECT setval(pg_get_serial_sequence('store_product_images', 'id'), "
        "COALESCE((SELECT MAX(id) FROM store_product_images), 0), "
        "CASE WHEN COALESCE((SELECT MAX(id) FROM store_product_images), 0) > 0 THEN true ELSE false END)"
    )


def add_gallery_photos(conn, product_id, slug):
    """Save uploaded gallery photos; returns warning strings.

    PostgreSQL gallery IDs are repaired under a transaction advisory lock
    immediately before each insert. This makes the operation self-healing even
    when a stale sequence survived an earlier deployment.
    """
    warnings = []
    existing = conn.execute(
        "SELECT COUNT(*) AS c FROM store_product_images WHERE product_id = ?", (product_id,)
    ).fetchone()["c"]
    position = existing
    for storage in _request_gallery_photos():
        if position >= MAX_GALLERY_IMAGES:
            warnings.append(f"Only {MAX_GALLERY_IMAGES} gallery photos per book are kept.")
            break
        try:
            url = save_gallery_photo(conn, storage)
        except ValueError as exc:
            warnings.append(str(exc))
            continue
        _sync_postgres_sequence_for_table(conn, "store_product_images")
        conn.execute(
            "INSERT INTO store_product_images(product_id, image_url, position, date_created) VALUES (?, ?, ?, ?)",
            (product_id, url, position, now_string()),
        )
        position += 1
    return warnings


def row_to_dict(row):
    item = dict(row)
    item["price"] = f"{item['price_cents'] / 100:.2f}"
    item["is_new_release"] = bool(item.get("is_new_release"))
    item["is_kw_snyder"] = bool(item.get("is_kw_snyder"))
    item["genre"] = item.get("genre") or ""
    item["section"] = canonical_section(item.get("category"))
    return item


def public_dict(row):
    item = row_to_dict(row)
    item.pop("notes", None)
    return item


@store_bp.before_request
def prepare_store():
    global _store_request_schema_ready
    if _store_request_schema_ready:
        return None
    with _store_request_schema_lock:
        if not _store_request_schema_ready:
            ensure_store_tables()
            _store_request_schema_ready = True
    return None


def active_products(conn):
    return conn.execute(
        """SELECT p.*, COALESCE(v.view_count, 0) AS view_count,
                  COALESCE(v.unique_visitors, 0) AS unique_visitors
           FROM store_products p
           LEFT JOIN (
               SELECT content_id, COUNT(*) AS view_count,
                      COUNT(DISTINCT visitor_key) AS unique_visitors
               FROM page_views
               WHERE page_type = 'store_book' AND category = 'store'
               GROUP BY content_id
           ) v ON v.content_id = p.id
           WHERE p.status = 'active' AND p.stock_quantity > 0
           ORDER BY LOWER(p.title), p.id"""
    ).fetchall()


def _request_data():
    if request.is_json:
        return request.get_json() or {}
    return request.form.to_dict()


def _request_photo():
    return request.files.get("cover_photo") if not request.is_json else None

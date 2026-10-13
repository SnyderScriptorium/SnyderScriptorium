import hashlib
import re
import uuid
from flask import request, session, g
from analytics_common import classify_path, traffic_source_label
from database import get_db

PUBLIC_CATEGORIES = {
    'curations': 'Book Curations',
    'reviews': 'Book Reviews',
    'curiosity': 'Curiosity Cabinet',
}

# Known crawlers, bots, link-preview clients, and monitoring agents should be
# allowed to visit the site normally, but must not inflate human-view analytics.
BOT_RE = re.compile(
    r'(?:bot|crawler|spider|slurp|google-extended|googleother|bingpreview|bingbot|yandex|baiduspider|duckduckbot|facebookexternalhit|facebot|twitterbot|linkedinbot|pinterestbot|embedly|quora link preview|whatsapp|telegrambot|applebot|semrush|ahrefs|mj12bot|dotbot|petalbot|bytespider|gptbot|claudebot|anthropic|perplexity|headlesschrome|lighthouse|pagespeed|uptimerobot|statuscake|pingdom|site24x7)', re.I
)


def _source(referrer):
    """Delegate to the shared referrer->source mapping in analytics_common."""
    return traffic_source_label(referrer)


def _client_ip():
    # Cloudflare overwrites CF-Connecting-IP, so trust it when present.
    ip = (request.headers.get('CF-Connecting-IP') or '').strip()
    if ip:
        return ip
    fwd = (request.headers.get('X-Forwarded-For') or '').strip()
    if fwd:
        return fwd.split(',')[0].strip()
    return request.remote_addr or ''


def _visitor_key():
    ck = request.cookies.get('snyder_visitor_key')
    if ck:
        return ck
    # No cookie: reuse one key for the whole request so the tracked pageview
    # and the Set-Cookie header agree. Previously they minted two different
    # UUIDs, double-counting every cookie-keeping human.
    gk = getattr(g, '_snyder_visitor_key', None)
    if gk:
        return gk
    # Cookieless client: stable IP+UA fingerprint instead of a fresh UUID per
    # hit, so scrapers and cookie-blockers count as one visitor, not one per
    # pageview. (Rare NAT collisions may slightly undercount; far more
    # accurate than the old behavior.)
    raw = _client_ip() + '|' + (request.headers.get('User-Agent', '') or '')
    gk = 'fp-' + hashlib.sha256(raw.encode('utf-8', 'ignore')).hexdigest()[:32]
    g._snyder_visitor_key = gk
    return gk


def _classify(path):
    """Classify a path via analytics_common, with a lazy store-slug lookup."""
    store_slug_to_id = None
    if (path or "").startswith("/store/book/"):
        try:
            conn = get_db()
            rows = conn.execute("SELECT slug, id FROM store_products").fetchall()
            store_slug_to_id = {}
            for row in rows:
                try:
                    slug, pid = row["slug"], row["id"]
                except (TypeError, KeyError):
                    slug, pid = row[0], row[1]
                store_slug_to_id[slug] = pid
            conn.close()
        except Exception:
            store_slug_to_id = None
    return classify_path(path, store_slug_to_id)


def register(app):
    @app.before_request
    def canonical_analytics_tracker():
        path = request.path
        if path.startswith(('/static/', '/api/', '/admin')):
            return None

        # Admins should be able to browse/test the public site without
        # polluting human visitor analytics. This does NOT affect public
        # visitors or prevent search engines from crawling/indexing pages.
        if session.get('admin_logged_in') is True:
            return None

        # Do not block these clients. They still receive the normal page and
        # can index/crawl it; we simply exclude them from human analytics.
        user_agent = request.headers.get('User-Agent', '')
        if not user_agent or BOT_RE.search(user_agent):
            return None

        page_type, category, content_id = _classify(path)
        if category == 'kwsnyderwriting':
            try:
                from app import member_has_access
                if not member_has_access():
                    return None
            except Exception:
                return None

        visitor_key = _visitor_key()
        referrer = request.referrer or ''
        conn = None
        try:
            conn = get_db()
            conn.execute(
                'INSERT INTO page_views(path,page_type,content_id,category,visitor_key,referrer,traffic_source,classified) VALUES (?,?,?,?,?,?,?,1)',
                (path, page_type, content_id, category, visitor_key, referrer, _source(referrer)),
            )
            conn.commit()
        except Exception:
            pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @app.after_request
    def canonical_analytics_cookie(response):
        if not request.path.startswith(('/static/', '/api/', '/admin')) and not request.cookies.get('snyder_visitor_key'):
            response.set_cookie(
                'snyder_visitor_key', _visitor_key(), max_age=31536000,
                httponly=True, samesite='Lax', secure=True
            )
        return response

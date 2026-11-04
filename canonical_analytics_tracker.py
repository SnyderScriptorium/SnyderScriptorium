import hashlib
import re
import uuid
from flask import request, session, g
from analytics_common import classify_path, traffic_source_label, is_spam_referrer
from database import get_db

PUBLIC_CATEGORIES = {
    'curations': 'Book Curations',
    'reviews': 'Book Reviews',
    'curiosity': 'Curiosity Cabinet',
    'kwsnyderwriting': 'K. W. Snyder Writing',
}

# Known crawlers, bots, link-preview clients, and monitoring agents should be
# allowed to visit the site normally, but must not inflate human-view analytics.
BOT_RE = re.compile(
    r'(?:bot|crawler|spider|slurp|google-extended|googleother|bingpreview|bingbot|yandex|baiduspider|duckduckbot|facebookexternalhit|facebot|twitterbot|linkedinbot|pinterestbot|embedly|quora link preview|whatsapp|telegrambot|applebot|semrush|ahrefs|mj12bot|dotbot|petalbot|bytespider|gptbot|claudebot|anthropic|perplexity|headlesschrome|lighthouse|pagespeed|uptimerobot|statuscake|pingdom|site24x7)', re.I
)


def _source(referrer, utm_source=None):
    """Delegate to the shared referrer->source mapping in analytics_common."""
    return traffic_source_label(referrer, utm_source)


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
    if (path or '').startswith('/store/book/'):
        try:
            conn = get_db()
            rows = conn.execute('SELECT slug, id FROM store_products').fetchall()
            store_slug_to_id = {}
            for row in rows:
                try:
                    slug, pid = row['slug'], row['id']
                except (TypeError, KeyError):
                    slug, pid = row[0], row[1]
                store_slug_to_id[slug] = pid
            conn.close()
        except Exception:
            store_slug_to_id = None
    return classify_path(path, store_slug_to_id)


def _is_trackable_page(path):
    """Return False for storefront assets/actions that are not page views."""
    path = path or '/'
    if path.startswith('/store/image/'):
        return False
    if path in ('/store/subscribe', '/store/unsubscribe'):
        return False
    return True


def register(app):
    @app.before_request
    def canonical_analytics_tracker():
        path = request.path
        if path.startswith(('/static/', '/api/', '/admin')):
            return None
        if not _is_trackable_page(path):
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
            # Private-library traffic is recorded in after_request, once
            # the server has decided the request: a 200 to an authorized
            # member is a read, a redirect to the membership/login page is
            # a blocked attempt. Recording here, in before_request, would
            # count attempts that never returned content and could never
            # carry a member id on blocked rows.
            return None

        visitor_key = _visitor_key()
        referrer = request.referrer or ''
        # Referrer-spam bots: never record the view at all.
        if is_spam_referrer(referrer):
            return None
        utm_source = (request.args.get('utm_source') or '').strip()[:64]
        conn = None
        try:
            conn = get_db()
            conn.execute(
                'INSERT INTO page_views(path,page_type,content_id,category,visitor_key,referrer,traffic_source,classified) VALUES (?,?,?,?,?,?,?,1)',
                (path, page_type, content_id, category, visitor_key, referrer, _source(referrer, utm_source)),
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
    def canonical_analytics_member_reads(response):
        # Private-library reads and blocked attempts, recorded only after
        # the server has decided the request. A 200 to an authorized member
        # is a read (with that member's id); a redirect to the membership
        # or login page is a blocked attempt (with the member id when the
        # visitor was signed in, else NULL). Anything else — a 404 for a
        # post that does not exist, an error, an admin preview — is
        # neither a read nor a blocked attempt and is not recorded.
        try:
            path = request.path
            if path.startswith(('/static/', '/api/', '/admin')):
                return response
            if not _is_trackable_page(path):
                return response
            if session.get('admin_logged_in') is True:
                return response
            user_agent = request.headers.get('User-Agent', '')
            if not user_agent or BOT_RE.search(user_agent):
                return response
            page_type, category, content_id = _classify(path)
            if category != 'kwsnyderwriting':
                return response
            location = response.headers.get('Location', '')
            member_id = session.get('member_id')
            if response.status_code == 200:
                try:
                    from app import member_has_access
                    if not member_has_access():
                        return response
                except Exception:
                    return response
                access_result = 'ok'
            elif response.status_code in (301, 302, 303) and (
                '/kwsnyderwriting/membership' in location or '/kwsnyderwriting/login' in location
            ):
                access_result = 'blocked'
            else:
                return response
            visitor_key = _visitor_key()
            referrer = request.referrer or ''
            if is_spam_referrer(referrer):
                return response
            utm_source = (request.args.get('utm_source') or '').strip()[:64]
            conn = None
            try:
                conn = get_db()
                conn.execute(
                    'INSERT INTO page_views(path,page_type,content_id,category,visitor_key,referrer,traffic_source,classified,member_id,access_result) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (path, page_type, content_id, category, visitor_key, referrer, _source(referrer, utm_source), 1, member_id, access_result),
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
        except Exception:
            pass
        return response

    @app.after_request
    def canonical_analytics_cookie(response):
        if _is_trackable_page(request.path) and not request.path.startswith(('/static/', '/api/', '/admin')) and not request.cookies.get('snyder_visitor_key'):
            response.set_cookie(
                'snyder_visitor_key', _visitor_key(), max_age=31536000,
                httponly=True, samesite='Lax', secure=True
            )
        return response

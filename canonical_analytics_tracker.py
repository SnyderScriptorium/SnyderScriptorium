import hashlib
import re
from flask import request, session, g
from analytics_common import classify_path, traffic_source_label, is_spam_referrer
from database import get_db

PUBLIC_CATEGORIES = {
    'curations': 'Book Curations',
    'reviews': 'Book Reviews',
    'curiosity': 'Curiosity Cabinet',
    'kwsnyderwriting': 'K. W. Snyder Writing',
}

# Exclude known crawlers, link-preview fetchers, uptime monitors, and common
# scripted HTTP clients from human pageview counts. This is a practical filter,
# not proof that every remaining request is a human.
BOT_RE = re.compile(
    r'(?:bot|crawler|spider|slurp|google-extended|googleother|googlebot|google-inspectiontool|adsbot-google|bingpreview|bingbot|yandex|baiduspider|duckduckbot|facebookexternalhit|facebot|twitterbot|linkedinbot|pinterestbot|embedly|quora link preview|whatsapp|telegrambot|applebot|semrush|ahrefs|mj12bot|dotbot|petalbot|bytespider|amazonbot|gptbot|claudebot|anthropic|perplexity|cohere-ai|meta-externalagent|meta-externalfetcher|headlesschrome|lighthouse|pagespeed|uptimerobot|statuscake|pingdom|site24x7|curl/|wget/|python-requests|python-urllib|go-http-client|java/|okhttp|scrapy|httpx|aiohttp)',
    re.I
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
    # Reuse one key for the tracked pageview and Set-Cookie header.
    gk = getattr(g, '_snyder_visitor_key', None)
    if gk:
        return gk
    # Cookieless clients are grouped by IP+UA. This is approximate and may
    # merge people sharing a network or split visitors whose IP/UA changes.
    raw = _client_ip() + '|' + (request.headers.get('User-Agent', '') or '')
    gk = 'fp-' + hashlib.sha256(raw.encode('utf-8', 'ignore')).hexdigest()[:32]
    g._snyder_visitor_key = gk
    return gk


def _classify(path):
    """Classify a path via analytics_common, with a lazy store-slug lookup."""
    store_slug_to_id = None
    if (path or '').startswith('/store/book/'):
        conn = None
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
        except Exception:
            store_slug_to_id = None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    return classify_path(path, store_slug_to_id)


def _is_trackable_page(path):
    """Return False for storefront assets/actions that are not page views."""
    path = path or '/'
    if path.startswith('/store/image/'):
        return False
    if path in ('/store/subscribe', '/store/unsubscribe'):
        return False
    return True


def _eligible_public_html_request(response):
    """Only count a successful, public HTML page load—not every HTTP request."""
    path = request.path or '/'
    if request.method != 'GET':
        return False
    if response.status_code != 200 or response.mimetype != 'text/html':
        return False
    if path.startswith(('/static/', '/api/', '/admin')):
        return False
    if not _is_trackable_page(path):
        return False
    if session.get('admin_logged_in') is True:
        return False
    user_agent = request.headers.get('User-Agent', '')
    if not user_agent or BOT_RE.search(user_agent):
        return False
    if is_spam_referrer(request.referrer or ''):
        return False
    return True


def register(app):
    # Multiple startup paths (Gunicorn and the WSGI/CI entry point) must never
    # attach the canonical pageview writer twice to the same Flask app.
    if app.extensions.get("snyder_canonical_analytics_registered"):
        return

    # Record pageviews after Flask has generated the response. This prevents
    # redirects, 404/500 pages, POST actions, JSON/API responses, and maintenance
    # pages from inflating human pageview totals.
    @app.after_request
    def canonical_analytics_tracker(response):
        if not _eligible_public_html_request(response):
            return response

        path = request.path
        page_type, category, content_id = _classify(path)
        if category == 'kwsnyderwriting':
            try:
                from app import member_has_access
                if not member_has_access():
                    return response
            except Exception:
                return response

        visitor_key = _visitor_key()
        referrer = request.referrer or ''
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
            # Analytics must never break a customer's page load.
            pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        # Set a stable first-party identifier only for eligible public HTML
        # visits. Do not set analytics cookies on bots, API calls, errors, or
        # admin traffic.
        if not request.cookies.get('snyder_visitor_key'):
            response.set_cookie(
                'snyder_visitor_key', visitor_key, max_age=31536000,
                httponly=True, samesite='Lax', secure=True
            )
        return response
    app.extensions["snyder_canonical_analytics_registered"] = True

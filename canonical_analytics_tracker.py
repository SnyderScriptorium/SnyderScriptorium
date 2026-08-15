import re
import uuid
from flask import request, session
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
    ref = str(referrer or '').lower()
    if not ref:
        return 'Direct'
    for needle, name in (
        ('google.', 'Google'), ('bing.', 'Bing'), ('yahoo.', 'Yahoo'),
        ('duckduckgo.', 'DuckDuckGo'), ('facebook.', 'Facebook'),
        ('instagram.', 'Instagram'), ('pinterest.', 'Pinterest'),
        ('linkedin.', 'LinkedIn'), ('reddit.', 'Reddit'),
        ('youtube.', 'YouTube'), ('t.co', 'X / Twitter'),
        ('twitter.', 'X / Twitter'), ('x.com', 'X / Twitter'),
    ):
        if needle in ref:
            return name
    return 'Referral'


def _visitor_key():
    return request.cookies.get('snyder_visitor_key') or str(uuid.uuid4())


def _classify(path):
    page_type = 'page'
    category = 'site'
    content_id = None
    if path == '/':
        return 'page', 'site', None
    if path == '/about':
        return 'page', 'about', None
    if path == '/blog':
        return 'section', 'blog', None
    if path == '/blog/bookcurations':
        return 'section', 'curations', None
    if path == '/blog/bookreviews':
        return 'section', 'reviews', None
    if path == '/blog/curiosity_cabinet':
        return 'section', 'curiosity', None
    m = re.match(r'^/blog/post/(\d+)', path)
    if m:
        return 'post', 'public_post', int(m.group(1))
    if path == '/kwsnyderwriting':
        return 'member_section', 'kwsnyderwriting', None
    m = re.match(r'^/kwsnyderwriting/post/(\d+)', path)
    if m:
        return 'member_post', 'kwsnyderwriting', int(m.group(1))
    m = re.match(r'^/kwsnyderwriting/novel/(\d+)/chapter/(\d+)', path)
    if m:
        return 'chapter', 'kwsnyderwriting', int(m.group(2))
    m = re.match(r'^/kwsnyderwriting/novel/(\d+)', path)
    if m:
        return 'novel', 'kwsnyderwriting', int(m.group(1))
    return page_type, category, content_id


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
                'INSERT INTO page_views(path,page_type,content_id,category,visitor_key,referrer,traffic_source) VALUES (?,?,?,?,?,?,?)',
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

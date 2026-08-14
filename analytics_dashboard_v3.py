from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
from flask import jsonify, render_template, request, session
from database import get_db

EASTERN = ZoneInfo('America/New_York')
LABELS = {
    '/': 'Home',
    '/about': 'About',
    '/blog': 'Blog',
    '/blog/bookcurations': 'Book Curations',
    '/blog/bookreviews': 'Book Reviews',
    '/blog/curiosity_cabinet': 'Curiosity Cabinet',
    '/kwsnyderwriting': 'K. W. Snyder Writing',
    '/kwsnyderwriting/membership': 'K. W. Snyder Writing Membership',
}
CATEGORIES = {
    'curations': 'Book Curations',
    'reviews': 'Book Reviews',
    'curiosity': 'Curiosity Cabinet',
    'kwsnyderwriting': 'K. W. Snyder Writing',
    'kw_short_stories': 'K. W. Snyder Writing — Short Stories',
    'kw_poems': 'K. W. Snyder Writing — Poems',
    'kw_vignettes': 'K. W. Snyder Writing — Vignettes',
    'blog': 'Blog',
    'site': 'Home',
    'journal': 'K. W. Snyder Writing',
    'Journal': 'K. W. Snyder Writing',
}


def admin_ok():
    return session.get('admin_logged_in') is True and session.get('admin_auth_version') == '2026-08-10-3'


def start_for(period):
    now = datetime.now(EASTERN)
    if period in {'day', '1d', 'today'}:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == '7d':
        return now - timedelta(days=7)
    if period == '30d':
        return now - timedelta(days=30)
    if period == '90d':
        return now - timedelta(days=90)
    if period == '6m':
        return now - timedelta(days=182)
    if period == '1y':
        return now - timedelta(days=365)
    return None


def label(path, typ, cat, title):
    if path == '/':
        return 'Home'
    if cat in {'journal', 'Journal'} and typ in {'post', 'member_post'}:
        return str(title).strip() if title and str(title).strip() else 'K. W. Snyder Writing'
    if cat in {'site', 'journal', 'Journal'} and not title:
        return LABELS.get(path, 'Home' if path in {'', '/'} else 'Site Page')
    return str(title).strip() if title and str(title).strip() else LABELS.get(path, CATEGORIES.get(cat, {'post': 'Blog Post', 'member_post': 'K. W. Snyder Writing Post', 'novel': 'Novel', 'chapter': 'Book Chapter'}.get(typ, path or 'Site Page')))


def report(period):
    period = str(period or '30d').strip().lower()
    if period in {'day', '1', '1d', 'today'}:
        period = 'day'
    start = start_for(period)
    conn = get_db()
    where = ''
    params = []
    if start:
        where = ' WHERE pv.viewed_at >= ?'
        params = [start.isoformat()]
    try:
        total = conn.execute(f'SELECT COUNT(*) FROM page_views pv{where}', params).fetchone()[0]
        unique = conn.execute(f"SELECT COUNT(DISTINCT pv.visitor_key) FROM page_views pv{where}{' AND' if where else ' WHERE'} pv.visitor_key IS NOT NULL AND pv.visitor_key<>''", params).fetchone()[0]

        # Use Eastern local time for the Today chart so the user sees the actual
        # hours of today, not UTC hours from the Render server.
        daily = []
        rows = conn.execute(f'SELECT pv.viewed_at FROM page_views pv{where}', params).fetchall()
        buckets = {}
        for row in rows:
            raw = row[0]
            if isinstance(raw, datetime):
                dt = raw
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo('UTC'))
                local = dt.astimezone(EASTERN)
            else:
                text = str(raw).replace('Z', '+00:00')
                try:
                    dt = datetime.fromisoformat(text)
                except ValueError:
                    continue
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo('UTC'))
                local = dt.astimezone(EASTERN)
            key = local.strftime('%Y-%m-%dT%H:00') if period == 'day' else local.strftime('%Y-%m-%d')
            buckets[key] = buckets.get(key, 0) + 1
        for key in sorted(buckets):
            daily.append({'day': key, 'views': buckets[key], 'visitors': 0})

        rows = conn.execute(
            f"SELECT pv.path,pv.page_type,pv.content_id,pv.category,COALESCE(pp.title,mb.title,mc.title),COUNT(*),COUNT(DISTINCT pv.visitor_key) FROM page_views pv LEFT JOIN published_posts pp ON pp.id=pv.content_id AND pv.page_type IN ('post','member_post') LEFT JOIN manuscript_books mb ON mb.id=pv.content_id AND pv.page_type='novel' LEFT JOIN manuscript_chapters mc ON mc.id=pv.content_id AND pv.page_type='chapter'{where} GROUP BY pv.path,pv.page_type,pv.content_id,pv.category,pp.title,mb.title,mc.title ORDER BY 6 DESC,pv.path",
            params,
        ).fetchall()
        content = []
        for row in rows:
            raw_category = row[3]
            content.append({
                'title': label(row[0], row[1], raw_category, row[4]),
                'category': CATEGORIES.get(raw_category, 'K. W. Snyder Writing' if str(raw_category).lower() == 'journal' else (raw_category or 'Home')),
                'content_type': row[1],
                'views': int(row[5]),
                'unique_visitors': int(row[6]),
            })

        counts = {str(r[0] or 'inactive'): int(r[1]) for r in conn.execute('SELECT subscription_status,COUNT(*) FROM members GROUP BY subscription_status').fetchall()}
        return {
            'period': period,
            'total_views': int(total),
            'total_views_today': int(total) if period == 'day' else None,
            'unique_visitors': int(unique),
            'all_time_views': int(conn.execute('SELECT COUNT(*) FROM page_views').fetchone()[0]),
            'daily_views': daily,
            'content_views': content,
            'members': {
                'total': sum(counts.values()),
                'active': counts.get('active', 0),
                'past_due': counts.get('past_due', 0),
                'paused': counts.get('paused', 0),
                'cancelled': counts.get('cancelled', 0),
                'expired': counts.get('expired', 0),
                'inactive': counts.get('inactive', 0),
            },
        }
    finally:
        conn.close()


def register(app):
    @app.get('/admin/analytics')
    def analytics_dashboard_v3():
        if not admin_ok():
            return app.view_functions['admin_dashboard']()
        return render_template('analytics.html', **report(request.args.get('period', '30d')))

    @app.get('/api/analytics-v3')
    def analytics_api_v3():
        if not admin_ok():
            return jsonify({'error': 'Unauthorized'}), 401
        return jsonify(report(request.args.get('period', '30d')))

    @app.after_request
    def analytics_ui_v3(response):
        if request.path != '/admin/analytics' or 'text/html' not in response.content_type:
            return response
        text = response.get_data(as_text=True)
        nav = ''.join(f'<a href="/admin/analytics?period={k}">{v}</a>' for k, v in [('day', '1 Day — Today'), ('7d', '7 Days'), ('30d', '30 Days'), ('90d', '90 Days'), ('6m', '6 Months'), ('1y', '1 Year'), ('all', 'All Time')])
        text = re.sub(r'<nav class="periods".*?</nav>', f'<nav class="periods" aria-label="Analytics period">{nav}</nav>', text, flags=re.S)
        text = text.replace('Journal', 'K. W. Snyder Writing')
        text = text.replace('Homepage', 'Home')
        if request.args.get('period') in {'day', '1d', 'today', '1'}:
            text = text.replace('Views by day', 'Views by hour')
        response.set_data(text)
        return response

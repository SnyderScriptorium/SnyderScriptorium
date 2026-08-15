from datetime import datetime, timedelta, timezone
import re
import sys
import uuid

from flask import jsonify, render_template, request, session, g
from database import get_db, using_postgres

ADMIN_AUTH_VERSION = "2026-08-10-3"


def _admin_ok():
    return session.get("admin_logged_in") is True and session.get("admin_auth_version") == ADMIN_AUTH_VERSION


def _ensure_column(conn, table, column, definition):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_analytics_table():
    conn = get_db()
    try:
        if using_postgres():
            conn.execute("CREATE TABLE IF NOT EXISTS page_views (id BIGSERIAL PRIMARY KEY, path TEXT NOT NULL, page_type TEXT NOT NULL DEFAULT 'page', content_id BIGINT, category TEXT, viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, visitor_key TEXT, referrer TEXT, traffic_source TEXT)")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS visitor_key TEXT")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS referrer TEXT")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS traffic_source TEXT")
        else:
            conn.execute("CREATE TABLE IF NOT EXISTS page_views (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, page_type TEXT NOT NULL DEFAULT 'page', content_id INTEGER, category TEXT, viewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, visitor_key TEXT, referrer TEXT, traffic_source TEXT)")
            _ensure_column(conn, "page_views", "visitor_key", "TEXT")
            _ensure_column(conn, "page_views", "referrer", "TEXT")
            _ensure_column(conn, "page_views", "traffic_source", "TEXT")
        conn.commit()
    finally:
        conn.close()


def _label_for(category, supplied=None):
    supplied = str(supplied or '').strip()
    defaults = {'curations':'Book Curations','reviews':'Book Reviews','curiosity':'Curiosity Cabinet','kwsnyderwriting':'K. W. Snyder Writing','kw_short_stories':'K. W. Snyder Writing — Short Stories','kw_poems':'K. W. Snyder Writing — Poems','kw_vignettes':'K. W. Snyder Writing — Vignettes','blog':'The Blog','site':'Site Pages'}
    return supplied or defaults.get(category, 'Site Pages')


def _traffic_source(referrer):
    value = str(referrer or '').strip()
    if not value: return 'Direct'
    low = value.lower()
    for needle, label in [('google.','Google'),('bing.','Bing'),('yahoo.','Yahoo'),('duckduckgo.','DuckDuckGo'),('facebook.','Facebook'),('fb.','Facebook'),('instagram.','Instagram'),('pinterest.','Pinterest'),('t.co','X / Twitter'),('twitter.','X / Twitter'),('x.com','X / Twitter'),('linkedin.','LinkedIn'),('reddit.','Reddit'),('youtube.','YouTube')]:
        if needle in low: return label
    return 'Referral'


def _is_bot():
    ua = str(request.headers.get('User-Agent', '')).lower()
    if not ua: return False
    bot_words = ('bot','crawler','spider','slurp','bingpreview','facebookexternalhit','linkedinbot','pinterest','semrush','ahrefs','bytespider','petalbot','uptimerobot')
    return any(word in ua for word in bot_words)


def _visitor_key():
    key = str(request.cookies.get('ss_visitor') or '').strip()
    if key and len(key) <= 100: return key
    key = uuid.uuid4().hex; g.analytics_new_visitor_key = key; return key


def _enhanced_record_page_view(path, page_type='page', content_id=None, category=None):
    if path.startswith('/static/') or path.startswith('/api/') or path.startswith('/admin') or _is_bot(): return
    key = _visitor_key(); g.analytics_visitor_key = key
    referrer = str(request.headers.get('Referer', '') or '').strip()[:1000]
    source = _traffic_source(referrer)
    conn = None
    try:
        conn = get_db()
        conn.execute("INSERT INTO page_views(path, page_type, content_id, category, visitor_key, referrer, traffic_source) VALUES (?, ?, ?, ?, ?, ?, ?)", (path,page_type,content_id,category,key,referrer,source)); conn.commit()
    except Exception:
        if conn:
            try: conn.rollback()
            except Exception: pass
    finally:
        if conn: conn.close()


def _period_start(period):
    now=datetime.now(timezone.utc)
    if period in {'day','today'}: return now.replace(hour=0,minute=0,second=0,microsecond=0)
    if period in {'7d','7'}: return now-timedelta(days=7)
    if period in {'month','30'}: return now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    if period in {'3m','90'}:
        month=now.month-3; year=now.year
        while month<=0: month+=12; year-=1
        return now.replace(year=year,month=month,day=1,hour=0,minute=0,second=0,microsecond=0)
    if period in {'6m','180'}:
        month=now.month-6; year=now.year
        while month<=0: month+=12; year-=1
        return now.replace(year=year,month=month,day=1,hour=0,minute=0,second=0,microsecond=0)
    if period in {'1y','365'}: return now-timedelta(days=365)
    return None


def _day_expr(column): return f"substr(CAST({column} AS TEXT), 1, 10)"


def _analytics_report(period='month'):
    start=_period_start(period); conn=get_db()
    try:
        where=''; params=[]
        if start: where=' WHERE viewed_at >= ?'; params.append(start.isoformat())
        total_views=conn.execute(f'SELECT COUNT(*) FROM page_views{where}',params).fetchone()[0]
        unique_sql=f"SELECT COUNT(DISTINCT visitor_key) FROM page_views{where} AND visitor_key IS NOT NULL" if where else "SELECT COUNT(DISTINCT visitor_key) FROM page_views WHERE visitor_key IS NOT NULL"
        unique_visitors=conn.execute(unique_sql,params).fetchone()[0]
        daily_rows=conn.execute(f"SELECT {_day_expr('viewed_at')} AS day, COUNT(*) AS views, COUNT(DISTINCT visitor_key) AS visitors FROM page_views{where} GROUP BY day ORDER BY day",params).fetchall()
        content_rows=conn.execute(f"""SELECT pv.page_type AS content_type,pv.content_id,COALESCE(pp.title,mb.title,mc.title,NULLIF(pv.path,''),'Site Page') AS title,COALESCE(pv.category,'site') AS category,pv.path,COUNT(*) AS views,COUNT(DISTINCT pv.visitor_key) AS unique_visitors FROM page_views pv LEFT JOIN published_posts pp ON pp.id=pv.content_id AND pv.page_type IN ('post','member_post') LEFT JOIN manuscript_books mb ON mb.id=pv.content_id AND pv.page_type='novel' LEFT JOIN manuscript_chapters mc ON mc.id=pv.content_id AND pv.page_type='chapter' {where.replace('viewed_at','pv.viewed_at')} GROUP BY pv.page_type,pv.content_id,COALESCE(pp.title,mb.title,mc.title,NULLIF(pv.path,''),'Site Page'),COALESCE(pv.category,'site'),pv.path ORDER BY views DESC,title ASC""",params).fetchall()
        category_rows=conn.execute(f"SELECT COALESCE(category,'site') AS category,COUNT(*) AS views,COUNT(DISTINCT visitor_key) AS unique_visitors FROM page_views{where} GROUP BY COALESCE(category,'site') ORDER BY views DESC",params).fetchall()
        source_rows=conn.execute(f"SELECT COALESCE(NULLIF(traffic_source,''),'Direct') AS source,COUNT(*) AS views,COUNT(DISTINCT visitor_key) AS unique_visitors FROM page_views{where} GROUP BY COALESCE(NULLIF(traffic_source,''),'Direct') ORDER BY views DESC,source ASC",params).fetchall()
        member_rows=conn.execute("SELECT subscription_status,COUNT(*) AS count FROM members GROUP BY subscription_status").fetchall(); member_counts={str(row['subscription_status'] or 'inactive'):int(row['count']) for row in member_rows}; total_members=sum(member_counts.values())
        sub_where=''; sub_params=[]
        if start: sub_where=' WHERE date_started IS NOT NULL AND date_started >= ?'; sub_params.append(start.isoformat())
        new_count=int(conn.execute(f"SELECT COUNT(*) FROM subscriptions{sub_where}",sub_params).fetchone()[0])
        cancel_where=" WHERE status IN ('cancelled','expired') AND date_ends IS NOT NULL"; cancel_params=[]
        if start: cancel_where+=' AND date_ends >= ?'; cancel_params.append(start.isoformat())
        cancelled_count=int(conn.execute(f"SELECT COUNT(*) FROM subscriptions{cancel_where}",cancel_params).fetchone()[0])
        return {'period':period,'total_views':int(total_views),'unique_visitors':int(unique_visitors),'all_time_views':int(conn.execute('SELECT COUNT(*) FROM page_views').fetchone()[0]),'daily':[{'day':row['day'],'views':int(row['views']),'visitors':int(row['visitors'])} for row in daily_rows],'categories':[{'category':_label_for(row['category']),'raw_category':row['category'],'views':int(row['views']),'unique_visitors':int(row['unique_visitors'])} for row in category_rows],'posts':[{'content_type':row['content_type'],'content_id':row['content_id'],'title':row['title'],'category':_label_for(row['category']),'path':row['path'],'views':int(row['views']),'unique_visitors':int(row['unique_visitors'])} for row in content_rows],'traffic_sources':[{'source':row['source'],'views':int(row['views']),'unique_visitors':int(row['unique_visitors'])} for row in source_rows],'members':{'total':total_members,'active':member_counts.get('active',0),'past_due':member_counts.get('past_due',0),'paused':member_counts.get('paused',0),'cancelled':member_counts.get('cancelled',0),'expired':member_counts.get('expired',0),'inactive':member_counts.get('inactive',0)},'subscriptions':{'new':new_count,'cancelled_or_expired':cancelled_count}}
    finally: conn.close()


def _public_category(category,template,title,filter_name):
    conn=get_db(); labels=conn.execute("SELECT DISTINCT category_name FROM published_posts WHERE category = ? AND access_level = 'public' AND category_name IS NOT NULL AND TRIM(category_name) <> '' ORDER BY LOWER(category_name)",(category,)).fetchall(); selected=str(request.args.get(filter_name,'')).strip(); search=str(request.args.get('q','')).strip(); sql="SELECT * FROM published_posts WHERE category = ? AND access_level = 'public'"; params=[category]
    if selected: sql+=" AND category_name = ?"; params.append(selected)
    if search: sql+=" AND (LOWER(title) LIKE LOWER(?) OR LOWER(content) LIKE LOWER(?))"; like=f"%{search}%"; params.extend([like,like])
    posts=conn.execute(sql+" ORDER BY id DESC",params).fetchall(); conn.close(); return render_template(template,posts=posts,category_name=title,filter_labels=[row['category_name'] for row in labels],selected_label=selected,search_query=search)


def _create_published_post():
    if not _admin_ok(): return jsonify({'error':'Unauthorized'}),401
    data=request.get_json() or {}; title=str(data.get('title','')).strip(); category=str(data.get('category','')).strip(); content=str(data.get('content','')); access=str(data.get('accessLevel','public'))
    if not title or not content.strip(): return jsonify({'error':'A title and content are required.'}),400
    if category=='kwsnyderwriting' or category.startswith('kw_'): access='members'
    if access not in {'public','members'}: access='public'
    conn=get_db(); cur=conn.execute("INSERT INTO published_posts(title,category,category_name,content,date_published,access_level) VALUES (?,?,?,?,?,?)",(title,category,_label_for(category,data.get('categoryName')),content,str(data.get('date','')).strip() or datetime.now().strftime('%m/%d/%Y %I:%M %p'),access)); conn.commit(); post_id=cur.lastrowid; conn.close(); return jsonify({'success':True,'id':post_id,'access_level':access}),201


def _update_published_post(post_id):
    if not _admin_ok(): return jsonify({'error':'Unauthorized'}),401
    data=request.get_json() or {}; title=str(data.get('title','')).strip(); category=str(data.get('category','')).strip(); content=str(data.get('content','')); access=str(data.get('accessLevel','public'))
    if not title or not content.strip(): return jsonify({'error':'A title and content are required.'}),400
    if category=='kwsnyderwriting' or category.startswith('kw_'): access='members'
    if access not in {'public','members'}: access='public'
    conn=get_db(); row=conn.execute('SELECT id,category_name FROM published_posts WHERE id=?',(post_id,)).fetchone()
    if not row: conn.close(); return jsonify({'error':'Post not found'}),404
    label=_label_for(category,data.get('categoryName'))
    if not data.get('categoryName') and category==row['category_name']: label=row['category_name']
    conn.execute("UPDATE published_posts SET title=?,category=?,category_name=?,content=?,access_level=? WHERE id=?",(title,category,label,content,access,post_id)); conn.commit(); conn.close(); return jsonify({'success':True})


def register_site_enhancements(app):
    ensure_analytics_table()
    try:
        app_module=sys.modules.get('app')
        if app_module is not None: app_module.record_page_view=_enhanced_record_page_view
    except Exception: pass
    @app.after_request
    def set_analytics_visitor_cookie(response):
        key=getattr(g,'analytics_visitor_key',None)
        if key and not request.cookies.get('ss_visitor'): response.set_cookie('ss_visitor',key,max_age=60*60*24*365*2,httponly=True,samesite='Lax',secure=True)
        return response
    def analytics_api():
        if not _admin_ok(): return jsonify({'error':'Unauthorized'}),401
        return jsonify(_analytics_report(request.args.get('period','month')))
    app.view_functions['analytics_api']=analytics_api
    if 'analytics_api' not in app.url_map._rules_by_endpoint: app.add_url_rule('/api/analytics',endpoint='analytics_api',view_func=analytics_api,methods=['GET'])
    app.view_functions['bookreviews']=lambda:_public_category('reviews','blog_templates/bookreviews.html','Book Reviews','genre')
    app.view_functions['curiosity_cabinet']=lambda:_public_category('curiosity','blog_templates/curiosity_cabinet.html','Curiosity Cabinet','topic')
    app.view_functions['create_published_post']=_create_published_post
    app.view_functions['update_published_post']=_update_published_post

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
from flask import jsonify, render_template, request, session
from database import get_db

EASTERN = ZoneInfo('America/New_York')
LABELS = {'/':'Home','/about':'About','/blog':'Blog','/blog/bookcurations':'Book Curations','/blog/bookreviews':'Book Reviews','/blog/curiosity_cabinet':'Curiosity Cabinet','/kwsnyderwriting':'K. W. Snyder Writing','/kwsnyderwriting/membership':'K. W. Snyder Writing Membership'}
CATEGORIES = {'curations':'Book Curations','reviews':'Book Reviews','curiosity':'Curiosity Cabinet','kwsnyderwriting':'K. W. Snyder Writing','kw_short_stories':'K. W. Snyder Writing — Short Stories','kw_poems':'K. W. Snyder Writing — Poems','kw_vignettes':'K. W. Snyder Writing — Vignettes','blog':'Blog','site':'Home','journal':'K. W. Snyder Writing','Journal':'K. W. Snyder Writing'}

def admin_ok(): return session.get('admin_logged_in') is True and session.get('admin_auth_version') == '2026-08-10-3'

def start_for(period):
    now=datetime.now(EASTERN)
    if period in {'day','1d','today'}: return now.replace(hour=0,minute=0,second=0,microsecond=0)
    if period=='7d': return now-timedelta(days=7)
    if period=='30d': return now-timedelta(days=30)
    if period=='90d': return now-timedelta(days=90)
    if period=='6m': return now-timedelta(days=182)
    if period=='1y': return now-timedelta(days=365)
    return None

def rowval(row,index,key=None):
    if key is not None:
        try: return row[key]
        except (KeyError,TypeError,IndexError): pass
    try: return row[index]
    except (KeyError,TypeError,IndexError): return None

def label(path,typ,cat,title):
    if path=='/': return 'Home'
    if typ in {'post','member_post'} and title and str(title).strip(): return str(title).strip()
    if cat in {'site','journal','Journal'} and not title: return LABELS.get(path,'Home' if path in {'','/'} else 'Site Page')
    return str(title).strip() if title and str(title).strip() else LABELS.get(path,CATEGORIES.get(cat,{'post':'Blog Post','member_post':'K. W. Snyder Writing Post','novel':'Novel','chapter':'Book Chapter'}.get(typ,path or 'Site Page')))

def source_label(value,referrer=''):
    if value and str(value).strip(): return str(value).strip()
    ref=str(referrer or '').lower()
    if not ref: return 'Direct'
    for needle,name in [('google.','Google'),('bing.','Bing'),('yahoo.','Yahoo'),('duckduckgo.','DuckDuckGo'),('facebook.','Facebook'),('instagram.','Instagram'),('pinterest.','Pinterest'),('linkedin.','LinkedIn'),('reddit.','Reddit'),('youtube.','YouTube'),('t.co','X / Twitter'),('twitter.','X / Twitter'),('x.com','X / Twitter')]:
        if needle in ref: return name
    return 'Referral'

def report(period):
    period=str(period or '30d').strip().lower()
    if period in {'day','1','1d','today'}: period='day'
    start=start_for(period); conn=get_db(); where=''; params=[]
    if start: where=' WHERE pv.viewed_at >= ?'; params=[start.isoformat()]
    try:
        total=int(rowval(conn.execute(f'SELECT COUNT(*) AS total FROM page_views pv{where}',params).fetchone(),0,'total'))
        unique=int(rowval(conn.execute(f"SELECT COUNT(DISTINCT pv.visitor_key) AS unique_visitors FROM page_views pv{where}{' AND' if where else ' WHERE'} pv.visitor_key IS NOT NULL AND pv.visitor_key<>''",params).fetchone(),0,'unique_visitors'))
        rows=conn.execute(f'SELECT pv.viewed_at AS viewed_at,pv.visitor_key AS visitor_key FROM page_views pv{where}',params).fetchall(); buckets={}; visitor_buckets={}
        for row in rows:
            raw=rowval(row,0,'viewed_at')
            if isinstance(raw,datetime): dt=raw
            else:
                try: dt=datetime.fromisoformat(str(raw).replace('Z','+00:00'))
                except ValueError: continue
            if dt.tzinfo is None: dt=dt.replace(tzinfo=ZoneInfo('UTC'))
            local=dt.astimezone(EASTERN); key=local.strftime('%Y-%m-%dT%H:00') if period=='day' else local.strftime('%Y-%m-%d')
            buckets[key]=buckets.get(key,0)+1; visitor_buckets.setdefault(key,set()).add(str(rowval(row,1,'visitor_key') or ''))
        daily=[{'day':k,'views':buckets[k],'visitors':len(visitor_buckets.get(k,set())- {''})} for k in sorted(buckets)]
        rows=conn.execute(f"SELECT pv.path AS path,pv.page_type AS page_type,pv.content_id AS content_id,pv.category AS category,COALESCE(pp.title,mb.title,mc.title) AS title,COUNT(*) AS views,COUNT(DISTINCT pv.visitor_key) AS unique_visitors FROM page_views pv LEFT JOIN published_posts pp ON pp.id=pv.content_id AND pv.page_type IN ('post','member_post') LEFT JOIN manuscript_books mb ON mb.id=pv.content_id AND pv.page_type='novel' LEFT JOIN manuscript_chapters mc ON mc.id=pv.content_id AND pv.page_type='chapter'{where} GROUP BY pv.path,pv.page_type,pv.content_id,pv.category,pp.title,mb.title,mc.title ORDER BY views DESC,pv.path",params).fetchall()
        content=[]
        for row in rows:
            path=rowval(row,0,'path'); typ=rowval(row,1,'page_type'); cat=rowval(row,3,'category'); title=rowval(row,4,'title')
            content.append({'title':label(path,typ,cat,title),'category':CATEGORIES.get(cat,'K. W. Snyder Writing' if str(cat).lower()=='journal' else (cat or 'Home')),'content_type':typ,'views':int(rowval(row,5,'views') or 0),'unique_visitors':int(rowval(row,6,'unique_visitors') or 0),'path':path})
        src_rows=conn.execute(f"SELECT traffic_source AS source,referrer AS referrer,COUNT(*) AS views,COUNT(DISTINCT visitor_key) AS unique_visitors FROM page_views pv{where} GROUP BY traffic_source,referrer ORDER BY views DESC",params).fetchall(); sources={}
        for row in src_rows:
            name=source_label(rowval(row,0,'source'),rowval(row,1,'referrer')); bucket=sources.setdefault(name,{'source':name,'views':0,'unique_visitors':set()}); bucket['views']+=int(rowval(row,2,'views') or 0)
        source_unique_rows=conn.execute(f"SELECT visitor_key,traffic_source,referrer FROM page_views pv{where} AND visitor_key IS NOT NULL" if where else "SELECT visitor_key,traffic_source,referrer FROM page_views pv WHERE visitor_key IS NOT NULL",params).fetchall()
        unique_by_source={}
        for row in source_unique_rows: unique_by_source.setdefault(source_label(rowval(row,1,'traffic_source'),rowval(row,2,'referrer')),set()).add(str(rowval(row,0,'visitor_key')))
        traffic_sources=[{'source':name,'views':data['views'],'unique_visitors':len(unique_by_source.get(name,set()))} for name,data in sorted(sources.items(),key=lambda x:(-x[1]['views'],x[0]))]
        counts={str(rowval(r,0,'subscription_status') or 'inactive'):int(rowval(r,1,'count') or 0) for r in conn.execute('SELECT subscription_status,COUNT(*) AS count FROM members GROUP BY subscription_status').fetchall()}
        new_last_30=int(rowval(conn.execute("SELECT COUNT(*) AS count FROM members WHERE created_at IS NOT NULL AND created_at >= ?",[(datetime.now(EASTERN)-timedelta(days=30)).isoformat()]).fetchone(),0,'count') or 0)
        sub_params=[]; sub_where=''
        if start: sub_where=' WHERE date_started IS NOT NULL AND date_started >= ?'; sub_params=[start.isoformat()]
        new_subs=int(rowval(conn.execute(f'SELECT COUNT(*) AS count FROM subscriptions{sub_where}',sub_params).fetchone(),0,'count') or 0)
        cancel_where=" WHERE status IN ('cancelled','expired') AND date_ends IS NOT NULL"; cancel_params=[]
        if start: cancel_where+=' AND date_ends >= ?'; cancel_params=[start.isoformat()]
        cancelled=int(rowval(conn.execute(f'SELECT COUNT(*) AS count FROM subscriptions{cancel_where}',cancel_params).fetchone(),0,'count') or 0)
        all_time=int(rowval(conn.execute('SELECT COUNT(*) AS total FROM page_views').fetchone(),0,'total'))
        return {'period':period,'total_views':total,'total_views_today':total if period=='day' else None,'unique_visitors':unique,'all_time_views':all_time,'daily_views':daily,'content_views':content,'traffic_sources':traffic_sources,'members':{'total':sum(counts.values()),'active':counts.get('active',0),'past_due':counts.get('past_due',0),'paused':counts.get('paused',0),'cancelled':counts.get('cancelled',0),'expired':counts.get('expired',0),'inactive':counts.get('inactive',0),'new_last_30_days':new_last_30},'subscription_activity':{'new':new_subs,'cancelled_or_expired':cancelled}}
    finally: conn.close()

def register(app):
    @app.get('/admin/analytics')
    def analytics_dashboard_v3():
        if not admin_ok(): return app.view_functions['admin_dashboard']()
        return render_template('analytics.html',**report(request.args.get('period','30d')))
    @app.get('/api/analytics-v3')
    def analytics_api_v3():
        if not admin_ok(): return jsonify({'error':'Unauthorized'}),401
        return jsonify(report(request.args.get('period','30d')))
    @app.after_request
    def analytics_ui_v3(response):
        if request.path!='/admin/analytics' or 'text/html' not in response.content_type: return response
        text=response.get_data(as_text=True); nav=''.join(f'<a href="/admin/analytics?period={k}">{v}</a>' for k,v in [('day','1 Day — Today'),('7d','7 Days'),('30d','30 Days'),('90d','90 Days'),('6m','6 Months'),('1y','1 Year'),('all','All Time')]); text=re.sub(r'<nav class="periods".*?</nav>',f'<nav class="periods" aria-label="Analytics period">{nav}</nav>',text,flags=re.S); text=text.replace('Journal','K. W. Snyder Writing').replace('Homepage','Home')
        if request.args.get('period') in {'day','1d','today','1'}: text=text.replace('Views by day','Views by hour')
        return response.set_data(text) or response

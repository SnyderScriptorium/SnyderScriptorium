from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
from flask import jsonify, render_template, request, session, redirect
from database import get_db

EASTERN = ZoneInfo('America/New_York')
LABELS = {'/':'Home','/about':'About','/blog':'Blog','/blog/bookcurations':'Book Curations','/blog/bookreviews':'Book Reviews','/blog/curiosity_cabinet':'Curiosity Cabinet','/kwsnyderwriting':'K. W. Snyder Writing','/kwsnyderwriting/membership':'K. W. Snyder Writing Membership','/contact':'Contact','/store':'The Scriptorium Book Store','/merch':'Scriptorium Merch Shop','/membership-terms':'Membership Terms'}
CATEGORIES = {'curations':'Book Curations','reviews':'Book Reviews','curiosity':'Curiosity Cabinet','kwsnyderwriting':'K. W. Snyder Writing','kw_short_stories':'K. W. Snyder Writing — Short Stories','kw_poems':'K. W. Snyder Writing — Poems','kw_vignettes':'K. W. Snyder Writing — Vignettes','blog':'Blog','site':'Home','journal':'K. W. Snyder Writing','Journal':'K. W. Snyder Writing'}
PAGE_SIZE=25

def admin_ok():
    try:
        from app import require_admin
        return require_admin()
    except Exception: return False

def normalize_period(period):
    return {'1':'day','1d':'day','day':'day','today':'day','7':'7d','7d':'7d','30':'30d','30d':'30d','90':'90d','90d':'90d','6':'6m','6m':'6m','12':'1y','1y':'1y','365':'1y','365d':'1y','all':'all','alltime':'all','all-time':'all'}.get(str(period or '30d').strip().lower(),'30d')

def start_for(period):
    now=datetime.now(EASTERN)
    if period=='day': return now.replace(hour=0,minute=0,second=0,microsecond=0)
    if period=='7d': return now-timedelta(days=7)
    if period=='30d': return now-timedelta(days=30)
    if period=='90d': return now-timedelta(days=90)
    if period=='6m': return now-timedelta(days=182)
    if period=='1y': return now-timedelta(days=365)
    return None

def rowval(row,index,key=None):
    if key is not None:
        try:return row[key]
        except (KeyError,TypeError,IndexError):pass
    try:return row[index]
    except (KeyError,TypeError,IndexError):return None

def clean_path(path):
    value=str(path or '').split('?',1)[0].rstrip('/')
    return value or '/'

def pretty_path(path):
    parts=[p for p in clean_path(path).split('/') if p]
    return re.sub(r'[-_]+',' ',parts[-1]).strip().title() if parts else 'Home'

def label(path,typ,cat,title):
    path=clean_path(path)
    if title and str(title).strip():return str(title).strip()
    if path in LABELS:return LABELS[path]
    if path.startswith('/blog/post/'):return 'Blog Post'
    if path.startswith('/kwsnyderwriting/post/'):return 'K. W. Snyder Writing Post'
    if '/kwsnyderwriting/novel/' in path and '/chapter/' in path:return 'Book Chapter'
    if '/kwsnyderwriting/novel/' in path:return 'Novel'
    if str(cat) in {'site','journal','Journal'}:return 'K. W. Snyder Writing' if str(cat).lower()=='journal' else 'Home'
    return CATEGORIES.get(str(cat),pretty_path(path))

def source_label(value,referrer=''):
    if value and str(value).strip():return str(value).strip()
    ref=str(referrer or '').lower()
    if not ref:return 'Direct'
    for needle,name in [('google.','Google'),('bing.','Bing'),('yahoo.','Yahoo'),('duckduckgo.','DuckDuckGo'),('facebook.','Facebook'),('instagram.','Instagram'),('pinterest.','Pinterest'),('linkedin.','LinkedIn'),('reddit.','Reddit'),('youtube.','YouTube'),('t.co','X / Twitter'),('twitter.','X / Twitter'),('x.com','X / Twitter')]:
        if needle in ref:return name
    return 'Referral'

def build_time_buckets(period,buckets,visitor_buckets):
    now=datetime.now(EASTERN)
    if period=='all':return sorted(buckets)
    if period=='day':
        start=now.replace(hour=0,minute=0,second=0,microsecond=0)
        return [(start+timedelta(hours=i)).strftime('%Y-%m-%dT%H:00') for i in range(24)]
    start=start_for(period).astimezone(EASTERN).replace(hour=0,minute=0,second=0,microsecond=0); end=now.replace(hour=0,minute=0,second=0,microsecond=0); keys=[]; current=start
    while current<=end:keys.append(current.strftime('%Y-%m-%d'));current+=timedelta(days=1)
    return keys

def chart_scale(max_value):
    max_value=max(0,int(max_value or 0))
    step=50
    chart_max=max(step,((max_value+step-1)//step)*step) if max_value else step
    return chart_max,list(range(0,chart_max+1,step))

def paginate(items,page):
    try:page=max(1,int(page))
    except (TypeError,ValueError):page=1
    total=len(items);pages=max(1,(total+PAGE_SIZE-1)//PAGE_SIZE);page=min(page,pages);start=(page-1)*PAGE_SIZE
    return items[start:start+PAGE_SIZE],page,pages,total

def report(period,content_page=1,source_page=1):
    period=normalize_period(period);start=start_for(period);conn=get_db();where='';params=[]
    if start:where=' WHERE pv.viewed_at >= ?';params=[start.isoformat()]
    try:
        total=int(rowval(conn.execute(f'SELECT COUNT(*) AS total FROM page_views pv{where}',params).fetchone(),0,'total'))
        unique=int(rowval(conn.execute(f"SELECT COUNT(DISTINCT pv.visitor_key) AS unique_visitors FROM page_views pv{where}{' AND' if where else ' WHERE'} pv.visitor_key IS NOT NULL AND pv.visitor_key<>''",params).fetchone(),0,'unique_visitors'))
        rows=conn.execute(f'SELECT pv.viewed_at AS viewed_at,pv.visitor_key AS visitor_key FROM page_views pv{where}',params).fetchall();buckets={};visitor_buckets={}
        for row in rows:
            raw=rowval(row,0,'viewed_at')
            try:dt=raw if isinstance(raw,datetime) else datetime.fromisoformat(str(raw).replace('Z','+00:00'))
            except ValueError:continue
            if dt.tzinfo is None:dt=dt.replace(tzinfo=ZoneInfo('UTC'))
            local=dt.astimezone(EASTERN);key=local.strftime('%Y-%m-%dT%H:00') if period=='day' else local.strftime('%Y-%m-%d');buckets[key]=buckets.get(key,0)+1;visitor_buckets.setdefault(key,set()).add(str(rowval(row,1,'visitor_key') or ''))
        daily=[{'day':k,'views':buckets.get(k,0),'visitors':len(visitor_buckets.get(k,set())-{''})} for k in build_time_buckets(period,buckets,visitor_buckets)];chart_max,chart_ticks=chart_scale(max((x['views'] for x in daily),default=0))
        rows=conn.execute(f"""SELECT pv.path AS path,pv.page_type AS page_type,pv.content_id AS content_id,pv.category AS category,COALESCE(pp.title,mb.title,mc.title) AS title,COUNT(*) AS views,COUNT(DISTINCT pv.visitor_key) AS unique_visitors FROM page_views pv LEFT JOIN published_posts pp ON pp.id=pv.content_id AND (pv.page_type IN ('post','member_post') OR pv.path LIKE '/blog/post/%' OR pv.path LIKE '/kwsnyderwriting/post/%') LEFT JOIN manuscript_books mb ON mb.id=pv.content_id AND (pv.page_type='novel' OR pv.path LIKE '/kwsnyderwriting/novel/%') AND pv.path NOT LIKE '%/chapter/%' LEFT JOIN manuscript_chapters mc ON mc.id=pv.content_id AND (pv.page_type='chapter' OR pv.path LIKE '/kwsnyderwriting/novel/%/chapter/%') {where} GROUP BY pv.path,pv.page_type,pv.content_id,pv.category,pp.title,mb.title,mc.title ORDER BY views DESC,pv.path""",params).fetchall()
        content=[]
        for row in rows:
            path=clean_path(rowval(row,0,'path'));typ=rowval(row,1,'page_type');cat=rowval(row,3,'category');title=rowval(row,4,'title');effective=typ
            if path.startswith('/blog/post/'):effective='post'
            elif path.startswith('/kwsnyderwriting/post/'):effective='member_post'
            elif '/kwsnyderwriting/novel/' in path and '/chapter/' in path:effective='chapter'
            elif '/kwsnyderwriting/novel/' in path:effective='novel'
            content.append({'title':label(path,effective,cat,title),'category':CATEGORIES.get(cat,'K. W. Snyder Writing' if str(cat).lower()=='journal' else (cat or LABELS.get(path,'Home'))),'content_type':effective,'views':int(rowval(row,5,'views') or 0),'unique_visitors':int(rowval(row,6,'unique_visitors') or 0),'path':path})
        content_page_items,content_page,content_pages,content_total=paginate(content,content_page)
        source_rows=conn.execute(f"SELECT traffic_source AS source,referrer AS referrer,COUNT(*) AS views,COUNT(DISTINCT visitor_key) AS unique_visitors FROM page_views pv{where} GROUP BY traffic_source,referrer ORDER BY views DESC,referrer",params).fetchall();details=[];source_totals={}
        for row in source_rows:
            name=source_label(rowval(row,0,'source'),rowval(row,1,'referrer'));ref=str(rowval(row,1,'referrer') or '').strip() or ('No referrer recorded (direct/bookmark or privacy-hidden referrer)' if name=='Direct' else 'Referrer not recorded');views=int(rowval(row,2,'views') or 0);uv=int(rowval(row,3,'unique_visitors') or 0);details.append({'source':name,'referrer':ref,'views':views,'unique_visitors':uv});source_totals[name]=source_totals.get(name,0)+views
        source_page_items,source_page,source_pages,source_total=paginate(details,source_page)
        traffic_sources=[{'source':n,'views':v} for n,v in sorted(source_totals.items(),key=lambda x:(-x[1],x[0]))]
        counts={str(rowval(r,0,'subscription_status') or 'inactive'):int(rowval(r,1,'count') or 0) for r in conn.execute('SELECT subscription_status,COUNT(*) AS count FROM members GROUP BY subscription_status').fetchall()};new_last_30=int(rowval(conn.execute('SELECT COUNT(*) AS count FROM members WHERE date_created IS NOT NULL AND date_created >= ?',[ (datetime.now(EASTERN)-timedelta(days=30)).isoformat()]).fetchone(),0,'count') or 0)
        sub_params=[];sub_where=''
        if start:sub_where=' WHERE date_started IS NOT NULL AND date_started >= ?';sub_params=[start.isoformat()]
        new_subs=int(rowval(conn.execute(f'SELECT COUNT(*) AS count FROM subscriptions{sub_where}',sub_params).fetchone(),0,'count') or 0);cancel_where=" WHERE status IN ('cancelled','expired') AND date_ends IS NOT NULL";cancel_params=[]
        if start:cancel_where+=' AND date_ends >= ?';cancel_params=[start.isoformat()]
        cancelled=int(rowval(conn.execute(f'SELECT COUNT(*) AS count FROM subscriptions{cancel_where}',cancel_params).fetchone(),0,'count') or 0);all_time=int(rowval(conn.execute('SELECT COUNT(*) AS total FROM page_views').fetchone(),0,'total'))
        return {'period':period,'total_views':total,'total_views_today':total if period=='day' else None,'unique_visitors':unique,'all_time_views':all_time,'daily_views':daily,'chart_max':chart_max,'chart_ticks':chart_ticks,'content_views':content_page_items,'content_pagination':{'page':content_page,'pages':content_pages,'total':content_total},'traffic_sources':traffic_sources,'source_details':source_page_items,'source_pagination':{'page':source_page,'pages':source_pages,'total':source_total},'members':{'total':sum(counts.values()),'active':counts.get('active',0),'past_due':counts.get('past_due',0),'paused':counts.get('paused',0),'cancelled':counts.get('cancelled',0),'expired':counts.get('expired',0),'inactive':counts.get('inactive',0),'new_last_30_days':new_last_30},'subscription_activity':{'new':new_subs,'cancelled_or_expired':cancelled}}
    finally:conn.close()

def register(app):
    @app.get('/admin/analytics')
    def analytics_dashboard_v3():
        if not admin_ok():return redirect('/admin/login')
        return render_template('analytics.html',**report(request.args.get('period','30d'),request.args.get('content_page',1),request.args.get('source_page',1)),tab=request.args.get('tab','overview'))
    @app.get('/api/analytics-v3')
    def analytics_api_v3():
        if not admin_ok():return jsonify({'error':'Unauthorized'}),401
        return jsonify(report(request.args.get('period','30d'),request.args.get('content_page',1),request.args.get('source_page',1)))
    @app.after_request
    def analytics_ui_v3(response):
        if request.path!='/admin/analytics' or 'text/html' not in response.content_type:return response
        text=response.get_data(as_text=True);nav=''.join(f'<a href="/admin/analytics?period={k}&tab={request.args.get("tab","overview")}">{v}</a>' for k,v in [('day','1 Day — Today'),('7d','7 Days'),('30d','30 Days'),('90d','90 Days'),('6m','6 Months'),('1y','1 Year'),('all','All Time')]);text=re.sub(r'<nav class="periods".*?</nav>',f'<nav class="periods" aria-label="Analytics period">{nav}</nav>',text,flags=re.S);text=text.replace('Journal','K. W. Snyder Writing').replace('Homepage','Home')
        if request.args.get('period') in {'day','1d','today','1'}:text=text.replace('Views by day','Views by hour')
        response.set_data(text);return response
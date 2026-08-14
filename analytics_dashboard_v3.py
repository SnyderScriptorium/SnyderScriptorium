from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
from flask import jsonify, render_template, request, session
from database import get_db
EASTERN=ZoneInfo('America/New_York')
LABELS={'/':'Homepage','/about':'About','/blog':'Blog','/blog/bookcurations':'Book Curations','/blog/bookreviews':'Book Reviews','/blog/curiosity_cabinet':'Curiosity Cabinet','/kwsnyderwriting':'K. W. Snyder Writing','/kwsnyderwriting/membership':'K. W. Snyder Writing Membership'}
CATEGORIES={'curations':'Book Curations','reviews':'Book Reviews','curiosity':'Curiosity Cabinet','kwsnyderwriting':'K. W. Snyder Writing','kw_short_stories':'K. W. Snyder Writing — Short Stories','kw_poems':'K. W. Snyder Writing — Poems','kw_vignettes':'K. W. Snyder Writing — Vignettes','blog':'Blog','site':'Site Pages'}
def admin_ok(): return session.get('admin_logged_in') is True and session.get('admin_auth_version')=='2026-08-10-3'
def start_for(p):
 n=datetime.now(EASTERN)
 if p in {'day','1d','today'}: return n.replace(hour=0,minute=0,second=0,microsecond=0)
 if p=='7d': return n-timedelta(days=7)
 if p=='30d': return n-timedelta(days=30)
 if p=='90d': return n-timedelta(days=90)
 if p=='6m': return n-timedelta(days=182)
 if p=='1y': return n-timedelta(days=365)
 return None
def label(path,typ,cat,title): return str(title).strip() if title and str(title).strip() else LABELS.get(path,CATEGORIES.get(cat,{'post':'Blog Post','member_post':'K. W. Snyder Writing Post','novel':'Novel','chapter':'Book Chapter'}.get(typ,path or 'Site Page')))
def report(p):
 s=start_for(p); c=get_db(); w=''; q=[]
 if s: w=' WHERE pv.viewed_at >= ?'; q=[s.isoformat()]
 try:
  total=c.execute(f'SELECT COUNT(*) FROM page_views pv{w}',q).fetchone()[0]
  uq=c.execute(f"SELECT COUNT(DISTINCT pv.visitor_key) FROM page_views pv{w}{' AND' if w else ' WHERE'} pv.visitor_key IS NOT NULL AND pv.visitor_key<>''",q).fetchone()[0]
  if p in {'day','1d','today'}: rs=c.execute(f"SELECT substr(CAST(pv.viewed_at AS TEXT),1,13),COUNT(*),COUNT(DISTINCT pv.visitor_key) FROM page_views pv{w} GROUP BY 1 ORDER BY 1",q).fetchall(); daily=[{'day':str(r[0])+':00','views':int(r[1]),'visitors':int(r[2])} for r in rs]
  else: rs=c.execute(f"SELECT substr(CAST(pv.viewed_at AS TEXT),1,10),COUNT(*),COUNT(DISTINCT pv.visitor_key) FROM page_views pv{w} GROUP BY 1 ORDER BY 1",q).fetchall(); daily=[{'day':r[0],'views':int(r[1]),'visitors':int(r[2])} for r in rs]
  rs=c.execute(f"SELECT pv.path,pv.page_type,pv.content_id,pv.category,COALESCE(pp.title,mb.title,mc.title),COUNT(*),COUNT(DISTINCT pv.visitor_key) FROM page_views pv LEFT JOIN published_posts pp ON pp.id=pv.content_id AND pv.page_type IN ('post','member_post') LEFT JOIN manuscript_books mb ON mb.id=pv.content_id AND pv.page_type='novel' LEFT JOIN manuscript_chapters mc ON mc.id=pv.content_id AND pv.page_type='chapter'{w} GROUP BY pv.path,pv.page_type,pv.content_id,pv.category,pp.title,mb.title,mc.title ORDER BY 6 DESC,pv.path",q).fetchall()
  content=[{'title':label(r[0],r[1],r[3],r[4]),'category':CATEGORIES.get(r[3],r[3] or 'Site Pages'),'content_type':r[1],'views':int(r[5]),'unique_visitors':int(r[6])} for r in rs]
  mc={str(r[0] or 'inactive'):int(r[1]) for r in c.execute('SELECT subscription_status,COUNT(*) FROM members GROUP BY subscription_status').fetchall()}
  return {'period':p,'total_views':int(total),'unique_visitors':int(uq),'all_time_views':int(c.execute('SELECT COUNT(*) FROM page_views').fetchone()[0]),'daily_views':daily,'content_views':content,'members':{'total':sum(mc.values()),'active':mc.get('active',0),'past_due':mc.get('past_due',0),'paused':mc.get('paused',0),'cancelled':mc.get('cancelled',0),'expired':mc.get('expired',0),'inactive':mc.get('inactive',0)}}
 finally: c.close()
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
  text=response.get_data(as_text=True)
  nav=''.join(f'<a href="/admin/analytics?period={k}">{v}</a>' for k,v in [('day','1 Day — Today'),('7d','7 Days'),('30d','30 Days'),('90d','90 Days'),('6m','6 Months'),('1y','1 Year'),('all','All Time')])
  text=re.sub(r'<nav class="periods".*?</nav>',f'<nav class="periods" aria-label="Analytics period">{nav}</nav>',text,flags=re.S)
  if request.args.get('period') in {'day','1d','today'}: text=text.replace('Views by day','Views by hour')
  text=text.replace('Journal','Site Pages')
  response.set_data(text); return response

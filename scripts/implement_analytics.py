from pathlib import Path
import re


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"{label} marker not found")
    return text.replace(old, new, 1)


def update_app():
    p = Path("app.py")
    s = p.read_text()

    if "def record_page_view(" not in s:
        marker = "def category_label(category):\n"
        helper = '''def record_page_view(path, page_type="page", content_id=None, category=None):
    """Persist a visitor view without allowing analytics failures to break the site."""
    if path.startswith("/static/") or path.startswith("/api/") or path.startswith("/admin"):
        return
    conn = None
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO page_views(path, page_type, content_id, category) VALUES (?, ?, ?, ?)",
            (path, page_type, content_id, category),
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


def category_label(category):
'''
        s = replace_once(s, marker, helper, "analytics helper")

    if "def analytics_request_tracker():" not in s:
        marker = "@app.route(\"/\")\ndef the_hearth():\n"
        tracker = '''@app.before_request
def analytics_request_tracker():
    path = request.path
    if path.startswith("/static/") or path.startswith("/api/") or path.startswith("/admin"):
        return None

    page_type = "page"
    category = None
    content_id = None

    if path == "/blog":
        page_type, category = "section", "blog"
    elif path.startswith("/blog/bookcurations"):
        page_type, category = "section", "curations"
    elif path.startswith("/blog/bookreviews"):
        page_type, category = "section", "reviews"
    elif path.startswith("/blog/curiosity_cabinet"):
        page_type, category = "section", "curiosity"
    elif path.startswith("/blog/post/"):
        match = re.match(r"^/blog/post/(\\d+)", path)
        if match:
            page_type, content_id = "post", int(match.group(1))
    elif path == "/kwsnyderwriting":
        if not member_has_access():
            return None
        page_type, category = "member_section", "kwsnyderwriting"
    elif path.startswith("/kwsnyderwriting/post/"):
        if not member_has_access():
            return None
        match = re.match(r"^/kwsnyderwriting/post/(\\d+)", path)
        if match:
            page_type, content_id, category = "member_post", int(match.group(1)), "kwsnyderwriting"
    elif path.startswith("/kwsnyderwriting/novel/") and "/chapter/" not in path:
        if not member_has_access():
            return None
        match = re.match(r"^/kwsnyderwriting/novel/(\\d+)", path)
        if match:
            page_type, content_id, category = "novel", int(match.group(1)), "kwsnyderwriting"
    elif "/kwsnyderwriting/novel/" in path and "/chapter/" in path:
        if not member_has_access():
            return None
        match = re.match(r"^/kwsnyderwriting/novel/(\\d+)/chapter/(\\d+)", path)
        if match:
            page_type, content_id, category = "chapter", int(match.group(2)), "kwsnyderwriting"
    else:
        category = "site"

    record_page_view(path, page_type, content_id, category)
    return None


@app.route("/")
def the_hearth():
'''
        s = replace_once(s, marker, tracker, "analytics request tracker")

    if "def get_analytics():" not in s:
        marker = '@app.route("/api/drafts", methods=["GET"])\n'
        analytics = '''@app.route("/api/analytics", methods=["GET"])
@admin_required
def get_analytics():
    from datetime import timedelta, timezone

    period = request.args.get("period", "30")
    now = datetime.now(timezone.utc)
    if period == "all":
        start = None
    else:
        try:
            days = max(1, min(int(period), 3650))
        except (TypeError, ValueError):
            days = 30
        start = now - timedelta(days=days)

    conn = get_db()
    if start is None:
        total = conn.execute("SELECT COUNT(*) AS count FROM page_views").fetchone()["count"]
        daily = conn.execute("SELECT DATE(viewed_at) AS day, COUNT(*) AS views FROM page_views GROUP BY DATE(viewed_at) ORDER BY day").fetchall()
        categories = conn.execute("SELECT category, COUNT(*) AS views FROM page_views WHERE category IS NOT NULL GROUP BY category ORDER BY views DESC").fetchall()
        posts = conn.execute("""SELECT pv.path, pv.content_id, pv.category, COALESCE(pp.title, pv.path) AS title, COUNT(*) AS views
            FROM page_views pv LEFT JOIN published_posts pp ON pp.id = pv.content_id
            WHERE pv.page_type IN ('post', 'member_post', 'chapter', 'novel')
            GROUP BY pv.path, pv.content_id, pv.category, pp.title ORDER BY views DESC""").fetchall()
    else:
        stamp = start.isoformat()
        total = conn.execute("SELECT COUNT(*) AS count FROM page_views WHERE viewed_at >= ?", (stamp,)).fetchone()["count"]
        daily = conn.execute("SELECT DATE(viewed_at) AS day, COUNT(*) AS views FROM page_views WHERE viewed_at >= ? GROUP BY DATE(viewed_at) ORDER BY day", (stamp,)).fetchall()
        categories = conn.execute("SELECT category, COUNT(*) AS views FROM page_views WHERE category IS NOT NULL AND viewed_at >= ? GROUP BY category ORDER BY views DESC", (stamp,)).fetchall()
        posts = conn.execute("""SELECT pv.path, pv.content_id, pv.category, COALESCE(pp.title, pv.path) AS title, COUNT(*) AS views
            FROM page_views pv LEFT JOIN published_posts pp ON pp.id = pv.content_id
            WHERE pv.viewed_at >= ? AND pv.page_type IN ('post', 'member_post', 'chapter', 'novel')
            GROUP BY pv.path, pv.content_id, pv.category, pp.title ORDER BY views DESC""", (stamp,)).fetchall()
    conn.close()

    return jsonify({
        "period": period,
        "total_views": total,
        "daily": [dict(row) for row in daily],
        "categories": [dict(row) for row in categories],
        "posts": [dict(row) for row in posts],
    })


@app.route("/api/drafts", methods=["GET"])
'''
        s = replace_once(s, marker, analytics, "analytics API")

    p.write_text(s)


def update_admin():
    p = Path("templates/admin.html")
    s = p.read_text()

    old = '''<section id="stats" class="hidden"><h2 class="section-title">Analytics</h2><div class="three"><div class="card"><div><h3>Drafts</h3><small>Saved writing</small></div><strong id="statDrafts">0</strong></div><div class="card"><div><h3>Published</h3><small>Live posts</small></div><strong id="statPublished">0</strong></div><div class="card"><div><h3>Novels</h3><small>Manuscript books</small></div><strong id="statBooks">0</strong></div></div><p class="note" style="margin-top:18px">Content counts are database-backed. Visitor view tracking will be added as a separate analytics layer before the site is considered launch-ready.</p></section>'''
    new = '''<section id="stats" class="hidden"><h2 class="section-title">Analytics</h2><div class="actions" style="margin-bottom:15px"><button type="button" class="light" onclick="loadStats('7')">7 Days</button><button type="button" class="light" onclick="loadStats('30')">30 Days</button><button type="button" class="light" onclick="loadStats('90')">90 Days</button><button type="button" class="light" onclick="loadStats('365')">1 Year</button><button type="button" class="light" onclick="loadStats('all')">All Time</button></div><div class="three"><div class="card"><div><h3>Total Views</h3><small>Selected period</small></div><strong id="statViews">0</strong></div><div class="card"><div><h3>Published</h3><small>Live posts</small></div><strong id="statPublished">0</strong></div><div class="card"><div><h3>Novels</h3><small>Manuscript books</small></div><strong id="statBooks">0</strong></div></div><div class="preview" style="margin-top:18px"><h3 class="section-title">Views Over Time</h3><canvas id="viewsChart" height="220" style="width:100%;display:block"></canvas></div><div class="two" style="margin-top:18px"><div class="preview"><h3 class="section-title">Views by Section</h3><div id="analyticsCategories" class="list"></div></div><div class="preview"><h3 class="section-title">Most Viewed Content</h3><div id="analyticsPosts" class="list"></div></div></div><p class="note" style="margin-top:18px">Visitor analytics are stored in the database and do not depend on browser storage.</p></section>'''
    if old in s:
        s = s.replace(old, new, 1)
    elif 'id="analyticsCategories"' not in s:
        raise SystemExit("analytics stats section marker not found")

    # Replace the simple stats loader if present, otherwise insert a loader before the final script tag.
    old_js = "async function loadStats(){await refreshCounts()}"
    new_js = '''async function loadStats(period='30'){
  try{
    window.analyticsPeriod=period;
    await refreshCounts();
    const d=await api(`/api/analytics?period=${encodeURIComponent(period)}`);
    $("statViews").textContent=d.total_views||0;
    renderAnalytics(d);
  }catch(e){showStatus(e.message,true)}
}
function renderAnalytics(d){
  const canvas=$("viewsChart"); if(!canvas)return;
  const ctx=canvas.getContext("2d"), ratio=window.devicePixelRatio||1;
  const w=Math.max(320,canvas.clientWidth||700), h=220;
  canvas.width=w*ratio; canvas.height=h*ratio; ctx.setTransform(ratio,0,0,ratio,0,0); ctx.clearRect(0,0,w,h);
  const points=d.daily||[], max=Math.max(1,...points.map(x=>Number(x.views)||0)), left=42,right=12,top=15,bottom=32,cw=w-left-right,ch=h-top-bottom;
  ctx.strokeStyle="#C9B78F";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,top);ctx.lineTo(left,h-bottom);ctx.lineTo(w-right,h-bottom);ctx.stroke();
  if(points.length){ctx.strokeStyle="#5C4033";ctx.lineWidth=2;ctx.beginPath();points.forEach((p,i)=>{const x=left+(points.length===1?cw/2:(i/(points.length-1))*cw),y=top+ch-(Number(p.views)/max)*ch;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();ctx.fillStyle="#5C4033";points.forEach((p,i)=>{const x=left+(points.length===1?cw/2:(i/(points.length-1))*cw),y=top+ch-(Number(p.views)/max)*ch;ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fill()});ctx.fillStyle="#6F6257";ctx.font="12px Georgia";ctx.fillText(String(points[0].day||""),left,h-8);if(points.length>1)ctx.fillText(String(points[points.length-1].day||""),Math.max(left,w-95),h-8);ctx.fillText(String(max),4,top+4);ctx.fillText("0",20,h-bottom+4)}else{ctx.fillStyle="#6F6257";ctx.font="15px Georgia";ctx.fillText("No visitor views recorded for this period yet.",left,top+40)}
  $("analyticsCategories").innerHTML=d.categories?.length?d.categories.map(x=>`<div class="card"><span>${esc(cat(x.category)||x.category)}</span><strong>${x.views}</strong></div>`).join(""):"<p class='note'>No section views yet.</p>";
  $("analyticsPosts").innerHTML=d.posts?.length?d.posts.slice(0,15).map(x=>`<div class="card"><div><strong>${esc(x.title)}</strong><br><small>${esc(cat(x.category)||x.category||"")}</small></div><strong>${x.views}</strong></div>`).join(""):"<p class='note'>No content views yet.</p>";
}
window.addEventListener('resize',()=>{if(window.analyticsPeriod&&$("stats")&&!$("stats").classList.contains('hidden'))loadStats(window.analyticsPeriod)});'''
    if old_js in s:
        s = s.replace(old_js, new_js, 1)
    elif "function renderAnalytics(d)" not in s:
        raise SystemExit("analytics JavaScript marker not found")

    s = s.replace("if(name===\"stats\")loadStats()", "if(name===\"stats\")loadStats(window.analyticsPeriod||'30')", 1)
    p.write_text(s)


update_app()
update_admin()
print("Analytics Phase 1 implementation complete")

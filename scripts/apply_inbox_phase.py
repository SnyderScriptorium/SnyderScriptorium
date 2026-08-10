from pathlib import Path


def replace_once(text, old, new, label):
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"Could not find {label} marker")
    return text.replace(old, new, 1)


db = Path("database.py")
s = db.read_text()
pg_marker = '''        """
        CREATE TABLE IF NOT EXISTS site_content ('''
pg_table = '''        """
        CREATE TABLE IF NOT EXISTS inbox_messages (
            id BIGSERIAL PRIMARY KEY,
            message_type TEXT NOT NULL DEFAULT 'contact',
            name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new',
            is_read INTEGER NOT NULL DEFAULT 0,
            post_id BIGINT,
            book_id BIGINT,
            chapter_id BIGINT,
            member_id BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
'''
if "CREATE TABLE IF NOT EXISTS inbox_messages" not in s:
    s = replace_once(s, pg_marker, pg_table + pg_marker, "PostgreSQL inbox table")
sqlite_marker = '''        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_views ('''
sqlite_table = '''        conn.execute("""
            CREATE TABLE IF NOT EXISTS inbox_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_type TEXT NOT NULL DEFAULT 'contact',
                name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new',
                is_read INTEGER NOT NULL DEFAULT 0,
                post_id INTEGER,
                book_id INTEGER,
                chapter_id INTEGER,
                member_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
'''
if "CREATE TABLE IF NOT EXISTS inbox_messages" not in s[s.find("def init_db") :]:
    s = replace_once(s, sqlite_marker, sqlite_table + sqlite_marker, "SQLite inbox table")
db.write_text(s)


app = Path("app.py")
s = app.read_text()
contact = '''

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        if not name or not email or not message:
            return render_template("contact.html", error="Please provide your name, email, and message.", name=name, email=email, subject=subject, message=message)
        conn = get_db()
        conn.execute("INSERT INTO inbox_messages(message_type, name, email, subject, message) VALUES (?, ?, ?, ?, ?)", ("contact", name, email, subject, message))
        conn.commit()
        conn.close()
        return render_template("contact.html", success="Your message has been sent. Thank you for reaching out.")
    return render_template("contact.html")
'''
if '@app.route("/contact"' not in s:
    s = replace_once(s, '\n@app.route("/store")', contact + '\n@app.route("/store")', "contact route")

inbox_routes = '''

@app.route("/admin/inbox")
@admin_required
def admin_inbox():
    return render_template("admin_inbox.html")


@app.route("/api/inbox", methods=["GET"])
@admin_required
def get_inbox():
    status = request.args.get("status", "").strip()
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM inbox_messages WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM inbox_messages ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route("/api/inbox/<int:message_id>", methods=["PATCH"])
@admin_required
def update_inbox_message(message_id):
    data = request.get_json() or {}
    status = str(data.get("status", "")).strip()
    allowed = {"new", "open", "in_progress", "resolved", "archived"}
    conn = get_db()
    row = conn.execute("SELECT id FROM inbox_messages WHERE id = ?", (message_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Inbox message not found."}), 404
    if status and status not in allowed:
        conn.close()
        return jsonify({"error": "Invalid inbox status."}), 400
    if status:
        conn.execute("UPDATE inbox_messages SET status = ?, is_read = 1 WHERE id = ?", (status, message_id))
    else:
        conn.execute("UPDATE inbox_messages SET is_read = 1 WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})
'''
if '@app.route("/admin/inbox")' not in s:
    s = replace_once(s, '\n@app.route("/api/analytics"', inbox_routes + '\n\n@app.route("/api/analytics"', "inbox routes")
app.write_text(s)


admin = Path("templates/admin.html")
s = admin.read_text()
tab_old = '''<button id="tab-stats" class="light" onclick="switchTab('stats')">Analytics</button>'''
tab_new = tab_old + '''<button id="tab-inbox" class="light" onclick="switchTab('inbox')">Inbox <span id="inboxCount">0</span></button>'''
s = replace_once(s, tab_old, tab_new, "Inbox tab")
section_marker = '<section id="stats" class="hidden">'
inbox_section = '''<section id="inbox" class="hidden"><h2 class="section-title">Admin Inbox</h2><p class="note">Contact messages and future reader feedback arrive here. Use the status menu to track each message.</p><div class="actions" style="margin-bottom:15px"><button type="button" class="light" onclick="loadInbox()">Refresh Inbox</button><button type="button" class="light" onclick="loadInbox('new')">New Only</button><button type="button" class="light" onclick="loadInbox()">All Messages</button></div><div id="inboxList" class="list"></div></section>'''
s = replace_once(s, section_marker, inbox_section + section_marker, "Inbox section")
tabs_old = '["write","drafts","published","manuscripts","about","kwpreview","stats"]'
tabs_new = '["write","drafts","published","manuscripts","about","kwpreview","stats","inbox"]'
s = s.replace(tabs_old, tabs_new)
load_old = "if(name===\"stats\")loadStats(window.analyticsPeriod||'30')"
load_new = load_old + ";if(name===\"inbox\")loadInbox()"
s = replace_once(s, load_old, load_new, "Inbox tab loader")
inbox_js = '''
async function loadInbox(status=""){
  const list=$("inboxList"); if(!list)return; list.innerHTML="Loading inbox...";
  try{
    const items=await api(status?`/api/inbox?status=${encodeURIComponent(status)}`:"/api/inbox");
    const unread=items.filter(x=>!x.is_read).length; $("inboxCount").textContent=unread?`(${unread})`:"";
    list.innerHTML=items.length?"":"<p class='note'>Your inbox is empty.</p>";
    items.forEach(m=>{
      const c=document.createElement("div"); c.className="card";
      const label={contact:"Contact",reader_feedback:"Reader Feedback",subscriber:"Subscriber"}[m.message_type]||m.message_type;
      c.innerHTML=`<div style="flex:1"><h3>${esc(m.subject||label)}</h3><small>${esc(label)} · ${esc(m.name||"Unknown")} · ${esc(m.email||"")} · ${esc(m.created_at||"")}</small><p>${esc(m.message||"")}</p><small>Post: ${esc(m.post_id||"—")} · Chapter: ${esc(m.chapter_id||"—")}</small></div><div class="small-actions"><select onchange="updateInboxStatus(${m.id},this.value)"><option value="new" ${m.status==='new'?'selected':''}>New</option><option value="open" ${m.status==='open'?'selected':''}>Open</option><option value="in_progress" ${m.status==='in_progress'?'selected':''}>In Progress</option><option value="resolved" ${m.status==='resolved'?'selected':''}>Resolved</option><option value="archived" ${m.status==='archived'?'selected':''}>Archived</option></select></div>`;
      list.appendChild(c);
    });
  }catch(e){list.innerHTML=`<p class='note'>${esc(e.message)}</p>`}
}
async function updateInboxStatus(id,status){try{await api(`/api/inbox/${id}`,{method:"PATCH",body:JSON.stringify({status})});await loadInbox();showStatus("Inbox status updated.")}catch(e){showStatus(e.message,true)}}
'''
if 'async function loadInbox(' not in s:
    s = replace_once(s, "async function loadStats(period='30'){", inbox_js + "\nasync function loadStats(period='30'){", "Inbox JavaScript")
admin.write_text(s)

Path("templates/contact.html").write_text('''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Contact — The Snyder Scriptorium</title><link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}"></head><body><main class="site-main"><div class="site-title"><h1>Contact</h1></div><section class="content-section"><h2>Send a Message</h2>{% if success %}<p>{{ success }}</p>{% endif %}{% if error %}<p>{{ error }}</p>{% endif %}<form method="POST"><label for="name">Name</label><input id="name" name="name" required value="{{ name|default('') }}"><label for="email">Email</label><input id="email" name="email" type="email" required value="{{ email|default('') }}"><label for="subject">Subject</label><input id="subject" name="subject" value="{{ subject|default('') }}"><label for="message">Message</label><textarea id="message" name="message" required>{{ message|default('') }}</textarea><button type="submit">Send Message</button></form></section></main></body></html>''')

Path("templates/admin_inbox.html").write_text('''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Admin Inbox — Scriptorium</title><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@300;400;500;600;700&display=swap" rel="stylesheet"><style>:root{--ivory:#F7F1E6;--paper:#FFFDF8;--camel2:#E8D9B5;--ink:#24333B;--brown:#5C4033;--line:#C9B78F;--muted:#6F6257}*{box-sizing:border-box}body{margin:0;padding:20px;background:var(--camel2);color:var(--ink);font-family:"Playfair Display",Georgia,serif}.shell{max-width:1100px;margin:auto}.panel{background:var(--ivory);border:1px solid var(--line);border-radius:10px;padding:25px}.card{background:var(--paper);border:1px solid var(--line);border-radius:7px;padding:15px;display:flex;justify-content:space-between;gap:15px;align-items:flex-start}.list{display:grid;gap:12px}.small-actions{display:flex;gap:8px;align-items:center}.small-actions select{padding:8px;border:1px solid var(--line);border-radius:5px;background:var(--paper)}a{color:var(--brown)}@media(max-width:700px){body{padding:10px}.panel{padding:16px}.card{flex-direction:column}.small-actions{width:100%}.small-actions select{width:100%}}</style></head><body><div class="shell"><div class="panel"><p><a href="{{ url_for('admin_dashboard') }}">← Back to Control Panel</a></p><h1>Admin Inbox</h1><p>Contact messages and reader feedback will appear here. Messages remain stored in the database until you change their status.</p><div id="inbox" class="list">Loading...</div></div></div><script>async function load(){const r=await fetch('/api/inbox');const data=await r.json();const box=document.getElementById('inbox');box.innerHTML=data.length?'':'<p>Your inbox is empty.</p>';data.forEach(m=>{const d=document.createElement('div');d.className='card';d.innerHTML='<div><h2>'+esc(m.subject||'Message')+'</h2><p>'+esc(m.name)+' · '+esc(m.email)+'</p><p>'+esc(m.message)+'</p><small>'+esc(m.created_at||'')+'</small></div><div class="small-actions"><select onchange="status('+m.id+',this.value)"><option value="new" '+(m.status==='new'?'selected':'')+'>New</option><option value="open" '+(m.status==='open'?'selected':'')+'>Open</option><option value="in_progress" '+(m.status==='in_progress'?'selected':'')+'>In Progress</option><option value="resolved" '+(m.status==='resolved'?'selected':'')+'>Resolved</option><option value="archived" '+(m.status==='archived'?'selected':'')+'>Archived</option></select></div>';box.appendChild(d)})}async function status(id,value){await fetch('/api/inbox/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:value})});load()}function esc(v){const d=document.createElement('div');d.textContent=v??'';return d.innerHTML}load();</script></body></html>''')

print("Inbox phase files prepared.")

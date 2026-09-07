from functools import wraps
from flask import request, jsonify, session, redirect, url_for, render_template, abort
from app import app, get_db, require_admin
from database import using_postgres
from datetime import datetime

def ensure_schema():
    conn=get_db()
    try:
        if using_postgres():
            statements=["ALTER TABLE members ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'","ALTER TABLE members ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMPTZ"]
        else:
            statements=["ALTER TABLE members ADD COLUMN status TEXT NOT NULL DEFAULT 'active'","ALTER TABLE members ADD COLUMN blocked_at TEXT"]
        for sql in statements:
            try: conn.execute(sql)
            except Exception as exc:
                if 'duplicate column' not in str(exc).lower() and 'already exists' not in str(exc).lower(): raise
        conn.commit()
    finally:
        conn.close()
try: ensure_schema()
except Exception: pass

def admin_only(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not require_admin(): return redirect(url_for('admin_login_page'))
        return view(*args,**kwargs)
    return wrapped

@app.route('/api/inbox/<int:message_id>',methods=['DELETE'])
@admin_only
def delete_inbox_message(message_id):
    conn=get_db(); row=conn.execute('SELECT id FROM inbox_messages WHERE id=?',(message_id,)).fetchone()
    if not row: conn.close(); return jsonify({'error':'Inbox message not found.'}),404
    conn.execute('DELETE FROM inbox_messages WHERE id=?',(message_id,)); conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/api/inbox/<int:message_id>/block-sender',methods=['POST'])
@admin_only
def block_inbox_sender(message_id):
    conn=get_db(); message=conn.execute('SELECT member_id,email FROM inbox_messages WHERE id=?',(message_id,)).fetchone()
    if not message: conn.close(); return jsonify({'error':'Inbox message not found.'}),404
    member=None
    if message['member_id']: member=conn.execute('SELECT id,email FROM members WHERE id=?',(message['member_id'],)).fetchone()
    if not member and message['email']: member=conn.execute('SELECT id,email FROM members WHERE lower(email)=lower(?)',(message['email'].strip(),)).fetchone()
    if not member: conn.close(); return jsonify({'error':'This sender does not have a member account to block.'}),400
    conn.execute("UPDATE members SET status='blocked',blocked_at=CURRENT_TIMESTAMP WHERE id=?",(member['id'],)); conn.commit(); conn.close(); return jsonify({'success':True,'member_id':member['id'],'email':member['email']})

@app.route('/api/members')
@admin_only
def admin_members():
    conn=get_db(); rows=conn.execute("SELECT id,email,subscription_status,COALESCE(status,'active') AS status,date_created,blocked_at FROM members ORDER BY id DESC").fetchall(); conn.close(); return jsonify([dict(r) for r in rows])

@app.route('/api/members/<int:member_id>/block',methods=['POST'])
@admin_only
def block_member(member_id):
    conn=get_db(); row=conn.execute('SELECT id FROM members WHERE id=?',(member_id,)).fetchone()
    if not row: conn.close(); return jsonify({'error':'Member not found.'}),404
    conn.execute("UPDATE members SET status='blocked',blocked_at=CURRENT_TIMESTAMP WHERE id=?",(member_id,)); conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/api/members/<int:member_id>/unblock',methods=['POST'])
@admin_only
def unblock_member(member_id):
    conn=get_db(); row=conn.execute('SELECT id FROM members WHERE id=?',(member_id,)).fetchone()
    if not row: conn.close(); return jsonify({'error':'Member not found.'}),404
    conn.execute("UPDATE members SET status='active',blocked_at=NULL WHERE id=?",(member_id,)); conn.commit(); conn.close(); return jsonify({'success':True})

@app.after_request
def inject_live_inbox_controls(response):
    if request.path != '/admin' or 'text/html' not in response.headers.get('Content-Type',''): return response
    script='''<script>(function(){function install(){if(typeof window.loadInbox!=="function"||window.__snyderInboxWrapped)return;window.__snyderInboxWrapped=true;const original=window.loadInbox;async function decorate(){const list=document.getElementById("inboxList");if(!list)return;list.querySelectorAll(".card").forEach(card=>{const select=card.querySelector("select[onchange*='updateInboxStatus']");if(!select)return;select.querySelectorAll("option[value='in_progress'],option[value='resolved']").forEach(o=>o.remove());const match=(select.getAttribute("onchange")||"").match(/updateInboxStatus\\((\\d+)/);if(!match||card.querySelector("[data-snyder-inbox-action]"))return;const id=match[1];const actions=select.parentElement;const block=document.createElement("button");block.type="button";block.className="secondary";block.dataset.snyderInboxAction="block";block.textContent="Block Sender";block.onclick=async function(){if(!confirm("Block the member associated with this message? They will no longer be able to log in."))return;try{const r=await fetch("/api/inbox/"+id+"/block-sender",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:"{}"});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||"Block failed.");alert("Member blocked.");await original();}catch(e){alert(e.message)}};const del=document.createElement("button");del.type="button";del.className="danger";del.dataset.snyderInboxAction="delete";del.textContent="Delete Permanently";del.onclick=async function(){if(!confirm("Delete this message permanently? This cannot be undone."))return;try{const r=await fetch("/api/inbox/"+id,{method:"DELETE",credentials:"same-origin"});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||"Delete failed.");await original();}catch(e){alert(e.message)}};actions.appendChild(block);actions.appendChild(del);});}window.loadInbox=async function(status){await original(status);decorate()};setTimeout(decorate,0)}if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install()})();</script>'''
    html=response.get_data(as_text=True)
    if '</body>' in html: response.set_data(html.replace('</body>',script+'</body>'))
    return response

@app.before_request
def reject_blocked_members():
    if request.path.startswith('/admin') or request.path.startswith('/static/'): return None
    member_id=session.get('member_id')
    if not member_id: return None
    conn=get_db(); row=conn.execute("SELECT COALESCE(status,'active') AS status FROM members WHERE id=?",(member_id,)).fetchone(); conn.close()
    if row and row['status']=='blocked': session.clear(); return redirect(url_for('member_login'))

# Find Us lives in this already-loaded admin extension so WSGI startup remains unchanged.
# The event table itself is created by the application's normal database initializer.
@app.route('/find-us')
def find_us():
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db()
    events = conn.execute(
        "SELECT * FROM find_us_events WHERE is_active = 1 AND date >= ? ORDER BY is_featured DESC, date ASC, start_time ASC, id ASC",
        (today,),
    ).fetchall()
    conn.close()
    return render_template('find_us.html', events=events)

@app.template_filter('display_event_date')
def display_event_date(value):
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').strftime('%A, %B %-d, %Y')
    except ValueError:
        try:
            return datetime.strptime(str(value), '%Y-%m-%d').strftime('%A, %B %#d, %Y')
        except ValueError:
            return str(value)

@app.route('/admin/find-us')
@admin_only
def admin_find_us():
    return render_template('admin_find_us.html')

@app.route('/api/find-us', methods=['GET'])
@admin_only
def get_find_us_events():
    conn = get_db()
    rows = conn.execute("SELECT * FROM find_us_events ORDER BY date ASC, start_time ASC, id ASC").fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route('/api/find-us', methods=['POST'])
@admin_only
def create_find_us_event():
    data = request.get_json() or {}
    title = str(data.get('title', '')).strip()
    event_date = str(data.get('date', '')).strip()
    if not title or not event_date:
        return jsonify({'error': 'Event name and date are required.'}), 400
    try:
        datetime.strptime(event_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Please provide a valid event date.'}), 400
    start_time = str(data.get('start_time', '')).strip()
    end_time = str(data.get('end_time', '')).strip()
    if start_time:
        try: datetime.strptime(start_time, '%H:%M')
        except ValueError: return jsonify({'error': 'Please provide a valid start time.'}), 400
    if end_time:
        try: datetime.strptime(end_time, '%H:%M')
        except ValueError: return jsonify({'error': 'Please provide a valid end time.'}), 400
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO find_us_events(title,date,start_time,end_time,location,address,description,website_url,image_url,is_active,is_featured,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (title, event_date, start_time, end_time, str(data.get('location','')).strip(), str(data.get('address','')).strip(), str(data.get('description','')).strip(), str(data.get('website_url','')).strip(), str(data.get('image_url','')).strip(), 1 if data.get('is_active', True) else 0, 1 if data.get('is_featured', False) else 0),
    )
    conn.commit(); event_id = cur.lastrowid; conn.close()
    return jsonify({'success': True, 'id': event_id}), 201

@app.route('/api/find-us/<int:event_id>', methods=['GET'])
@admin_only
def get_find_us_event(event_id):
    conn = get_db(); row = conn.execute('SELECT * FROM find_us_events WHERE id=?',(event_id,)).fetchone(); conn.close()
    if not row: return jsonify({'error':'Event not found.'}),404
    return jsonify(dict(row))

@app.route('/api/find-us/<int:event_id>', methods=['PUT'])
@admin_only
def update_find_us_event(event_id):
    data = request.get_json() or {}
    title = str(data.get('title', '')).strip()
    event_date = str(data.get('date', '')).strip()
    if not title or not event_date: return jsonify({'error':'Event name and date are required.'}),400
    try: datetime.strptime(event_date, '%Y-%m-%d')
    except ValueError: return jsonify({'error':'Please provide a valid event date.'}),400
    conn = get_db(); row = conn.execute('SELECT id FROM find_us_events WHERE id=?',(event_id,)).fetchone()
    if not row: conn.close(); return jsonify({'error':'Event not found.'}),404
    conn.execute(
        "UPDATE find_us_events SET title=?,date=?,start_time=?,end_time=?,location=?,address=?,description=?,website_url=?,image_url=?,is_active=?,is_featured=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (title,event_date,str(data.get('start_time','')).strip(),str(data.get('end_time','')).strip(),str(data.get('location','')).strip(),str(data.get('address','')).strip(),str(data.get('description','')).strip(),str(data.get('website_url','')).strip(),str(data.get('image_url','')).strip(),1 if data.get('is_active',True) else 0,1 if data.get('is_featured',False) else 0,event_id),
    )
    conn.commit(); conn.close(); return jsonify({'success':True})

@app.route('/api/find-us/<int:event_id>', methods=['DELETE'])
@admin_only
def delete_find_us_event(event_id):
    conn = get_db(); cur = conn.execute('DELETE FROM find_us_events WHERE id=?',(event_id,)); conn.commit(); conn.close()
    if cur.rowcount == 0: return jsonify({'error':'Event not found.'}),404
    return jsonify({'success':True})

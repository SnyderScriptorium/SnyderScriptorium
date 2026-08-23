from functools import wraps
from flask import request, jsonify, session, redirect, url_for
from app import app, get_db, require_admin
from database import using_postgres

def ensure_schema():
    conn=get_db()
    try:
        if using_postgres():
            statements=["ALTER TABLE members ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'","ALTER TABLE members ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMPTZ","ALTER TABLE inbox_messages ADD COLUMN IF NOT EXISTS replied_at TIMESTAMPTZ"]
        else:
            statements=["ALTER TABLE members ADD COLUMN status TEXT NOT NULL DEFAULT 'active'","ALTER TABLE members ADD COLUMN blocked_at TEXT"]
        for sql in statements:
            try: conn.execute(sql)
            except Exception as exc:
                if 'duplicate column' not in str(exc).lower() and 'already exists' not in str(exc).lower(): raise
        conn.commit()
    finally: conn.close()
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
    if request.path != '/admin' or 'text/html' not in response.headers.get('Content-Type',''):
        return response
    script='''<script>(function(){function install(){if(typeof window.loadInbox!=="function")return;if(window.__snyderInboxWrapped)return;window.__snyderInboxWrapped=true;const original=window.loadInbox;async function decorate(){const list=document.getElementById("inboxList");if(!list)return;list.querySelectorAll(".card").forEach(card=>{if(card.querySelector("[data-snyder-inbox-action]"))return;const select=card.querySelector("select[onchange*='updateInboxStatus']");if(!select)return;const match=(select.getAttribute("onchange")||"").match(/updateInboxStatus\\((\\d+)/);if(!match)return;const id=match[1];const actions=select.parentElement;const del=document.createElement("button");del.type="button";del.className="danger";del.dataset.snyderInboxAction="delete";del.textContent="Delete Permanently";del.onclick=async function(){if(!confirm("Delete this message permanently? This cannot be undone."))return;try{const r=await fetch("/api/inbox/"+id,{method:"DELETE",credentials:"same-origin"});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||"Delete failed.");await original();}catch(e){alert(e.message)}};const block=document.createElement("button");block.type="button";block.className="secondary";block.dataset.snyderInboxAction="block";block.textContent="Block Sender";block.onclick=async function(){if(!confirm("Block the member associated with this message? They will no longer be able to log in."))return;try{const r=await fetch("/api/inbox/"+id+"/block-sender",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:"{}"});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||"Block failed.");alert("Member blocked.");await original();}catch(e){alert(e.message)}};actions.appendChild(block);actions.appendChild(del);});}window.loadInbox=async function(status){await original(status);decorate()};setTimeout(decorate,0)}if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",install,{once:true});else install()})();</script>'''
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
    return None

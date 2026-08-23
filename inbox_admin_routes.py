from functools import wraps
from flask import request, jsonify, session, redirect, url_for
from app import app, get_db, require_admin
from database import using_postgres

def ensure_schema():
    conn=get_db()
    try:
        if using_postgres():
            statements=["ALTER TABLE members ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'","ALTER TABLE members ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMPTZ","ALTER TABLE inbox_messages ADD COLUMN IF NOT EXISTS replied_at TIMESTAMPTZ","CREATE TABLE IF NOT EXISTS inbox_replies (id BIGSERIAL PRIMARY KEY,message_id BIGINT NOT NULL REFERENCES inbox_messages(id) ON DELETE CASCADE,recipient_email TEXT NOT NULL,subject TEXT NOT NULL,message TEXT NOT NULL,sent_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,delivery_status TEXT NOT NULL DEFAULT 'pending')"]
        else:
            statements=["ALTER TABLE members ADD COLUMN status TEXT NOT NULL DEFAULT 'active'","ALTER TABLE members ADD COLUMN blocked_at TEXT","ALTER TABLE inbox_messages ADD COLUMN replied_at TEXT","CREATE TABLE IF NOT EXISTS inbox_replies (id INTEGER PRIMARY KEY AUTOINCREMENT,message_id INTEGER NOT NULL,recipient_email TEXT NOT NULL,subject TEXT NOT NULL,message TEXT NOT NULL,sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,delivery_status TEXT NOT NULL DEFAULT 'pending',FOREIGN KEY(message_id) REFERENCES inbox_messages(id) ON DELETE CASCADE)"]
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

@app.before_request
def reject_blocked_members():
    if request.path.startswith('/admin') or request.path.startswith('/static/'): return None
    member_id=session.get('member_id')
    if not member_id: return None
    conn=get_db(); row=conn.execute("SELECT COALESCE(status,'active') AS status FROM members WHERE id=?",(member_id,)).fetchone(); conn.close()
    if row and row['status']=='blocked': session.clear(); return redirect(url_for('member_login'))
    return None

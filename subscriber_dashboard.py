from flask import render_template_string, redirect, url_for
from database import get_db

TEMPLATE = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Subscriber Dashboard</title><style>body{font-family:Georgia,serif;background:#E8D9B5;color:#24333B;padding:20px}.wrap{max-width:1100px;margin:auto;background:#F7F1E6;padding:25px;border:1px solid #C9B78F;border-radius:10px}table{width:100%;border-collapse:collapse;background:#FFFDF8}th,td{padding:11px;border-bottom:1px solid #E4D8C2;text-align:left}th{background:#EFE7D8;color:#5C4033}.status{font-weight:bold}.active{color:#405A32}.past_due,.paused{color:#8A641D}.cancelled,.expired{color:#8B3F3F}.cards{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}.card{padding:14px;background:#FFFDF8;border:1px solid #C9B78F;border-radius:7px}.card b{font-size:1.5rem;display:block}.error{padding:12px;background:#F3D5D0;border:1px solid #B65B50;border-radius:6px;color:#6B2F29}</style></head><body><div class="wrap"><h1>Subscriber Dashboard</h1><p>Membership accounts and current PayPal subscription status.</p>{% if error %}<div class="error">Subscriber data could not be loaded. The dashboard itself is working; the database query reported: {{ error }}</div>{% endif %}<div class="cards">{% for label,count in counts.items() %}<div class="card"><b>{{ count }}</b>{{ label|replace('_',' ')|title }}</div>{% endfor %}</div><table><thead><tr><th>Email</th><th>Account Created</th><th>Membership Status</th><th>PayPal Status</th><th>Subscription ID</th><th>Started</th><th>Next/End</th></tr></thead><tbody>{% for row in rows %}<tr><td>{{ row.email }}</td><td>{{ row.date_created }}</td><td class="status {{ row.subscription_status }}">{{ row.subscription_status }}</td><td>{{ row.sub_status or '—' }}</td><td>{{ row.subscription_id or '—' }}</td><td>{{ row.date_started or '—' }}</td><td>{{ row.date_ends or '—' }}</td></tr>{% else %}<tr><td colspan="7">No member accounts yet.</td></tr>{% endfor %}</tbody></table><p><a href="/admin/analytics">← Analytics</a> &nbsp; <a href="/admin">← Control Panel</a></p></div></body></html>'''

def register_subscriber_dashboard(app):
    def dashboard_view():
        from app import require_admin
        if not require_admin():
            return redirect(url_for('admin_login_page'))
        conn = get_db()
        try:
            rows = conn.execute('''SELECT m.email, m.date_created, m.subscription_status,
                s.status AS sub_status, s.subscription_id, s.date_started, s.date_ends
                FROM members m
                LEFT JOIN subscriptions s ON s.id = (
                    SELECT s2.id FROM subscriptions s2
                    WHERE s2.member_id = m.id ORDER BY s2.id DESC LIMIT 1
                ) ORDER BY m.id DESC''').fetchall()
            counts = {}
            for row in conn.execute('SELECT subscription_status, COUNT(*) AS count FROM members GROUP BY subscription_status').fetchall():
                counts[str(row[0] if not isinstance(row, dict) else row.get('subscription_status') or 'inactive')] = int(row[1] if not isinstance(row, dict) else row.get('count') or 0)
            return render_template_string(TEMPLATE, rows=[dict(r) for r in rows], counts=counts, error=None)
        except Exception as exc:
            return render_template_string(TEMPLATE, rows=[], counts={}, error=str(exc))
        finally:
            conn.close()

    app.add_url_rule('/admin/subscribers', endpoint='subscriber_dashboard', view_func=dashboard_view, methods=['GET'])
    app.add_url_rule('/admin/subscriber-dashboard', endpoint='subscriber_dashboard_alias', view_func=dashboard_view, methods=['GET'])

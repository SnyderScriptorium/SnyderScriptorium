import os
from functools import wraps
from flask import jsonify, render_template, request
from database import get_db, using_postgres


def ensure_analytics_table():
    conn = get_db()
    try:
        if using_postgres():
            conn.execute("""
                CREATE TABLE IF NOT EXISTS page_views (
                    id BIGSERIAL PRIMARY KEY,
                    path TEXT NOT NULL,
                    page_type TEXT NOT NULL DEFAULT 'page',
                    content_id BIGINT,
                    category TEXT,
                    viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS page_views (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    page_type TEXT NOT NULL DEFAULT 'page',
                    content_id INTEGER,
                    category TEXT,
                    viewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()
    finally:
        conn.close()


def _label_for(category, supplied=None):
    supplied = str(supplied or '').strip()
    defaults = {
        'curations': 'Book Curations',
        'reviews': 'Book Reviews',
        'curiosity': 'Curiosity Cabinet',
    }
    if category in defaults:
        return supplied or defaults[category]
    return supplied or {
        'kwsnyderwriting': 'K. W. Snyder Writing',
        'kw_short_stories': 'Short Stories',
        'kw_poems': 'Poems',
        'kw_vignettes': 'Vignettes',
    }.get(category, 'Journal')


def _public_category(app, category, template, title, filter_name=None):
    conn = get_db()
    labels = conn.execute(
        "SELECT DISTINCT category_name FROM published_posts WHERE category = ? AND access_level = 'public' AND category_name IS NOT NULL AND TRIM(category_name) <> '' ORDER BY category_name COLLATE NOCASE",
        (category,),
    ).fetchall()
    selected = str(request.args.get(filter_name or 'label', '')).strip()
    search = str(request.args.get('q', '')).strip()
    sql = "SELECT * FROM published_posts WHERE category = ? AND access_level = 'public'"
    params = [category]
    if selected:
        sql += " AND category_name = ?"
        params.append(selected)
    if search:
        sql += " AND (LOWER(title) LIKE LOWER(?) OR LOWER(content) LIKE LOWER(?))"
        like = f"%{search}%"
        params.extend([like, like])
    sql += " ORDER BY id DESC"
    posts = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template(template, posts=posts, category_name=title,
                           filter_labels=[row['category_name'] for row in labels],
                           selected_label=selected, search_query=search)


def _create_published_post(app):
    data = request.get_json() or {}
    title = str(data.get('title', '')).strip()
    category = str(data.get('category', '')).strip()
    content = str(data.get('content', ''))
    access = str(data.get('accessLevel', 'public'))
    if not title or not content.strip():
        return jsonify({'error': 'A title and content are required.'}), 400
    if category == 'kwsnyderwriting' or category.startswith('kw_'):
        access = 'members'
    if access not in {'public', 'members'}:
        access = 'public'
    label = _label_for(category, data.get('categoryName'))
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO published_posts(title, category, category_name, content, date_published, access_level) VALUES (?, ?, ?, ?, ?, ?)",
        (title, category, label, content, str(data.get('date', '')).strip() or __import__('datetime').datetime.now().strftime('%m/%d/%Y %I:%M %p'), access),
    )
    conn.commit()
    post_id = cur.lastrowid
    conn.close()
    return jsonify({'success': True, 'id': post_id, 'access_level': access}), 201


def _update_published_post(app, post_id):
    data = request.get_json() or {}
    title = str(data.get('title', '')).strip()
    category = str(data.get('category', '')).strip()
    content = str(data.get('content', ''))
    access = str(data.get('accessLevel', 'public'))
    if not title or not content.strip():
        return jsonify({'error': 'A title and content are required.'}), 400
    if category == 'kwsnyderwriting' or category.startswith('kw_'):
        access = 'members'
    if access not in {'public', 'members'}:
        access = 'public'
    conn = get_db()
    row = conn.execute('SELECT id, category_name FROM published_posts WHERE id = ?', (post_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Post not found'}), 404
    label = _label_for(category, data.get('categoryName'))
    if not data.get('categoryName') and category == row['category_name']:
        label = row['category_name']
    conn.execute(
        "UPDATE published_posts SET title = ?, category = ?, category_name = ?, content = ?, access_level = ? WHERE id = ?",
        (title, category, label, content, access, post_id),
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


def register_site_enhancements(app):
    ensure_analytics_table()

    app.view_functions['bookreviews'] = lambda: _public_category(
        app, 'reviews', 'blog_templates/bookreviews.html', 'Book Reviews', 'genre'
    )
    app.view_functions['curiosity_cabinet'] = lambda: _public_category(
        app, 'curiosity', 'blog_templates/curiosity_cabinet.html', 'Curiosity Cabinet', 'topic'
    )
    app.view_functions['create_published_post'] = lambda: _create_published_post(app)
    app.view_functions['update_published_post'] = lambda post_id: _update_published_post(app, post_id)

    @app.after_request
    def inject_admin_label_tools(response):
        if request.path.startswith('/admin') and response.content_type.startswith('text/html') and response.status_code == 200:
            body = response.get_data(as_text=True)
            marker = '</body>'
            script = '<script src="/static/category_labels.js"></script>'
            if marker in body and 'category_labels.js' not in body:
                response.set_data(body.replace(marker, script + marker))
        return response

from flask import render_template, request
from database import get_db


def register_category_route_fix(app):
    """Serve the two public category pages defensively, including legacy category names."""
    @app.before_request
    def _category_route_fix():
        path = request.path.rstrip('/')
        if path not in {'/blog/bookreviews', '/blog/curiosity_cabinet'}:
            return None

        aliases = {
            '/blog/bookreviews': ('reviews', 'bookreviews'),
            '/blog/curiosity_cabinet': ('curiosity', 'curiosity_cabinet'),
        }
        categories = aliases[path]
        template = 'blog_templates/bookreviews.html' if path.endswith('bookreviews') else 'blog_templates/curiosity_cabinet.html'
        title = 'Book Reviews' if path.endswith('bookreviews') else 'Curiosity Cabinet'

        conn = get_db()
        try:
            placeholders = ','.join('?' for _ in categories)
            rows = conn.execute(
                f"SELECT * FROM published_posts WHERE LOWER(COALESCE(category,'')) IN ({placeholders}) AND LOWER(COALESCE(access_level,'public')) = 'public' ORDER BY id DESC",
                tuple(c.lower() for c in categories),
            ).fetchall()
        finally:
            conn.close()

        return render_template(template, posts=rows, category_name=title)

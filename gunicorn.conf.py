def post_worker_init(worker):
    app = worker.wsgi

    from database import init_db, get_db, using_postgres
    init_db()

    from paypal_plan_bootstrap import ensure_paypal_plan
    ensure_paypal_plan(app)

    from paypal_member_routes import register_paypal_member
    register_paypal_member(app)
    from member_auth_guard import register_member_auth_guard
    register_member_auth_guard(app)
    from admin_auth_guard import register_admin_auth_guard
    register_admin_auth_guard(app)
    from site_enhancements import register_site_enhancements
    register_site_enhancements(app)

    # Compatibility aliases for older admin-template endpoint names.
    if "get_published_posts" not in app.view_functions and "get_published" in app.view_functions:
        app.add_url_rule("/api/published", endpoint="get_published_posts", view_func=app.view_functions["get_published"], methods=["GET"])
    if "create_published_post" not in app.view_functions and "create_published" in app.view_functions:
        app.add_url_rule("/api/published", endpoint="create_published_post", view_func=app.view_functions["create_published"], methods=["POST"])

    if using_postgres():
        conn = get_db()
        try:
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
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS page_type TEXT NOT NULL DEFAULT 'page'")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS content_id BIGINT")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS category TEXT")
            conn.execute("ALTER TABLE page_views ADD COLUMN IF NOT EXISTS viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP")
            conn.commit()
        finally:
            conn.close()

    from flask import request

    @app.after_request
    def no_cache_admin(response):
        if request.path.startswith("/admin"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

            if request.path == "/admin" and response.mimetype == "text/html":
                guard = r'''<script>
(function(){
  if(window.__snyderAdminGuard)return;
  window.__snyderAdminGuard=true;
  const originalFetch=window.fetch.bind(window);
  let publishedCache=null,publishedCachedAt=0,publishedInFlight=null;
  const TTL=5000;
  function isPublishedGet(input,init){
    const method=((init&&init.method)||((input&&input.method)||'GET')).toUpperCase();
    if(method!=='GET')return false;
    const raw=typeof input==='string'?input:(input&&input.url)||'';
    try{return new URL(raw,location.href).pathname==='/api/published';}catch(_){return false;}
  }
  function responseFrom(data){return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});}
  window.fetch=function(input,init){
    if(!isPublishedGet(input,init))return originalFetch(input,init);
    const now=Date.now();
    if(publishedCache!==null&&now-publishedCachedAt<TTL)return Promise.resolve(responseFrom(publishedCache));
    if(publishedInFlight)return publishedInFlight.then(responseFrom);
    publishedInFlight=originalFetch(input,init).then(function(r){return r.clone().json().then(function(data){publishedCache=data;publishedCachedAt=Date.now();return data;});}).finally(function(){publishedInFlight=null;});
    return publishedInFlight.then(responseFrom);
  };
  function installTabNavigation(){
    const names=['write','drafts','published','manuscripts','about','kwpreview','stats','inbox'];
    const tabs=document.querySelector('.tabs');
    if(!tabs||tabs.dataset.snyderTabsFixed)return;
    tabs.dataset.snyderTabsFixed='1';
    tabs.style.position='relative';tabs.style.zIndex='10000';tabs.style.pointerEvents='auto';
    tabs.querySelectorAll('button').forEach(function(button){
      button.style.position='relative';button.style.zIndex='10001';button.style.pointerEvents='auto';
      button.addEventListener('click',function(event){
        const match=(button.id||'').match(/^tab-(.+)$/);if(!match)return;
        const name=match[1];if(!names.includes(name))return;
        event.preventDefault();event.stopPropagation();
        try{window.switchTab(name);}catch(error){
          console.error('Dashboard tab navigation failed:',error);
          names.forEach(function(n){const section=document.getElementById(n);if(section)section.classList.toggle('hidden',n!==name);});
        }
      },true);
    });
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',installTabNavigation,{once:true});else installTabNavigation();
})();
</script>'''
                body = response.get_data(as_text=True)
                if "__snyderAdminGuard" not in body and "</body>" in body:
                    response.set_data(body.replace("</body>", guard + "</body>"))
        elif request.path == "/api/published" and request.method == "GET":
            response.headers["Cache-Control"] = "private, max-age=5, must-revalidate"
            response.headers["Vary"] = "Cookie"
        return response

    if "kwsnyderwriting" not in app.view_functions and "kwsnyderwriting_entry" in app.view_functions:
        app.add_url_rule("/kwsnyderwriting", endpoint="kwsnyderwriting", view_func=app.view_functions["kwsnyderwriting_entry"])

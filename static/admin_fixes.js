/* Admin editor fixes: rich editing, fail-safe publishing, and K.W. category restoration. */
(function(){
'use strict';
const KW_SUBCATEGORIES=new Set(['kwsnyderwriting','kw_short_stories','kw_poems','kw_vignettes']);
const PUBLIC_CATEGORIES=new Set(['curations','reviews','curiosity']);
function canonicalCategory(v){v=String(v||'').trim().toLowerCase();if(['journal','kw_snyder_writing','kw-snyder-writing','k.w. snyder writing'].includes(v))return'kwsnyderwriting';return v}
function installKWCategoryRestorer(){const c=document.getElementById('postCategory'),w=document.getElementById('postKWSubcategoryWrap'),sub=document.getElementById('postKWSubcategory');if(!c||!w||!sub)return;function set(v){v=canonicalCategory(v);if(KW_SUBCATEGORIES.has(v)){c.value='kwsnyderwriting';sub.value=v;c.dataset.effectiveKW=v;w.classList.remove('hidden')}else{c.value=v||'curations';delete c.dataset.effectiveKW;w.classList.add('hidden')}if(typeof window.syncAccess==='function')window.syncAccess()}window.setPostCategory=set;window.effectivePostCategory=function(){return c.value==='kwsnyderwriting'?(c.dataset.effectiveKW||sub.value||'kwsnyderwriting'):canonicalCategory(c.value)};if(!c.dataset.kwRestorerWired){c.dataset.kwRestorerWired='1';c.addEventListener('change',()=>{if(c.value==='kwsnyderwriting'){w.classList.remove('hidden');if(!KW_SUBCATEGORIES.has(sub.value))sub.value='kwsnyderwriting';c.dataset.effectiveKW=sub.value}else{w.classList.add('hidden');delete c.dataset.effectiveKW}});sub.addEventListener('change',()=>{if(c.value==='kwsnyderwriting')c.dataset.effectiveKW=sub.value})}}
function safeAccess(c){return PUBLIC_CATEGORIES.has(canonicalCategory(c))?'public':'members'}
function status(m,e){if(typeof window.showStatus==='function')window.showStatus(m,e);}
window.publishPost=async function(){const title=(document.getElementById('postTitle')?.value||'').trim(),content=document.getElementById('postEditor')?.innerHTML||'',category=window.effectivePostCategory?window.effectivePostCategory():canonicalCategory(document.getElementById('postCategory')?.value||'');const draftId=(typeof editingDraftId!=='undefined'?editingDraftId:null)||window.editingDraftId||null;if(!title||!content.trim())return status('Add a title and some content first.',true);const access=safeAccess(category);try{const r=await fetch('/api/published',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,category,content,access_level:access,accessLevel:access,date:new Date().toLocaleDateString()})});const data=await r.json().catch(()=>({}));if(!r.ok||data.success===false)throw new Error(data.error||'The post could not be published.');if(draftId)await fetch('/api/drafts/'+draftId,{method:'DELETE'});if(typeof window.clearPost==='function')window.clearPost();if(typeof window.refreshCounts==='function')await window.refreshCounts();if(typeof window.loadDrafts==='function')await window.loadDrafts();if(typeof window.loadPublished==='function')await window.loadPublished();status(access==='members'?'Published to Members Only.':'Published publicly.')}catch(e){status(e.message||'The post could not be published.',true)}};
function restoreKWEditor(){const c=document.getElementById('postCategory'),w=document.getElementById('postKWSubcategoryWrap'),sub=document.getElementById('postKWSubcategory');if(!c||!w||!sub)return;const ensure=()=>{const raw=String(c.value||'').trim().toLowerCase(),dataCat=String(c.dataset.effectiveKW||'').trim().toLowerCase();const isKW=raw==='kwsnyderwriting'||KW_SUBCATEGORIES.has(raw)||raw==='journal'||KW_SUBCATEGORIES.has(dataCat);if(!isKW)return;const subtype=KW_SUBCATEGORIES.has(raw)&&raw!=='kwsnyderwriting'?raw:(KW_SUBCATEGORIES.has(dataCat)?dataCat:(KW_SUBCATEGORIES.has(sub.value)?sub.value:'kwsnyderwriting'));c.value='kwsnyderwriting';sub.value=subtype;c.dataset.effectiveKW=subtype;w.classList.remove('hidden');const access=document.getElementById('postAccess');if(access){access.value='members';access.disabled=true;}};ensure();const observer=new MutationObserver(ensure);observer.observe(c,{attributes:true,childList:true,subtree:true});observer.observe(sub,{attributes:true,childList:true,subtree:true});[50,200,500,1000,2500].forEach(ms=>setTimeout(ensure,ms));}
function install(){installKWCategoryRestorer();restoreKWEditor();}

// Keep the admin tab system independent of inline onclick handlers. This also
// prevents a failed API call in one section from disabling navigation to the others.
function installAdminTabNavigation(){
  const names=['write','drafts','published','manuscripts','about','kwpreview','stats','inbox'];
  const dashboard=document.getElementById('dashboard');
  if(!dashboard||dashboard.dataset.tabNavigationInstalled==='1')return;
  dashboard.dataset.tabNavigationInstalled='1';
  window.switchTab=function(name){
    if(!names.includes(name))return;
    names.forEach(n=>{const section=document.getElementById(n);if(section)section.classList.toggle('hidden',n!==name);const button=document.getElementById('tab-'+n);if(button)button.className=n===name?'':'light';});
    try{
      if(name==='drafts'&&typeof window.loadDrafts==='function')window.loadDrafts();
      if(name==='published'&&typeof window.loadPublished==='function')window.loadPublished();
      if(name==='manuscripts'&&typeof window.loadBooks==='function')window.loadBooks();
      if(name==='about'&&typeof window.loadAbout==='function')window.loadAbout();
      if(name==='kwpreview'&&typeof window.loadKWPreview==='function')window.loadKWPreview();
      if(name==='stats'&&typeof window.loadStats==='function')window.loadStats(window.analyticsPeriod||'30');
      if(name==='inbox'&&typeof window.loadInbox==='function')window.loadInbox();
    }catch(error){if(typeof window.showStatus==='function')window.showStatus(error.message||'Unable to load this section.',true);}
  };
  dashboard.addEventListener('click',function(event){
    const button=event.target.closest&&event.target.closest('button[id^="tab-"]');
    if(!button)return;
    const name=button.id.slice(4);
    if(names.includes(name)){event.preventDefault();event.stopPropagation();window.switchTab(name);}
  },true);
}
function startAdminTabNavigation(){
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',installAdminTabNavigation,{once:true});
  else installAdminTabNavigation();
}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
startAdminTabNavigation();
})();
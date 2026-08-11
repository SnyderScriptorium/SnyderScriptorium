(function(){
'use strict';
const EDITOR='.editor';
const ranges=new WeakMap();
function ed(n){return n&&n.closest?n.closest(EDITOR):null}
function inside(e){const s=getSelection();return !!(e&&s&&s.rangeCount&&e.contains(s.anchorNode)&&e.contains(s.focusNode))}
function remember(e){const s=getSelection();if(inside(e))ranges.set(e,s.getRangeAt(0).cloneRange())}
function restore(e){const r=ranges.get(e),s=getSelection();if(!r||!e.contains(r.commonAncestorContainer))return false;s.removeAllRanges();s.addRange(r);return true}
function focus(e){if(!e)return false;e.contentEditable='true';e.removeAttribute('disabled');e.removeAttribute('readonly');e.focus({preventScroll:true});return true}
function keep(e,fn){const x=scrollX,y=scrollY,ex=e.scrollLeft,ey=e.scrollTop;fn();scrollTo(x,y);e.scrollLeft=ex;e.scrollTop=ey;requestAnimationFrame(()=>{scrollTo(x,y);e.scrollLeft=ex;e.scrollTop=ey})}
function block(e){const s=getSelection();if(!inside(e))return null;let n=s.anchorNode;if(n&&n.nodeType===3)n=n.parentElement;return n&&n.closest?(n.closest('p,h1,h2,h3,h4,h5,h6,blockquote,pre,div,li')||e):e}
function indent(e,out){const b=block(e);if(!b||b===e)return;const cur=parseFloat(b.style.marginLeft)||0;const next=Math.max(0,cur+(out?-2:2));b.style.marginLeft=next?next+'em':''}

document.addEventListener('focusin',e=>{const x=ed(e.target);if(x){x.contentEditable='true';remember(x)}},true);
document.addEventListener('click',e=>{const x=ed(e.target);if(x){x.contentEditable='true';remember(x)}},true);
document.addEventListener('selectionchange',()=>document.querySelectorAll(EDITOR).forEach(x=>{if(inside(x))remember(x)}));

document.addEventListener('paste',e=>{
  const x=ed(e.target);
  if(!x)return;
  e.preventDefault();
  e.stopImmediatePropagation();
  focus(x);
  let s=getSelection();
  let r=(s&&s.rangeCount&&inside(x))?s.getRangeAt(0):null;
  if(!r){
    r=document.createRange();
    r.selectNodeContents(x);
    r.collapse(false);
    s=getSelection();
    s.removeAllRanges();
    s.addRange(r);
  }
  const html=e.clipboardData&&e.clipboardData.getData('text/html');
  const text=e.clipboardData&&e.clipboardData.getData('text/plain');
  const value=html||((text||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\r\n|\r|\n/g,'<br>'));
  if(!value)return;
  keep(x,()=>document.execCommand('insertHTML',false,value));
  remember(x);
},true);

document.addEventListener('keydown',e=>{const x=ed(e.target);if(!x)return;if(e.key==='Tab'){e.preventDefault();e.stopImmediatePropagation();focus(x);remember(x);keep(x,()=>indent(x,e.shiftKey));remember(x)}},true);

function exec(e,c,v){focus(e);restore(e);document.execCommand('styleWithCSS',false,true);keep(e,()=>document.execCommand(c,false,v==null?null:v));remember(e)}
function size(e,pt){focus(e);restore(e);const s=getSelection();if(!s.rangeCount||!inside(e))return;const r=s.getRangeAt(0);keep(e,()=>{const span=document.createElement('span');span.style.fontSize=pt+'pt';if(r.collapsed){span.appendChild(document.createTextNode('\u200b'));r.insertNode(span);const n=document.createRange();n.setStart(span.firstChild,1);n.collapse(true);s.removeAllRanges();s.addRange(n)}else{span.appendChild(r.extractContents());r.insertNode(span);const n=document.createRange();n.selectNodeContents(span);s.removeAllRanges();s.addRange(n)}});remember(e)}
function opt(s,v,t){const o=document.createElement('option');o.value=v;o.textContent=t;s.appendChild(o)}
function ol(e){if(!inside(e))return null;let n=getSelection().anchorNode;if(n&&n.nodeType===3)n=n.parentElement;return n&&n.closest?n.closest('ol'):null}
function enhance(tb){if(!tb||tb.dataset.fixed)return;const e=tb.nextElementSibling&&tb.nextElementSibling.matches(EDITOR)?tb.nextElementSibling:null;if(!e)return;tb.dataset.fixed='1';const ss=tb.querySelectorAll('select'),font=ss[0],sz=ss[1];
if(sz){sz.innerHTML='';opt(sz,'','Size');[8,9,10,11,12,14,16,18,20,22,24,26,28,32,36,40,44,48,54,60,64].forEach(n=>opt(sz,n,n+'pt'));sz.onmousedown=()=>remember(e);sz.onchange=function(){if(this.value)size(e,+this.value);this.value=''}}
if(font){font.onmousedown=()=>remember(e);font.onchange=function(){if(this.value)exec(e,'fontName',this.value);this.selectedIndex=0}}
const color=document.createElement('input');color.type='color';color.value='#24333B';color.title='Font color';color.onmousedown=()=>remember(e);color.onchange=()=>exec(e,'foreColor',color.value);const d=tb.querySelector('.divider');if(d)tb.insertBefore(color,d);else tb.appendChild(color);
const format=document.createElement('select');format.title='Paragraph / heading style';[['P','Paragraph'],['H1','Heading 1'],['H2','Heading 2'],['H3','Heading 3'],['H4','Heading 4'],['BLOCKQUOTE','Quote']].forEach(a=>opt(format,a[0],a[1]));format.onmousedown=()=>remember(e);format.onchange=function(){if(this.value)exec(e,'formatBlock',this.value);this.value='P'};if(font)tb.insertBefore(format,font);else tb.prepend(format);
const marker=document.createElement('select');marker.title='Number size';opt(marker,'match','Number = Text');[12,14,16,18,20,24,28,32,36,40,48,54,60,64].forEach(n=>opt(marker,n,'Number '+n+'pt'));marker.onmousedown=()=>remember(e);marker.onchange=function(){const x=ol(e);if(x){if(this.value==='match')x.style.removeProperty('--marker-size');else x.style.setProperty('--marker-size',this.value+'pt')}this.value='match'};tb.appendChild(marker);
const mc=document.createElement('input');mc.type='color';mc.value='#24333B';mc.title='Number color';mc.onmousedown=()=>remember(e);mc.onchange=function(){const x=ol(e);if(x)x.style.setProperty('--marker-color',this.value)};tb.appendChild(mc);
tb.querySelectorAll('button').forEach(b=>b.addEventListener('mousedown',q=>{remember(e);q.preventDefault()}))}
function enhance(){document.querySelectorAll('.toolbar').forEach(enhance);document.querySelectorAll(EDITOR).forEach(e=>e.contentEditable='true')}
function resetChapter(){const t=document.getElementById('chapterTitle'),n=document.getElementById('chapterNumber'),e=document.getElementById('chapterEditor'),p=document.getElementById('chapterPublished');if(t)t.value='';if(n)n.value='';if(e)e.innerHTML='';if(p)p.checked=false}
window.resetManuscriptEditor=resetChapter;

/* Published-post organization. The existing backend/API remains unchanged; this
   only makes the long Published Posts screen easier to navigate. */
const PUBLISHED_FILTERS=[
  ['all','All Posts'],
  ['curations','Book Curations'],
  ['reviews','Book Reviews'],
  ['curiosity','Curiosity Cabinet'],
  ['kwsnyderwriting','K. W. Snyder Writing'],
  ['kw_short_stories','Short Stories'],
  ['kw_poems','Poems'],
  ['kw_vignettes','Vignettes']
];
const PUBLISHED_LABELS={curations:'Book Curations',reviews:'Book Reviews',curiosity:'Curiosity Cabinet',kwsnyderwriting:'Essays',kw_short_stories:'Short Stories',kw_poems:'Poems',kw_vignettes:'Vignettes'};
let publishedCache=[];
let activePublishedFilter='all';
function publishedText(value){return String(value==null?'':value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;').replace(/'/g,'&#39;')}
function publishedCategoryName(category){return PUBLISHED_LABELS[category]||category_label_fallback(category)}
function category_label_fallback(category){return ({curations:'Book Curations',reviews:'Book Reviews',curiosity:'Curiosity Cabinet',kwsnyderwriting:'K. W. Snyder Writing',kw_short_stories:'Short Stories',kw_poems:'Poems',kw_vignettes:'Vignettes'})[category]||'Other'}
function ensurePublishedFilterBar(){
  const list=document.getElementById('publishedList');
  if(!list)return null;
  let bar=document.getElementById('publishedFilterBar');
  if(!bar){
    bar=document.createElement('div');
    bar.id='publishedFilterBar';
    bar.className='published-filter-bar';
    list.parentNode.insertBefore(bar,list);
  }
  bar.innerHTML=PUBLISHED_FILTERS.map(([key,label])=>`<button type="button" class="published-filter ${key===activePublishedFilter?'active':''}" data-filter="${key}">${publishedText(label)}</button>`).join('');
  bar.querySelectorAll('[data-filter]').forEach(btn=>btn.addEventListener('click',()=>{activePublishedFilter=btn.dataset.filter;renderPublishedPosts();ensurePublishedFilterBar()}));
  return bar;
}
function renderPublishedPosts(){
  const list=document.getElementById('publishedList');
  if(!list)return;
  const filtered=activePublishedFilter==='all'?publishedCache:publishedCache.filter(p=>p.category===activePublishedFilter);
  list.innerHTML=filtered.length?'':'<p class="note">No published posts in this category.</p>';
  filtered.forEach(p=>{
    const c=document.createElement('div');
    c.className='card published-card';
    const preview=(p.content||'').replace(/<[^>]*>/g,'').slice(0,120);
    c.innerHTML=`<div><h3>${publishedText(p.title)}</h3><small>${publishedText(p.date||'')} · ${publishedText(publishedCategoryName(p.category))} · ${p.accessLevel==='members'?'Members Only':'Public'}</small><p>${publishedText(preview)}${preview.length>=120?'…':''}</p></div><div class="small-actions"><button type="button" class="published-edit-button">Edit</button><button type="button" class="gold published-unpublish-button">Unpublish</button><button type="button" class="danger published-delete-button">Delete</button></div>`;
    c.querySelector('.published-edit-button').addEventListener('click',()=>window.editPublished(p.id));
    c.querySelector('.published-unpublish-button').addEventListener('click',()=>window.unpublish(p.id));
    c.querySelector('.published-delete-button').addEventListener('click',()=>window.deletePublished(p.id));
    list.appendChild(c);
  });
}
window.loadPublished=async function(){
  const list=document.getElementById('publishedList');
  if(!list)return;
  list.innerHTML='Loading...';
  try{
    publishedCache=await api(urls.published);
    activePublishedFilter='all';
    ensurePublishedFilterBar();
    renderPublishedPosts();
  }catch(e){list.innerHTML=`<p class="note">${publishedText(e.message)}</p>`}
};

/* Make a loaded published post explicitly editable and preserve its selected
   category/subcategory when moving it to another section. */
window.editPublished=async function(id){
  try{
    const p=await api(`/api/published/${id}`);
    window.editingPostId=id;
    editingPostId=id;
    editingDraftId=null;
    $("postTitle").value=p.title||'';
    setPostCategory(p.category||'curations');
    syncAccess();
    $("postAccess").value=p.accessLevel||'public';
    const editor=$("postEditor");
    editor.contentEditable='true';
    editor.removeAttribute('readonly');
    editor.removeAttribute('disabled');
    editor.innerHTML=p.content||'';
    editor.focus({preventScroll:true});
    const range=document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    const selection=getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    remember(editor);
    $("publishButton").textContent='Update Published Post';
    $("publishButton").onclick=updatePublished;
    switchTab('write');
    setTimeout(()=>{editor.contentEditable='true';editor.focus({preventScroll:true})},50);
    showStatus('Published post loaded for editing. You can change its category and content before updating.');
  }catch(e){showStatus(e.message,true)}
};

const style=document.createElement('style');
style.textContent='.published-filter-bar{display:flex;flex-wrap:wrap;gap:8px;padding:12px;background:#EFE7D8;border:1px solid var(--line);border-radius:7px;margin-top:15px}.published-filter{background:var(--paper);color:var(--brown);border:1px solid var(--line);padding:7px 11px}.published-filter.active{background:var(--brown);color:#fff}.published-card{align-items:flex-start}.published-card p{margin:.45rem 0 0;color:var(--muted)}';
document.head.appendChild(style);

document.addEventListener('DOMContentLoaded',enhance);
window.addEventListener('load',()=>{enhance();if(document.getElementById('publishedList'))ensurePublishedFilterBar()});
setTimeout(enhance,500);
})();
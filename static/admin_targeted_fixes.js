(function () {
  'use strict';
  function currentEditorTarget(target){return target&&target.closest?target.closest('#postEditor, #chapterEditor'):null}
  function paragraphBlock(editor){const selection=window.getSelection();if(!selection||!selection.rangeCount||!editor.contains(selection.anchorNode))return null;let node=selection.anchorNode;if(node&&node.nodeType===Node.TEXT_NODE)node=node.parentElement;return node&&node.closest?(node.closest('p,h1,h2,h3,h4,h5,h6,blockquote,li,div')||editor):editor}
  function indentParagraph(editor,outdent){editor.focus({preventScroll:true});let block=paragraphBlock(editor);if(!block||block===editor){document.execCommand('formatBlock',false,'p');block=paragraphBlock(editor)}if(!block||block===editor)return;const current=parseFloat(block.style.textIndent)||0;const next=Math.max(0,current+(outdent?-2:2));if(next===0)block.style.removeProperty('text-indent');else block.style.textIndent=next+'em'}
  document.addEventListener('keydown',function(event){if(event.key!=='Tab')return;const editor=currentEditorTarget(event.target);if(!editor)return;event.preventDefault();event.stopImmediatePropagation();indentParagraph(editor,event.shiftKey)},true);

  function setPostEditorCategoryMode(){
    const category=document.getElementById('postCategory'),wrapper=document.getElementById('postKWSubcategoryWrap'),sub=document.getElementById('postKWSubcategory');if(!category||!wrapper||!sub)return;
    const oldValue=category.value;const oldKW=['kw_short_stories','kw_poems','kw_vignettes'].includes(oldValue)?oldValue:(oldValue==='kwsnyderwriting'?'kwsnyderwriting':null);
    category.innerHTML='';[['curations','Book Curations'],['reviews','Book Reviews'],['curiosity','Curiosity Cabinet'],['kwsnyderwriting','K. W. Snyder Writing']].forEach(([value,label])=>{const option=document.createElement('option');option.value=value;option.textContent=label;category.appendChild(option)});
    category.value=oldKW?'kwsnyderwriting':(oldValue==='journal'?'kwsnyderwriting':(oldValue||'curations'));if(oldKW&&oldKW!=='kwsnyderwriting')sub.value=oldKW;
    function sync(){const isKW=category.value==='kwsnyderwriting';wrapper.classList.toggle('hidden',!isKW);const access=document.getElementById('postAccess');if(access){access.value=isKW?'members':'public';access.disabled=isKW}}
    category.addEventListener('change',sync);sub.addEventListener('change',sync);sync()
  }
  function removeDuplicateSizeSelectors(){document.querySelectorAll('.toolbar').forEach(toolbar=>{const sizes=Array.from(toolbar.querySelectorAll('select')).filter(select=>{const first=select.options&&select.options[0];return first&&String(first.textContent||'').trim().toLowerCase()==='size'});sizes.slice(1).forEach(select=>select.remove())})}

  function categoryForCard(card){const text=String(card.textContent||'').toLowerCase();if(text.includes('book curations'))return'curations';if(text.includes('book reviews'))return'reviews';if(text.includes('curiosity cabinet'))return'curiosity';if(text.includes('k. w. snyder writing')||text.includes('k.w. snyder writing')||text.includes('short stories')||text.includes('poems')||text.includes('vignettes'))return'kwsnyderwriting';return'other'}
  function enforcePublishedDisplay(){const list=document.getElementById('publishedList');if(!list)return;Array.from(list.children).forEach(card=>{if(!card.classList||!card.classList.contains('card'))return;if(categoryForCard(card)==='kwsnyderwriting'){const small=card.querySelector('small');if(small){const bits=small.textContent.split(' · ');if(bits.length)bits[bits.length-1]='Members Only';small.textContent=bits.join(' · ')}}})}

  function addPublishedFilters(){
    const section=document.getElementById('published'),list=document.getElementById('publishedList');if(!section||!list||document.getElementById('publishedFilters'))return;
    const wrap=document.createElement('div');wrap.id='publishedFilters';wrap.className='actions';wrap.style.marginBottom='8px';const title=document.createElement('strong');title.textContent='Show:';title.style.color='var(--brown)';wrap.appendChild(title);
    const filters=[['all','All'],['curations','Book Curations'],['reviews','Book Reviews'],['curiosity','Curiosity Cabinet'],['kwsnyderwriting','K. W. Snyder Writing']];let active='all';
    function apply(){enforcePublishedDisplay();const cards=Array.from(list.children).filter(card=>card.classList&&card.classList.contains('card'));const counts={all:cards.length,curations:0,reviews:0,curiosity:0,kwsnyderwriting:0};cards.forEach(card=>{const c=categoryForCard(card);if(counts[c]!==undefined)counts[c]++});cards.forEach(card=>{card.classList.toggle('hidden',active!=='all'&&categoryForCard(card)!==active)});wrap.querySelectorAll('button[data-filter]').forEach(button=>{const value=button.dataset.filter;button.className=value===active?'':'light';button.textContent=`${button.dataset.label} (${counts[value]||0})`})}
    filters.forEach(([value,label])=>{const button=document.createElement('button');button.type='button';button.dataset.filter=value;button.dataset.label=label;button.textContent=`${label} (0)`;button.className=value===active?'':'light';button.addEventListener('click',()=>{active=value;apply()});wrap.appendChild(button)});
    const note=section.querySelector('.note');if(note)note.insertAdjacentElement('afterend',wrap);else section.insertBefore(wrap,list);const observer=new MutationObserver(apply);observer.observe(list,{childList:true});apply();
  }

  function addSubscriberDashboardLink(){const tabs=document.querySelector('.tabs');if(!tabs||document.getElementById('subscriberDashboardLink'))return;const button=document.createElement('button');button.id='subscriberDashboardLink';button.type='button';button.className='light';button.textContent='Subscriber Dashboard';button.addEventListener('click',()=>{location.href='/admin/subscribers'});const analyticsTab=document.getElementById('tab-stats');if(analyticsTab)analyticsTab.insertAdjacentElement('afterend',button);else tabs.appendChild(button)}
  function addTodayAnalyticsButton(){const stats=document.getElementById('stats');if(!stats||document.getElementById('analyticsTodayButton'))return;const actions=stats.querySelector('.actions');if(!actions)return;const b=document.createElement('button');b.id='analyticsTodayButton';b.type='button';b.className='light';b.textContent='1 Day — Today';b.onclick=()=>window.loadStats&&window.loadStats('day');actions.insertBefore(b,actions.firstChild);const three=stats.querySelector('.three');if(three&&!document.getElementById('statUniqueVisitors')){const card=document.createElement('div');card.className='card';card.innerHTML='<div><h3>Unique Visitors</h3><small>Selected period</small></div><strong id="statUniqueVisitors">0</strong>';three.appendChild(card)}}
  function normalizeAnalyticsLabel(category,path){const c=String(category||'').toLowerCase();if(path==='/')return'Home';if(c==='site')return'Home';if(c==='journal')return'K. W. Snyder Writing';return({curations:'Book Curations',reviews:'Book Reviews',curiosity:'Curiosity Cabinet',kwsnyderwriting:'K. W. Snyder Writing',kw_short_stories:'K. W. Snyder Writing — Short Stories',kw_poems:'K. W. Snyder Writing — Poems',kw_vignettes:'K. W. Snyder Writing — Vignettes'})[c]||category||'Home'}
  function escAnalytics(value){const d=document.createElement('div');d.textContent=value==null?'':String(value);return d.innerHTML}

  function installAnalyticsOverride(){
    window.loadStats=async function(period='30'){window.analyticsPeriod=period;try{if(typeof window.refreshCounts==='function')await window.refreshCounts();const r=await fetch(`/api/analytics-v3?period=${encodeURIComponent(period)}`,{credentials:'same-origin'});if(!r.ok)throw new Error(`Analytics request failed (${r.status})`);const d=await r.json();const statViews=document.getElementById('statViews');if(statViews)statViews.textContent=d.total_views_today??d.total_views??0;const unique=document.getElementById('statUniqueVisitors');if(unique)unique.textContent=d.unique_visitors??0;
      const cards=document.getElementById('analyticsCategories');if(cards){const map={};(d.content_views||[]).forEach(x=>{const label=normalizeAnalyticsLabel(x.category,x.path);map[label]=(map[label]||0)+Number(x.views||0)});cards.innerHTML=Object.entries(map).sort((a,b)=>b[1]-a[1]).map(([label,views])=>`<div class="card"><span>${escAnalytics(label)}</span><strong>${views}</strong></div>`).join('')||'<p class="note">No section views yet.</p>'}
      if(typeof window.renderAnalytics==='function')window.renderAnalytics({daily:(d.daily_views||[]).map(x=>({day:x.day,views:x.views})),categories:[],posts:(d.content_views||[]).map(x=>({title:x.title,category:normalizeAnalyticsLabel(x.category,x.path),views:x.views}))});
      const heading=document.querySelector('#stats .preview h3');if(heading)heading.textContent=period==='day'?'Views by Hour — Today':'Views Over Time';const totalCard=statViews&&statViews.closest('.card');if(totalCard){const h3=totalCard.querySelector('h3'),small=totalCard.querySelector('small');if(h3)h3.textContent=period==='day'?'Total Views Today':'Total Views';if(small)small.textContent=period==='day'?'Today':'Selected period'}
    }catch(e){if(typeof window.showStatus==='function')window.showStatus(e.message,true);else console.error(e)}}
  }

  // K. W. Snyder Writing is a protected branch. Normalize the editor value
  // before the original publish/save functions ever send it to Flask.
  function installKWPublishGuard(){
    const canonical=function(){
      const c=document.getElementById('postCategory'),sub=document.getElementById('postKWSubcategory');
      let value=(c&&c.value)||'';
      if(value==='journal') value='kwsnyderwriting';
      if(value==='kwsnyderwriting' && sub && sub.value) value=sub.value;
      if(['kw_short_stories','kw_poems','kw_vignettes'].includes(value)) return value;
      if(value==='kwsnyderwriting') return 'kwsnyderwriting';
      return value;
    };
    window.effectivePostCategory=canonical;
    const access=document.getElementById('postAccess');
    const category=document.getElementById('postCategory');
    if(category&&access){const sync=()=>{const value=canonical();const locked=value==='kwsnyderwriting'||value.startsWith('kw_');access.value=locked?'members':'public';access.disabled=locked;};category.addEventListener('change',sync);if(document.getElementById('postKWSubcategory'))document.getElementById('postKWSubcategory').addEventListener('change',sync);sync();}
  }

  function start(){setPostEditorCategoryMode();removeDuplicateSizeSelectors();addPublishedFilters();addSubscriberDashboardLink();addTodayAnalyticsButton();installKWPublishGuard();setTimeout(removeDuplicateSizeSelectors,50);setTimeout(removeDuplicateSizeSelectors,250);setTimeout(installAnalyticsOverride,0);setTimeout(installAnalyticsOverride,100)}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();

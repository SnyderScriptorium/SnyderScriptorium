/* One and only dashboard tab controller. */
(function(){
  'use strict';
  const TABS=['write','drafts','published','manuscripts','about','kwpreview','store','stats','inbox'];
  function installStoreTab(){
    const tabs=document.querySelector('.tabs');
    const dashboard=document.getElementById('dashboard');
    if(!tabs||!dashboard)return;
    if(!document.getElementById('tab-store')){
      const button=document.createElement('button');
      button.id='tab-store'; button.type='button'; button.className='light'; button.textContent='Book Store';
      const manuscriptTab=document.getElementById('tab-manuscripts');
      if(manuscriptTab) manuscriptTab.insertAdjacentElement('afterend',button); else tabs.appendChild(button);
    }
    if(!document.getElementById('store')){
      const section=document.createElement('section');
      section.id='store'; section.className='hidden';
      section.innerHTML='<h2 class="section-title">The Scriptorium Book Store</h2><p class="note">Manage the finished books you are selling through The Scriptorium. This is separate from Manuscripts Studio: a manuscript does not become a product until you add it here.</p><div id="storeAdminMount"></div>';
      dashboard.appendChild(section);
    }
    if(!window.__storeAdminScriptLoaded){
      window.__storeAdminScriptLoaded=true;
      const script=document.createElement('script');
      script.src="{{ url_for('static', filename='admin_store.js') }}";
      script.onload=function(){if(typeof window.initStoreAdmin==='function')window.initStoreAdmin();};
      document.head.appendChild(script);
    }
  }
  function showTab(name){
    if(!TABS.includes(name))return;
    TABS.forEach(function(tab){
      const section=document.getElementById(tab); if(section)section.classList.toggle('hidden',tab!==name);
      const button=document.getElementById('tab-'+tab); if(button)button.className=tab===name?'':'light';
    });
    if(name==='drafts'&&typeof window.loadDrafts==='function')window.loadDrafts();
    if(name==='published'&&typeof window.loadPublished==='function')window.loadPublished();
    if(name==='manuscripts'&&typeof window.loadBooks==='function')window.loadBooks();
    if(name==='about'&&typeof window.loadAbout==='function')window.loadAbout();
    if(name==='kwpreview'&&typeof window.loadKWPreview==='function')window.loadKWPreview();
    if(name==='store'&&typeof window.loadStoreAdmin==='function')window.loadStoreAdmin();
    if(name==='stats'&&typeof window.loadStats==='function')window.loadStats(window.analyticsPeriod||'30');
    if(name==='inbox'&&typeof window.loadInbox==='function')window.loadInbox();
  }
  function install(){
    const tabs=document.querySelector('.tabs'); if(!tabs||tabs.dataset.navigationInstalled==='1')return;
    installStoreTab();
    tabs.dataset.navigationInstalled='1';
    tabs.addEventListener('click',function(event){
      const button=event.target.closest('button[id^="tab-"]'); if(!button)return;
      const name=button.id.slice(4); if(!TABS.includes(name))return;
      event.preventDefault(); showTab(name);
    });
    window.adminShowTab=showTab; window.switchTab=showTab; showTab('write');
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})();

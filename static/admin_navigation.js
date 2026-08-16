/* One and only dashboard tab controller. */
(function(){
  'use strict';
  const TABS=['write','drafts','published','manuscripts','about','kwpreview','stats','inbox'];
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
    if(name==='stats'&&typeof window.loadStats==='function')window.loadStats(window.analyticsPeriod||'30');
    if(name==='inbox'&&typeof window.loadInbox==='function')window.loadInbox();
  }
  function install(){
    const tabs=document.querySelector('.tabs'); if(!tabs||tabs.dataset.navigationInstalled==='1')return;
    tabs.dataset.navigationInstalled='1';
    tabs.addEventListener('click',function(event){
      const button=event.target.closest('button[id^="tab-"]'); if(!button)return;
      const name=button.id.slice(4); if(!TABS.includes(name))return;
      event.preventDefault(); showTab(name);
    });
    window.adminShowTab=showTab;
    window.switchTab=showTab;
    showTab('write');
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})();

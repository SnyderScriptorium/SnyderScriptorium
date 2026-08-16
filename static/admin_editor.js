(function () {
  'use strict';

  const FONTS = [
    'Cormorant Garamond','Playfair Display','Libre Baskerville','Bodoni Moda',
    'EB Garamond','Cinzel','IM FELL English','UnifrakturMaguntia','Italianno',
    'Great Vibes','Alex Brush','Allura','Lora','Crimson Text','Cormorant Infant',
    'Georgia','Times New Roman'
  ];
  const SIZES = [8,9,10,11,12,14,16,18,20,22,24,26,28,32,36,48,72];
  const DEFAULT_COLORS = ['#24333B','#5C4033','#75695D','#8A6A4A','#A67B5B','#6F6257','#7A2929','#405A32','#2F4F4F','#4B3A5A','#7B4B3A','#8B6F47','#000000','#444444','#666666','#FFFFFF'];
  const saved = new WeakMap();
  let recentColors = [];

  function editorFor(toolbar){const next=toolbar&&toolbar.nextElementSibling;return next&&next.classList.contains('editor')?next:null;}
  function remember(editor){const s=window.getSelection();if(!editor||!s||!s.rangeCount)return;if(editor.contains(s.anchorNode)&&editor.contains(s.focusNode))saved.set(editor,s.getRangeAt(0).cloneRange());}
  function restore(editor){const range=saved.get(editor),s=window.getSelection();if(!range||!editor.contains(range.commonAncestorContainer))return false;s.removeAllRanges();s.addRange(range);return true;}
  function command(editor,name,value){editor.focus();restore(editor);document.execCommand('styleWithCSS',false,true);document.execCommand(name,false,value==null?null:value);remember(editor);}
  function applySize(editor,pt){editor.focus();restore(editor);const s=window.getSelection();if(!s||!s.rangeCount||!editor.contains(s.anchorNode))return;const r=s.getRangeAt(0),span=document.createElement('span');span.style.fontSize=pt+'pt';if(r.collapsed){span.appendChild(document.createTextNode('\u200b'));r.insertNode(span);const nr=document.createRange();nr.setStart(span.firstChild,1);nr.collapse(true);s.removeAllRanges();s.addRange(nr);}else{span.appendChild(r.extractContents());r.insertNode(span);const nr=document.createRange();nr.selectNodeContents(span);s.removeAllRanges();s.addRange(nr);}remember(editor);}
  function fill(select,items,label){if(!select)return;select.innerHTML='';const first=document.createElement('option');first.value='';first.textContent=label;first.selected=true;select.appendChild(first);items.forEach(item=>{const o=document.createElement('option');o.value=item;o.textContent=item;if(label==='Font')o.style.fontFamily='"'+item+'", serif';select.appendChild(o);});}
  function getRecentColors(){return recentColors.slice(0,12);}
  function saveRecentColor(color){const normalized=color.toUpperCase();recentColors=recentColors.filter(c=>c!==normalized);recentColors.unshift(normalized);recentColors=recentColors.slice(0,12);return recentColors;}
  function swatch(color,title,onClick){const button=document.createElement('button');button.type='button';button.className='snyder-color-swatch';button.title=title+' '+color;button.setAttribute('aria-label',title+' '+color);button.style.cssText='width:24px!important;height:24px!important;min-width:24px;padding:0!important;border:1px solid #8f816d;border-radius:4px;background:'+color+';cursor:pointer;box-shadow:inset 0 0 0 1px rgba(255,255,255,.35);';button.addEventListener('mousedown',e=>e.preventDefault());button.addEventListener('click',onClick);return button;}
  function renderRecent(container,colors,apply){container.innerHTML='';if(!colors.length){const empty=document.createElement('span');empty.textContent='None yet';empty.style.cssText='font-size:.8rem;color:var(--muted);';container.appendChild(empty);return;}colors.forEach(color=>container.appendChild(swatch(color,'Recent color',()=>apply(color))));}
  function addColor(toolbar,editor,sizeSelect){if(toolbar.querySelector('.snyder-font-color'))return;const wrap=document.createElement('span');wrap.className='snyder-font-color';wrap.style.cssText='position:relative;display:inline-flex;align-items:center;gap:4px;margin:0 2px;';const button=document.createElement('button');button.type='button';button.className='snyder-color-button';button.setAttribute('aria-label','Font color');button.title='Font color — choose from the palette or pick a custom color';button.style.cssText='width:auto!important;min-width:58px;height:30px;padding:4px 8px!important;display:inline-flex;align-items:center;gap:5px;';const label=document.createElement('span');label.textContent='Color';const indicator=document.createElement('span');indicator.style.cssText='width:18px;height:18px;border:1px solid #8f816d;border-radius:3px;background:#24333B;display:inline-block;';button.append(label,indicator);const menu=document.createElement('div');menu.className='snyder-color-menu';menu.style.cssText='display:none;position:absolute;z-index:10000;top:36px;left:0;width:270px;padding:12px;background:#FFFDF8;border:1px solid var(--line);border-radius:7px;box-shadow:0 6px 18px rgba(40,30,20,.18);';const title=document.createElement('div');title.textContent='Font Color';title.style.cssText='font-weight:600;color:var(--brown);margin-bottom:8px;';menu.appendChild(title);const paletteTitle=document.createElement('div');paletteTitle.textContent='Color Palette';paletteTitle.style.cssText='font-size:.8rem;color:var(--muted);margin-bottom:5px;';menu.appendChild(paletteTitle);const palette=document.createElement('div');palette.style.cssText='display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px;';menu.appendChild(palette);const recentTitle=document.createElement('div');recentTitle.textContent='Recent Colors';recentTitle.style.cssText='font-size:.8rem;color:var(--muted);margin-bottom:5px;';menu.appendChild(recentTitle);const recent=document.createElement('div');recent.style.cssText='display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px;';menu.appendChild(recent);const customRow=document.createElement('div');customRow.style.cssText='display:flex;align-items:center;gap:8px;border-top:1px solid var(--line);padding-top:9px;';const customLabel=document.createElement('span');customLabel.textContent='Custom';customLabel.style.cssText='font-size:.8rem;color:var(--muted);';const input=document.createElement('input');input.type='color';input.value='#24333B';input.setAttribute('aria-label','Choose custom font color');input.style.cssText='width:40px!important;height:30px!important;padding:2px!important;cursor:pointer;';customRow.append(customLabel,input);menu.appendChild(customRow);function applyColor(color){editor.focus();restore(editor);command(editor,'foreColor',color);indicator.style.background=color;renderRecent(recent,saveRecentColor(color),applyColor);menu.style.display='none';}DEFAULT_COLORS.forEach(color=>palette.appendChild(swatch(color,'Palette color',()=>applyColor(color))));renderRecent(recent,getRecentColors(),applyColor);button.addEventListener('mousedown',()=>remember(editor));button.addEventListener('click',e=>{e.stopPropagation();menu.style.display=menu.style.display==='none'?'block':'none';});input.addEventListener('mousedown',()=>remember(editor));input.addEventListener('input',()=>applyColor(input.value));document.addEventListener('click',e=>{if(!wrap.contains(e.target))menu.style.display='none';});wrap.append(button,menu);if(sizeSelect)sizeSelect.insertAdjacentElement('afterend',wrap);else toolbar.appendChild(wrap);}

  function selectedBlock(editor){
    const s=window.getSelection();
    if(!s||!s.rangeCount||!editor.contains(s.anchorNode)) return null;
    let node=s.anchorNode;
    if(node&&node.nodeType===Node.TEXT_NODE) node=node.parentElement;
    return node&&node.closest ? (node.closest('p,h1,h2,h3,h4,h5,h6,blockquote,pre,div,li')||editor) : editor;
  }

  function changeIndent(editor,delta){
    const block=selectedBlock(editor);
    if(!block||block===editor) return false;
    const current=parseFloat(block.style.textIndent)||0;
    const next=Math.max(0,current+delta);
    if(next===0) block.style.removeProperty('text-indent');
    else block.style.textIndent=next+'em';
    remember(editor);
    return true;
  }

  function installKeyboardBehavior(editor){
    if(editor.dataset.snyderKeyboardFix==='1') return;
    editor.dataset.snyderKeyboardFix='1';
    editor.addEventListener('keydown',function(event){
      if(event.key!=='Tab'||event.ctrlKey||event.metaKey||event.altKey) return;
      if(!editor.contains(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
      remember(editor);
      if(event.shiftKey) changeIndent(editor,-2);
      else changeIndent(editor,2);
    },true);
  }

  function installDraftSaveGuard(){
    if(window.__snyderDraftSaveGuardInstalled) return;
    window.__snyderDraftSaveGuardInstalled=true;
    let saving=false;
    const original=window.saveDraft;
    if(typeof original!=='function') return;

    window.saveDraft=function(){
      if(saving) return false;
      saving=true;
      const button=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Save as Draft');
      const originalText=button?button.textContent:'';
      if(button){button.disabled=true;button.textContent='Saving…';button.setAttribute('aria-busy','true');}
      let result;
      try{result=original.apply(this,arguments);}catch(error){unlock();throw error;}
      if(result&&typeof result.finally==='function') result.finally(unlock);
      else waitForSaveResult();
      return result;

      function unlock(){
        if(!saving)return;
        saving=false;
        if(button){button.disabled=false;button.textContent=originalText||'Save as Draft';button.removeAttribute('aria-busy');}
      }
      function waitForSaveResult(){
        const status=document.getElementById('status');
        const started=Date.now();
        const timer=setInterval(function(){
          const visible=status&&!status.classList.contains('hidden');
          const elapsed=Date.now()-started;
          if(visible||elapsed>=8000){clearInterval(timer);unlock();}
        },100);
      }
    };
  }

  function enhance(toolbar){const editor=editorFor(toolbar);if(!editor||toolbar.dataset.adminEditorReady==='1')return;toolbar.dataset.adminEditorReady='1';const selects=toolbar.querySelectorAll('select');if(selects[0]){fill(selects[0],FONTS,'Font');selects[0].onmousedown=()=>remember(editor);selects[0].onchange=function(){if(this.value)command(editor,'fontName',this.value);this.selectedIndex=0;};}if(selects[1]){fill(selects[1],SIZES.map(String),'Size');[...selects[1].options].forEach((o,i)=>{if(i)o.textContent=o.value+' pt';});selects[1].onmousedown=()=>remember(editor);selects[1].onchange=function(){if(this.value)applySize(editor,Number(this.value));this.selectedIndex=0;};addColor(toolbar,editor,selects[1]);installKeyboardBehavior(editor);}
  }
  function run(){document.querySelectorAll('.toolbar').forEach(enhance);document.querySelectorAll('.editor').forEach(e=>{e.contentEditable='true';installKeyboardBehavior(e);});installDraftSaveGuard();}
  document.addEventListener('selectionchange',()=>{document.querySelectorAll('.editor').forEach(e=>remember(e));});
  document.addEventListener('DOMContentLoaded',run);run();setTimeout(run,100);setTimeout(run,500);
})();

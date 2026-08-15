(function(){
'use strict';

// Admin editor enhancements. This file must not control dashboard navigation.
const EDITOR='.editor';
const ranges=new WeakMap();
const FONT_OPTIONS=[
 ['Cormorant Garamond','Cormorant Garamond'],['Playfair Display','Playfair Display'],['Libre Baskerville','Libre Baskerville'],['Bodoni Moda','Bodoni Moda'],['EB Garamond','EB Garamond'],['Cinzel','Cinzel'],['IM FELL English','IM FELL English'],['UnifrakturMaguntia','UnifrakturMaguntia'],['Italianno','Italianno'],['Great Vibes','Great Vibes'],['Alex Brush','Alex Brush'],['Allura','Allura'],['Lora','Lora'],['Crimson Text','Crimson Text'],['Cormorant Infant','Cormorant Infant'],['Georgia','Georgia'],['Times New Roman','Times New Roman']
];
const FONT_SIZES=[8,9,10,11,12,14,16,18,20,22,24,26,28,32,36,48,72];
function loadEditorFonts(){if(document.getElementById('snyder-editor-fonts'))return;const link=document.createElement('link');link.id='snyder-editor-fonts';link.rel='stylesheet';link.href='https://fonts.googleapis.com/css2?family=Alex+Brush&family=Allura&family=Bodoni+Moda:opsz,wght@6..96,400;6..96,500;6..96,600&family=Cinzel:wght@400;500;600&family=Cormorant+Garamond:wght@400;500;600&family=Cormorant+Infant:wght@400;500;600&family=Crimson+Text:wght@400;600&family=EB+Garamond:wght@400;500;600&family=Great+Vibes&family=IM+Fell+English&family=Italianno&family=Lora:wght@400;500;600&family=Libre+Baskerville:wght@400;700&family=Playfair+Display:wght@400;500;600;700&family=UnifrakturMaguntia&display=swap';document.head.appendChild(link)}
function inside(editor){const s=getSelection();return !!(editor&&s&&s.rangeCount&&editor.contains(s.anchorNode)&&editor.contains(s.focusNode))}
function remember(editor){const s=getSelection();if(inside(editor))ranges.set(editor,s.getRangeAt(0).cloneRange())}
function restore(editor){const r=ranges.get(editor),s=getSelection();if(!r||!editor.contains(r.commonAncestorContainer))return false;s.removeAllRanges();s.addRange(r);return true}
function focusEditor(editor){if(!editor)return false;editor.contentEditable='true';editor.removeAttribute('disabled');editor.removeAttribute('readonly');editor.focus({preventScroll:true});return true}
function keepScroll(editor,fn){const x=scrollX,y=scrollY,ex=editor.scrollLeft,ey=editor.scrollTop;fn();scrollTo(x,y);editor.scrollLeft=ex;editor.scrollTop=ey}
function selectedBlock(editor){const s=getSelection();if(!inside(editor))return null;let n=s.anchorNode;if(n&&n.nodeType===3)n=n.parentElement;return n&&n.closest?n.closest('p,h1,h2,h3,h4,h5,h6,blockquote,pre,div,li')||editor:editor}
function indent(editor,outdent){focusEditor(editor);restore(editor);let block=selectedBlock(editor);if(block===editor){document.execCommand('formatBlock',false,'p');block=selectedBlock(editor)}if(!block||block===editor)return;const current=parseFloat(block.style.textIndent)||0;const next=Math.max(0,current+(outdent?-2:2));if(next===0)block.style.removeProperty('text-indent');else block.style.textIndent=next+'em';remember(editor)}
function cmd(editor,command,value){focusEditor(editor);restore(editor);document.execCommand('styleWithCSS',false,true);keepScroll(editor,()=>document.execCommand(command,false,value==null?null:value));remember(editor)}
function size(editor,pt){focusEditor(editor);restore(editor);const s=getSelection();if(!s.rangeCount||!inside(editor))return;const r=s.getRangeAt(0);keepScroll(editor,()=>{const span=document.createElement('span');span.style.fontSize=pt+'pt';if(r.collapsed){span.appendChild(document.createTextNode('\u200b'));r.insertNode(span);const n=document.createRange();n.setStart(span.firstChild,1);n.collapse(true);s.removeAllRanges();s.addRange(n)}else{span.appendChild(r.extractContents());r.insertNode(span);const n=document.createRange();n.selectNodeContents(span);s.removeAllRanges();s.addRange(n)}});remember(editor)}
function opt(select,value,text){const o=document.createElement('option');o.value=value;o.textContent=text;select.appendChild(o)}
const RECENT_COLORS_KEY='snyderEditorRecentColors';
function recentColors(){try{const a=JSON.parse(localStorage.getItem(RECENT_COLORS_KEY)||'[]');return Array.isArray(a)?a.filter(x=>/^#[0-9a-f]{6}$/i.test(x)).slice(0,12):[]}catch(_){return[]}}
function saveRecentColor(color){color=String(color||'').toLowerCase();if(!/^#[0-9a-f]{6}$/.test(color))return;const a=[color,...recentColors().filter(x=>x!==color)].slice(0,12);try{localStorage.setItem(RECENT_COLORS_KEY,JSON.stringify(a))}catch(_) {}}
function makeColorPicker(editor,initial){const wrap=document.createElement('span');wrap.className='editor-color-picker';wrap.title='Font color — choose any color or reuse a recent color';const input=document.createElement('input');input.type='color';input.value=initial||'#24333B';input.className='editor-font-color';input.setAttribute('aria-label','Choose font color');const recent=document.createElement('div');recent.className='editor-recent-colors';recent.setAttribute('aria-label','Recently used font colors');function render(){recent.replaceChildren();recentColors().forEach(color=>{const b=document.createElement('button');b.type='button';b.className='editor-recent-color';b.style.backgroundColor=color;b.title='Reuse '+color;b.setAttribute('aria-label','Reuse '+color);b.addEventListener('mousedown',e=>{e.preventDefault();remember(editor)});b.addEventListener('click',e=>{e.preventDefault();focusEditor(editor);restore(editor);input.value=color;cmd(editor,'foreColor',color);saveRecentColor(color);render()});recent.appendChild(b)})}input.addEventListener('mousedown',()=>remember(editor));input.addEventListener('change',()=>{cmd(editor,'foreColor',input.value);saveRecentColor(input.value);render()});wrap.append(input,recent);render();return wrap}
function enhanceToolbar(toolbar){if(!toolbar||toolbar.dataset.snyderEnhanced==='1')return;const editor=toolbar.nextElementSibling&&toolbar.nextElementSibling.matches(EDITOR)?toolbar.nextElementSibling:null;if(!editor)return;toolbar.dataset.snyderEnhanced='1';const selects=toolbar.querySelectorAll('select');const font=selects[0];const sizeSelect=selects[1];if(font){font.replaceChildren();opt(font,'','Font');FONT_OPTIONS.forEach(([value,label])=>{const o=document.createElement('option');o.value=value;o.textContent=label;o.style.fontFamily='"'+value+'",serif';font.appendChild(o)});font.addEventListener('mousedown',()=>remember(editor));font.addEventListener('change',()=>{if(font.value)cmd(editor,'fontName',font.value);font.selectedIndex=0})}if(sizeSelect){sizeSelect.replaceChildren();opt(sizeSelect,'','Size');FONT_SIZES.forEach(n=>opt(sizeSelect,String(n),n+'pt'));sizeSelect.addEventListener('mousedown',()=>remember(editor));sizeSelect.addEventListener('change',()=>{if(sizeSelect.value)size(editor,Number(sizeSelect.value));sizeSelect.selectedIndex=0})}const divider=toolbar.querySelector('.divider');const colorPicker=makeColorPicker(editor,'#24333B');if(divider)toolbar.insertBefore(colorPicker,divider);else toolbar.appendChild(colorPicker);const format=document.createElement('select');format.title='Paragraph / heading style';[['P','Paragraph'],['H1','Heading 1'],['H2','Heading 2'],['H3','Heading 3'],['H4','Heading 4'],['BLOCKQUOTE','Quote']].forEach(([v,t])=>opt(format,v,t));format.addEventListener('mousedown',()=>remember(editor));format.addEventListener('change',()=>{if(format.value)cmd(editor,'formatBlock',format.value);format.selectedIndex=0});if(font)toolbar.insertBefore(format,font);else toolbar.prepend(format);toolbar.querySelectorAll('button').forEach(button=>button.addEventListener('mousedown',()=>remember(editor)))}
function applyEditorBehavior(editor){if(editor.dataset.snyderEditorBehavior==='1')return;editor.dataset.snyderEditorBehavior='1';editor.contentEditable='true';editor.addEventListener('focus',()=>remember(editor));editor.addEventListener('mouseup',()=>remember(editor));editor.addEventListener('keyup',()=>remember(editor));editor.addEventListener('keydown',event=>{if(event.key!=='Tab')return;event.preventDefault();event.stopImmediatePropagation();indent(editor,event.shiftKey)},true);editor.addEventListener('paste',event=>{event.preventDefault();event.stopPropagation();focusEditor(editor);restore(editor);const html=event.clipboardData&&event.clipboardData.getData('text/html');const text=event.clipboardData&&event.clipboardData.getData('text/plain')||'';const value=html||text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\r\n|\r|\n/g,'<br>');if(value)document.execCommand('insertHTML',false,value);remember(editor)})}

// Robust K. W. Snyder Writing category/subcategory restoration. This runs
// after the inline admin script, so resumeDraft/editPublished always gets the
// same function regardless of whether the editor was started fresh or loaded
// from a draft/published record.
const KW_SUBCATEGORIES=new Set(['kwsnyderwriting','kw_short_stories','kw_poems','kw_vignettes']);
function installKWCategoryRestorer(){
  const c=document.getElementById('postCategory'),wrap=document.getElementById('postKWSubcategoryWrap'),sub=document.getElementById('postKWSubcategory');
  if(!c||!wrap||!sub)return false;
  function set(value){
    let v=String(value||'').trim().toLowerCase();
    if(v==='journal'||v==='kw_snyder_writing'||v==='kw-snyder-writing')v='kwsnyderwriting';
    if(KW_SUBCATEGORIES.has(v)){
      c.value='kwsnyderwriting';
      sub.value=v;
      c.dataset.effectiveKW=v;
      wrap.classList.remove('hidden');
    }else{
      c.value=v||'curations';
      delete c.dataset.effectiveKW;
      wrap.classList.add('hidden');
    }
    if(typeof window.syncAccess==='function')window.syncAccess();
    else{
      const access=document.getElementById('postAccess');
      if(access){const locked=c.value==='kwsnyderwriting';access.value=locked?'members':'public';access.disabled=locked;}
    }
  }
  window.setPostCategory=set;
  window.effectivePostCategory=function(){
    const value=c.value;
    return value==='kwsnyderwriting'?(c.dataset.effectiveKW||sub.value||'kwsnyderwriting'):value;
  };
  if(!c.dataset.kwRestorerWired){
    c.dataset.kwRestorerWired='1';
    c.addEventListener('change',()=>{
      if(c.value==='kwsnyderwriting'){
        wrap.classList.remove('hidden');
        if(!KW_SUBCATEGORIES.has(sub.value))sub.value='kwsnyderwriting';
        c.dataset.effectiveKW=sub.value;
      }else{
        wrap.classList.add('hidden');
        delete c.dataset.effectiveKW;
      }
    });
    sub.addEventListener('change',()=>{if(c.value==='kwsnyderwriting')c.dataset.effectiveKW=sub.value});
  }
  return true;
}

function install(){if(window.__snyderAdminFixesInstalled)return;window.__snyderAdminFixesInstalled=true;loadEditorFonts();document.querySelectorAll('.toolbar').forEach(enhanceToolbar);document.querySelectorAll(EDITOR).forEach(applyEditorBehavior);installKWCategoryRestorer()}
window.resetManuscriptEditor=function(){const title=document.getElementById('chapterTitle');const number=document.getElementById('chapterNumber');const editor=document.getElementById('chapterEditor');const published=document.getElementById('chapterPublished');if(title)title.value='';if(number)number.value='';if(editor)editor.innerHTML='';if(published)published.checked=false};

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})();
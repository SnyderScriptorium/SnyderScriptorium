(function(){
'use strict';
function legacyToHtml(value){
  const text=String(value||'');
  if(!text.trim()) return '';
  if(/<\/?(p|div|br|h[1-6]|ul|ol|li|blockquote|strong|em|u|a)\b/i.test(text)) return text;
  return text.split(/\n\s*\n/).map(part=>`<p>${part.trim().replace(/\n/g,'<br>')}</p>`).join('');
}
function install(){
  const source=document.getElementById('aboutEditor');
  if(!source || source.dataset.richReady==='1') return;
  source.dataset.richReady='1';
  source.style.display='none';
  const wrap=document.createElement('div');
  wrap.className='about-rich-editor-wrap';
  const toolbar=document.createElement('div');
  toolbar.className='toolbar';
  const editor=document.createElement('div');
  editor.id='aboutRichEditor';
  editor.className='editor';
  editor.contentEditable='true';
  editor.setAttribute('aria-label','About Page rich text editor');
  function button(label,cmd,value){
    const b=document.createElement('button'); b.type='button'; b.textContent=label;
    b.addEventListener('mousedown',e=>e.preventDefault());
    b.addEventListener('click',()=>{editor.focus();document.execCommand(cmd,false,value||null);sync();});
    toolbar.appendChild(b);
  }
  const font=document.createElement('select');
  [['','Font'],['Cormorant Garamond','Cormorant Garamond'],['Playfair Display','Playfair Display'],['Libre Baskerville','Libre Baskerville'],['EB Garamond','EB Garamond'],['Georgia','Georgia'],['Times New Roman','Times New Roman']].forEach(([v,t])=>{const o=document.createElement('option');o.value=v;o.textContent=t;font.appendChild(o)});
  font.addEventListener('change',()=>{if(font.value){editor.focus();document.execCommand('fontName',false,font.value);sync();font.selectedIndex=0}});
  toolbar.appendChild(font);
  const size=document.createElement('select');
  [['','Size'],['2','12pt'],['3','14pt'],['4','18pt'],['5','24pt'],['6','32pt']].forEach(([v,t])=>{const o=document.createElement('option');o.value=v;o.textContent=t;size.appendChild(o)});
  size.addEventListener('change',()=>{if(size.value){editor.focus();document.execCommand('fontSize',false,size.value);sync();size.selectedIndex=0}});
  toolbar.appendChild(size);
  button('B','bold'); button('I','italic'); button('U','underline');
  button('Left','justifyLeft'); button('Center','justifyCenter'); button('Right','justifyRight'); button('Justify','justifyFull');
  button('• List','insertUnorderedList'); button('1. List','insertOrderedList'); button('Clear','removeFormat');
  wrap.append(toolbar,editor);
  source.parentNode.insertBefore(wrap,source);
  function sync(){source.value=editor.innerHTML;}
  editor.addEventListener('input',sync);
  editor.addEventListener('blur',sync);
  let last='';
  function refreshFromSource(){
    if(document.activeElement===editor) return;
    if(source.value!==last){
      editor.innerHTML=legacyToHtml(source.value);
      source.value=editor.innerHTML;
      last=source.value;
    }
  }
  refreshFromSource();
  setInterval(refreshFromSource,500);
  const form=source.closest('section')||source.closest('form');
  if(form) form.addEventListener('submit',sync);
  window.addEventListener('beforeunload',sync);
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install,{once:true}); else install();
})();

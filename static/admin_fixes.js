(function(){
'use strict';
const EDITOR='.editor';
const ranges=new WeakMap();
function ed(n){return n&&n.closest?n.closest(EDITOR):null}
function inside(e){const s=getSelection();return !!(e&&s&&s.rangeCount&&e.contains(s.anchorNode)&&e.contains(s.focusNode))}
function remember(e){const s=getSelection();if(inside(e))ranges.set(e,s.getRangeAt(0).cloneRange())}
function restore(e){const r=ranges.get(e),s=getSelection();if(!r||!e.contains(r.commonAncestorContainer))return false;s.removeAllRanges();s.addRange(r);return true}
function focus(e){if(!e)return false;e.contentEditable='true';e.removeAttribute('disabled');e.removeAttribute('readonly');e.focus({preventScroll:true});restore(e);return true}
function keep(e,fn){const x=scrollX,y=scrollY,ex=e.scrollLeft,ey=e.scrollTop;fn();scrollTo(x,y);e.scrollLeft=ex;e.scrollTop=ey;requestAnimationFrame(()=>{scrollTo(x,y);e.scrollLeft=ex;e.scrollTop=ey})}
function block(e){if(!inside(e))return null;let n=getSelection().anchorNode;if(n&&n.nodeType===3)n=n.parentElement;return n&&n.closest?(n.closest('p,h1,h2,h3,h4,h5,h6,blockquote,pre,div,li')||e):e}
function indent(e,out){const b=block(e);if(!b||b===e)return;const cur=parseFloat(b.style.marginLeft)||0;const next=Math.max(0,cur+(out?-2:2));b.style.marginLeft=next?next+'em':''}

document.addEventListener('focusin',e=>{const x=ed(e.target);if(x)x.contentEditable='true'},true);
document.addEventListener('click',e=>{const x=ed(e.target);if(x){x.contentEditable='true';remember(x)}},true);
document.addEventListener('selectionchange',()=>document.querySelectorAll(EDITOR).forEach(x=>{if(inside(x))remember(x)}));
// Do not intercept paste. Native paste keeps Blogger/Word/Docs formatting and leaves it editable.
document.addEventListener('paste',e=>{const x=ed(e.target);if(x){x.contentEditable='true';remember(x)}},true);
// One shared Tab behavior for both editors.
document.addEventListener('keydown',e=>{const x=ed(e.target);if(!x)return;if(e.key==='Tab'){e.preventDefault();e.stopImmediatePropagation();x.contentEditable='true';remember(x);focus(x);keep(x,()=>indent(x,e.shiftKey));remember(x)}},true);

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
document.addEventListener('DOMContentLoaded',enhance);window.addEventListener('load',enhance);setTimeout(enhance,500);
})();
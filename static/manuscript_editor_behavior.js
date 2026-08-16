(function(){
  'use strict';

  const EDITOR_SELECTOR = '.editor';
  const FONT_SIZES = [8,9,10,11,12,14,16,18,20,22,24,26,28,32,36,48,72];

  function inside(editor){
    const s = window.getSelection();
    return !!(editor && s && s.rangeCount && editor.contains(s.anchorNode) && editor.contains(s.focusNode));
  }

  function remember(editor){
    const s = window.getSelection();
    if(inside(editor)) editor.__snyderRange = s.getRangeAt(0).cloneRange();
  }

  function restore(editor){
    const r = editor.__snyderRange;
    const s = window.getSelection();
    if(!r || !editor.contains(r.commonAncestorContainer)) return false;
    s.removeAllRanges();
    s.addRange(r);
    return true;
  }

  function selectedBlock(editor){
    const s = window.getSelection();
    if(!inside(editor)) return null;
    let n = s.anchorNode;
    if(n && n.nodeType === 3) n = n.parentElement;
    return n && n.closest ? n.closest('p,h1,h2,h3,h4,h5,h6,blockquote,pre,div,li') : editor;
  }

  function removeOneIndent(editor){
    const block = selectedBlock(editor);
    if(!block || block === editor) return false;
    const current = parseFloat(block.style.textIndent) || 0;
    if(current <= 0) return false;
    const next = Math.max(0, current - 2);
    if(next === 0) block.style.removeProperty('text-indent');
    else block.style.textIndent = next + 'em';
    remember(editor);
    return true;
  }

  function installBackspace(editor){
    if(editor.dataset.snyderBackspaceFix === '1') return;
    editor.dataset.snyderBackspaceFix = '1';
    editor.addEventListener('keydown', function(event){
      if(event.ctrlKey || event.metaKey || event.altKey) return;

      // Shift+Tab should act exactly like Backspace in the manuscript editor.
      if(event.key === 'Tab' && event.shiftKey){
        const s = window.getSelection();
        if(!s || !s.rangeCount || !inside(editor)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        editor.focus({preventScroll:true});
        document.execCommand('delete', false, null);
        remember(editor);
        return;
      }

      if(event.key !== 'Backspace') return;
      const s = window.getSelection();
      if(!s || !s.rangeCount || !s.isCollapsed || !inside(editor)) return;
      const r = s.getRangeAt(0);
      if(r.startOffset !== 0) return;
      if(removeOneIndent(editor)){
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }, true);
  }

  function makeSizeSelect(oldSelect, editor){
    if(!oldSelect || oldSelect.dataset.snyderExactPt === '1') return;
    const select = oldSelect.cloneNode(false);
    select.dataset.snyderExactPt = '1';
    select.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Size';
    select.appendChild(placeholder);
    FONT_SIZES.forEach(function(pt){
      const option = document.createElement('option');
      option.value = String(pt);
      option.textContent = pt + 'pt';
      select.appendChild(option);
    });
    select.addEventListener('mousedown', function(){ remember(editor); });
    select.addEventListener('change', function(){
      const pt = Number(select.value);
      if(!pt) return;
      if(!restore(editor)) return;
      const s = window.getSelection();
      if(!s.rangeCount || !inside(editor)) return;
      const r = s.getRangeAt(0);
      const span = document.createElement('span');
      span.style.setProperty('font-size', pt + 'pt');
      if(r.collapsed){
        span.appendChild(document.createTextNode('\u200b'));
        r.insertNode(span);
        const caret = document.createRange();
        caret.setStart(span.firstChild, 1);
        caret.collapse(true);
        s.removeAllRanges();
        s.addRange(caret);
      } else {
        span.appendChild(r.extractContents());
        r.insertNode(span);
        const selected = document.createRange();
        selected.selectNodeContents(span);
        s.removeAllRanges();
        s.addRange(selected);
      }
      remember(editor);
      select.selectedIndex = 0;
    });
    oldSelect.replaceWith(select);
  }

  function makeFontSelect(oldSelect, editor){
    if(!oldSelect || oldSelect.dataset.snyderExactFont === '1') return;
    const select = oldSelect.cloneNode(true);
    select.dataset.snyderExactFont = '1';
    select.addEventListener('mousedown', function(){ remember(editor); });
    select.addEventListener('change', function(){
      if(!select.value) return;
      restore(editor);
      editor.focus({preventScroll:true});
      document.execCommand('styleWithCSS', false, true);
      document.execCommand('fontName', false, select.value);
      remember(editor);
      select.selectedIndex = 0;
    });
    oldSelect.replaceWith(select);
  }

  function normalizeEditor(editor){
    if(editor.dataset.snyderEditorNormalized === '1') return;
    editor.dataset.snyderEditorNormalized = '1';
    editor.style.fontSize = '11pt';
    editor.style.fontFamily = 'Georgia, "Times New Roman", serif';
    installBackspace(editor);

    const toolbar = editor.previousElementSibling;
    if(!toolbar || !toolbar.classList.contains('toolbar')) return;
    const selects = toolbar.querySelectorAll('select');
    if(selects[0]) makeFontSelect(selects[0], editor);
    if(selects[1]) makeSizeSelect(selects[1], editor);
  }

  function install(){
    document.querySelectorAll(EDITOR_SELECTOR).forEach(normalizeEditor);
  }

  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function(){ setTimeout(install, 0); }, {once:true});
  else setTimeout(install, 0);
})();

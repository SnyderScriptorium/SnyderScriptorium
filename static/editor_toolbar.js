(function () {
  'use strict';

  const FONTS = [
    'Cormorant Garamond','Playfair Display','Libre Baskerville','Bodoni Moda',
    'EB Garamond','Cinzel','IM FELL English','UnifrakturMaguntia','Italianno',
    'Great Vibes','Alex Brush','Allura','Lora','Crimson Text','Cormorant Infant',
    'Georgia','Times New Roman'
  ];
  const SIZES = [8,9,10,11,12,14,16,18,20,22,24,26,28,32,36,48,72];
  const saved = new WeakMap();

  function editorFor(toolbar) {
    const next = toolbar && toolbar.nextElementSibling;
    return next && next.classList.contains('editor') ? next : null;
  }

  function remember(editor) {
    const s = window.getSelection();
    if (!editor || !s || !s.rangeCount) return;
    if (editor.contains(s.anchorNode) && editor.contains(s.focusNode)) {
      saved.set(editor, s.getRangeAt(0).cloneRange());
    }
  }

  function restore(editor) {
    const range = saved.get(editor), s = window.getSelection();
    if (!range || !editor.contains(range.commonAncestorContainer)) return false;
    s.removeAllRanges(); s.addRange(range); return true;
  }

  function command(editor, name, value) {
    editor.focus(); restore(editor);
    document.execCommand('styleWithCSS', false, true);
    document.execCommand(name, false, value == null ? null : value);
    remember(editor);
  }

  function applySize(editor, pt) {
    editor.focus(); restore(editor);
    const s = window.getSelection();
    if (!s || !s.rangeCount || !editor.contains(s.anchorNode)) return;
    const r = s.getRangeAt(0);
    const span = document.createElement('span');
    span.style.fontSize = pt + 'pt';
    if (r.collapsed) {
      span.appendChild(document.createTextNode('\u200b'));
      r.insertNode(span);
      const nr = document.createRange(); nr.setStart(span.firstChild, 1); nr.collapse(true);
      s.removeAllRanges(); s.addRange(nr);
    } else {
      span.appendChild(r.extractContents()); r.insertNode(span);
      const nr = document.createRange(); nr.selectNodeContents(span);
      s.removeAllRanges(); s.addRange(nr);
    }
    remember(editor);
  }

  function fill(select, items, label) {
    if (!select) return;
    select.innerHTML = '';
    const first = document.createElement('option');
    first.value = ''; first.textContent = label; first.disabled = false; first.selected = true;
    select.appendChild(first);
    items.forEach(item => {
      const o = document.createElement('option');
      o.value = item; o.textContent = item;
      if (label === 'Font') o.style.fontFamily = '"' + item + '", serif';
      select.appendChild(o);
    });
  }

  function addColor(toolbar, editor) {
    if (toolbar.querySelector('.snyder-font-color')) return;
    const wrap = document.createElement('span');
    wrap.className = 'snyder-font-color';
    wrap.title = 'Font color';
    wrap.style.cssText = 'display:inline-flex;align-items:center;gap:4px;margin-left:2px;';
    const label = document.createElement('span');
    label.textContent = 'Color';
    label.style.cssText = 'font-size:.85rem;color:var(--brown);';
    const input = document.createElement('input');
    input.type = 'color'; input.value = '#24333B';
    input.setAttribute('aria-label','Font color');
    input.style.cssText = 'width:34px!important;height:30px!important;padding:2px!important;cursor:pointer;';
    input.addEventListener('mousedown', () => remember(editor));
    input.addEventListener('input', () => command(editor, 'foreColor', input.value));
    wrap.append(label, input); toolbar.appendChild(wrap);
  }

  function enhance(toolbar) {
    const editor = editorFor(toolbar);
    if (!editor) return;
    const selects = toolbar.querySelectorAll('select');
    if (selects[0]) {
      fill(selects[0], FONTS, 'Font');
      selects[0].onmousedown = () => remember(editor);
      selects[0].onchange = function () { if (this.value) command(editor,'fontName',this.value); this.selectedIndex = 0; };
    }
    if (selects[1]) {
      fill(selects[1], SIZES.map(String), 'Size');
      [...selects[1].options].forEach((o,i) => { if (i) o.textContent = o.value + ' pt'; });
      selects[1].onmousedown = () => remember(editor);
      selects[1].onchange = function () { if (this.value) applySize(editor, Number(this.value)); this.selectedIndex = 0; };
    }
    addColor(toolbar, editor);
    toolbar.querySelectorAll('button').forEach(button => {
      button.addEventListener('mousedown', () => remember(editor), true);
    });
  }

  function run() {
    document.querySelectorAll('.toolbar').forEach(enhance);
    document.querySelectorAll('.editor').forEach(e => e.contentEditable = 'true');
  }

  document.addEventListener('selectionchange', () => {
    document.querySelectorAll('.editor').forEach(e => remember(e));
  });
  document.addEventListener('DOMContentLoaded', run);
  run();
  setTimeout(run, 100);
  setTimeout(run, 500);
  setTimeout(run, 1500);
})();

(function () {
  'use strict';

  const savedRanges = new WeakMap();
  const EDITOR_SELECTOR = '.editor[contenteditable="true"]';

  function resetChapterEditor() {
    const title = document.getElementById('chapterTitle');
    const number = document.getElementById('chapterNumber');
    const content = document.getElementById('chapterEditor');
    const published = document.getElementById('chapterPublished');
    if (title) title.value = '';
    if (number) number.value = '';
    if (content) content.innerHTML = '';
    if (published) published.checked = false;
  }

  function editorForNode(node) {
    return node && node.closest ? node.closest(EDITOR_SELECTOR) : null;
  }

  function selectionInside(editor) {
    const sel = window.getSelection();
    return !!(editor && sel && sel.rangeCount && editor.contains(sel.anchorNode) && editor.contains(sel.focusNode));
  }

  function rememberSelection(editor) {
    if (!editor) return;
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !selectionInside(editor)) return;
    savedRanges.set(editor, sel.getRangeAt(0).cloneRange());
  }

  function restoreSelection(editor) {
    if (!editor) return false;
    const range = savedRanges.get(editor);
    if (!range || !editor.contains(range.commonAncestorContainer)) return false;
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  }

  function focusEditorPreservingSelection(editor) {
    if (!editor) return false;
    const hadSaved = restoreSelection(editor);
    editor.focus({ preventScroll: true });
    if (hadSaved) restoreSelection(editor);
    return selectionInside(editor);
  }

  document.addEventListener('selectionchange', function () {
    document.querySelectorAll(EDITOR_SELECTOR).forEach(editor => {
      if (selectionInside(editor)) rememberSelection(editor);
    });
  });

  document.addEventListener('mousedown', function (event) {
    const button = event.target.closest && event.target.closest('.toolbar button, .toolbar select, .toolbar input[type="color"]');
    if (!button) return;
    const toolbar = button.closest('.toolbar');
    const editor = toolbar && toolbar.nextElementSibling && toolbar.nextElementSibling.matches(EDITOR_SELECTOR)
      ? toolbar.nextElementSibling : null;
    if (editor) rememberSelection(editor);
  }, true);

  document.addEventListener('keydown', function (event) {
    const editor = editorForNode(event.target);
    if (!editor) return;

    if (event.key === 'Tab') {
      event.preventDefault();
      event.stopImmediatePropagation();
      rememberSelection(editor);
      focusEditorPreservingSelection(editor);
      document.execCommand(event.shiftKey ? 'outdent' : 'indent', false, null);
      rememberSelection(editor);
      return;
    }

    if (event.key === 'Enter') {
      // Keep Enter inside the contenteditable instead of allowing outer-page handlers
      // to hijack it after pasted/foreign markup.
      event.stopPropagation();
    }
  }, true);

  function sanitizePastedHtml(html) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');
    const allowed = new Set(['A','B','STRONG','I','EM','U','S','SPAN','P','DIV','BR','H1','H2','H3','H4','H5','H6','BLOCKQUOTE','PRE','OL','UL','LI','FONT']);
    const styleProps = ['font-family','font-size','color','background-color','font-weight','font-style','text-decoration','text-align','vertical-align'];

    function clean(node) {
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      Array.from(node.children).forEach(clean);
      if (!allowed.has(node.tagName)) {
        const parent = node.parentNode;
        while (node.firstChild) parent.insertBefore(node.firstChild, node);
        parent.removeChild(node);
        return;
      }
      Array.from(node.attributes).forEach(attr => {
        if (attr.name.toLowerCase() !== 'style' && !(node.tagName === 'A' && attr.name.toLowerCase() === 'href')) {
          node.removeAttribute(attr.name);
        }
      });
      if (node.hasAttribute('style')) {
        const source = node.style;
        const keep = {};
        styleProps.forEach(prop => { if (source.getPropertyValue(prop)) keep[prop] = source.getPropertyValue(prop); });
        node.removeAttribute('style');
        Object.entries(keep).forEach(([prop, value]) => node.style.setProperty(prop, value));
      }
      if (node.tagName === 'A') {
        const href = node.getAttribute('href');
        if (!href || !/^(https?:|mailto:|#)/i.test(href)) node.removeAttribute('href');
        else node.setAttribute('target', '_blank');
      }
    }

    clean(doc.body);
    return doc.body.innerHTML;
  }

  document.addEventListener('paste', function (event) {
    const editor = editorForNode(event.target);
    if (!editor) return;
    event.preventDefault();
    event.stopPropagation();
    rememberSelection(editor);
    focusEditorPreservingSelection(editor);

    const clipboard = event.clipboardData;
    const html = clipboard && clipboard.getData('text/html');
    const text = clipboard && clipboard.getData('text/plain');
    let insert = html ? sanitizePastedHtml(html) : '';
    if (!insert && text) {
      insert = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
    }
    if (!insert) return;
    document.execCommand('insertHTML', false, insert);
    rememberSelection(editor);
  }, true);

  const style = document.createElement('style');
  style.textContent = `
    html, body { min-height: 100%; }
    body { overflow-y: scroll; overscroll-behavior: none; }
    .shell, #dashboard { width: 100%; }
    .tabs { position: relative; }
    .editor { overflow-y: auto; overflow-x: hidden; }
    .editor:focus { outline: 2px solid rgba(92,64,51,.18); outline-offset: -2px; }
    .toolbar { flex: 0 0 auto; min-height: 42px; align-items: center; }
    .toolbar select, .toolbar button, .toolbar input[type=color] { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
    .toolbar input[type=color] { width: 34px !important; height: 30px; padding: 2px; cursor: pointer; }
    .editor h1 { font-size: 2em; margin: .55em 0 .3em; }
    .editor h2 { font-size: 1.5em; margin: .5em 0 .25em; }
    .editor h3 { font-size: 1.25em; margin: .45em 0 .2em; }
    .editor p { margin: .55em 0; }
    .editor ol[data-marker-size], .editor ol[data-marker-color] { padding-left: 2.2em; }
    .editor ol[data-marker-size]::marker { font-size: var(--marker-size, inherit); }
    .editor ol[data-marker-color]::marker { color: var(--marker-color, inherit); }
    .editor ol { --marker-size: inherit; --marker-color: inherit; }
    .published-filter-bar { display:flex; flex-wrap:wrap; gap:8px; margin:0 0 14px; padding:10px; background:#EFE7D8; border:1px solid var(--line); border-radius:7px; }
    .published-filter-bar button.active { background:var(--brown); color:#fff; }
    .published-filter-count { opacity:.75; font-size:.85em; }
    .editor ul, .editor ol { margin-top:.55em; margin-bottom:.55em; }
  `;
  document.head.appendChild(style);

  function execIn(editor, command, value) {
    if (!editor) return;
    rememberSelection(editor);
    if (!focusEditorPreservingSelection(editor)) return;
    document.execCommand('styleWithCSS', false, true);
    document.execCommand(command, false, value == null ? null : value);
    rememberSelection(editor);
  }

  function applyExactFontSize(editor, pt) {
    if (!editor || !focusEditorPreservingSelection(editor)) return;
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !selectionInside(editor)) return;
    const range = sel.getRangeAt(0);
    if (range.collapsed) {
      const span = document.createElement('span');
      span.style.fontSize = `${pt}pt`;
      span.appendChild(document.createTextNode('\u200b'));
      range.insertNode(span);
      const caret = document.createRange();
      caret.setStart(span.firstChild, 1);
      caret.collapse(true);
      sel.removeAllRanges();
      sel.addRange(caret);
    } else {
      const fragment = range.extractContents();
      const span = document.createElement('span');
      span.style.fontSize = `${pt}pt`;
      span.appendChild(fragment);
      range.insertNode(span);
      const selected = document.createRange();
      selected.selectNodeContents(span);
      sel.removeAllRanges();
      sel.addRange(selected);
    }
    rememberSelection(editor);
  }

  function addOption(select, value, label) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }

  function nearestOrderedList(editor) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !selectionInside(editor)) return null;
    let node = sel.anchorNode;
    if (node && node.nodeType === Node.TEXT_NODE) node = node.parentElement;
    return node && node.closest ? node.closest('ol') : null;
  }

  function setMarkerSize(editor, value) {
    const list = nearestOrderedList(editor);
    if (!list) return;
    if (value === 'match') {
      list.style.removeProperty('--marker-size');
      list.removeAttribute('data-marker-size');
    } else {
      list.style.setProperty('--marker-size', `${value}pt`);
      list.setAttribute('data-marker-size', value);
    }
  }

  function setMarkerColor(editor, value) {
    const list = nearestOrderedList(editor);
    if (!list) return;
    list.style.setProperty('--marker-color', value);
    list.setAttribute('data-marker-color', value);
  }

  function installToolbar(toolbar) {
    if (!toolbar || toolbar.dataset.enhanced === '1') return;
    toolbar.dataset.enhanced = '1';
    const editor = toolbar.nextElementSibling && toolbar.nextElementSibling.matches(EDITOR_SELECTOR) ? toolbar.nextElementSibling : null;
    if (!editor) return;

    const selects = toolbar.querySelectorAll('select');
    const fontSelect = selects[0];
    const sizeSelect = selects[1];

    if (sizeSelect) {
      sizeSelect.innerHTML = '';
      addOption(sizeSelect, '', 'Size');
      [8,9,10,11,12,14,16,18,20,22,24,26,28,32,36,40,44,48,54,60,64].forEach(pt => addOption(sizeSelect, String(pt), `${pt}pt`));
      sizeSelect.value = '';
      sizeSelect.onmousedown = function () { rememberSelection(editor); };
      sizeSelect.onchange = function () { if (this.value) applyExactFontSize(editor, Number(this.value)); this.value = ''; };
      sizeSelect.title = 'Font size (8–64 pt)';
    }

    if (fontSelect) {
      fontSelect.onmousedown = function () { rememberSelection(editor); };
      fontSelect.onchange = function () { if (this.value) execIn(editor, 'fontName', this.value); this.selectedIndex = 0; };
    }

    const firstDivider = toolbar.querySelector('.divider');
    const color = document.createElement('input');
    color.type = 'color'; color.value = '#24333B'; color.title = 'Font color'; color.setAttribute('aria-label', 'Font color');
    color.addEventListener('mousedown', function () { rememberSelection(editor); });
    color.addEventListener('change', function () { execIn(editor, 'foreColor', this.value); });
    if (firstDivider) toolbar.insertBefore(color, firstDivider); else toolbar.appendChild(color);

    const format = document.createElement('select');
    format.title = 'Paragraph / heading style'; format.setAttribute('aria-label', 'Paragraph / heading style');
    [['P','Paragraph'],['H1','Heading 1'],['H2','Heading 2'],['H3','Heading 3'],['H4','Heading 4'],['BLOCKQUOTE','Quote'],['PRE','Preformatted']].forEach(([v,l]) => addOption(format, v, l));
    format.onmousedown = function () { rememberSelection(editor); };
    format.addEventListener('change', function () { if (this.value) execIn(editor, 'formatBlock', this.value); this.value = 'P'; });
    if (fontSelect) toolbar.insertBefore(format, fontSelect); else toolbar.prepend(format);

    const markerSize = document.createElement('select');
    markerSize.title = 'Number size for the selected numbered list';
    markerSize.setAttribute('aria-label', 'Number size');
    addOption(markerSize, 'match', 'Number = Text');
    [12,14,16,18,20,24,28,32,36,40,48,54,60,64].forEach(pt => addOption(markerSize, String(pt), `Number ${pt}pt`));
    markerSize.addEventListener('mousedown', function () { rememberSelection(editor); });
    markerSize.addEventListener('change', function () { setMarkerSize(editor, this.value); this.value = 'match'; });
    toolbar.appendChild(markerSize);

    const markerColor = document.createElement('input');
    markerColor.type = 'color'; markerColor.value = '#24333B'; markerColor.title = 'Number color for the selected numbered list'; markerColor.setAttribute('aria-label', 'Number color');
    markerColor.addEventListener('mousedown', function () { rememberSelection(editor); });
    markerColor.addEventListener('change', function () { setMarkerColor(editor, this.value); });
    toolbar.appendChild(markerColor);

    toolbar.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('mousedown', function (e) { rememberSelection(editor); e.preventDefault(); });
    });
  }

  function enhanceToolbars() { document.querySelectorAll('.toolbar').forEach(installToolbar); }

  function organizePublishedPosts() {
    const list = document.getElementById('publishedList');
    const section = document.getElementById('published');
    if (!list || !section) return;
    const cards = Array.from(list.children).filter(el => el.classList.contains('card'));
    if (!cards.length) return;
    const labels = ['Book Curations','Book Reviews','Curiosity Cabinet','K. W. Snyder Writing — Essays','K. W. Snyder Writing — Short Stories','K. W. Snyder Writing — Poems','K. W. Snyder Writing — Vignettes'];
    cards.forEach(card => { const text = card.querySelector('small')?.textContent || ''; card.dataset.category = labels.find(label => text.includes(label)) || 'Other'; });
    let bar = section.querySelector('.published-filter-bar');
    if (!bar) { bar = document.createElement('div'); bar.className = 'published-filter-bar'; list.parentNode.insertBefore(bar, list); }
    bar.innerHTML = '';
    const counts = {}; cards.forEach(card => { counts[card.dataset.category] = (counts[card.dataset.category] || 0) + 1; });
    const categories = ['All Posts', ...labels];
    const show = category => { cards.forEach(card => { card.style.display = category === 'All Posts' || card.dataset.category === category ? '' : 'none'; }); bar.querySelectorAll('button').forEach(button => button.classList.toggle('active', button.dataset.category === category)); };
    categories.forEach(category => { const button = document.createElement('button'); button.type = 'button'; button.dataset.category = category; button.textContent = category; const badge = document.createElement('span'); badge.className = 'published-filter-count'; badge.textContent = ` (${category === 'All Posts' ? cards.length : (counts[category] || 0)})`; button.appendChild(badge); button.addEventListener('click', () => show(category)); bar.appendChild(button); });
    show('All Posts');
  }

  function wrapPublishedLoader() {
    if (typeof window.loadPublished !== 'function' || window.loadPublished.__organized) return;
    const original = window.loadPublished;
    async function wrapped() { const result = await original.apply(this, arguments); organizePublishedPosts(); enhanceToolbars(); return result; }
    wrapped.__organized = true;
    window.loadPublished = wrapped;
  }

  window.resetManuscriptEditor = resetChapterEditor;
  window.applyExactFontSize = applyExactFontSize;

  document.addEventListener('DOMContentLoaded', function () { enhanceToolbars(); wrapPublishedLoader(); setTimeout(function () { enhanceToolbars(); organizePublishedPosts(); }, 250); });

  window.addEventListener('load', function () {
    if (typeof window.saveChapter !== 'function' || window.saveChapter.__resetWrapped) return;
    const originalSaveChapter = window.saveChapter;
    const wrappedSave = async function () { const result = await originalSaveChapter.apply(this, arguments); resetChapterEditor(); return result; };
    wrappedSave.__resetWrapped = true;
    window.saveChapter = wrappedSave;
  });
})();

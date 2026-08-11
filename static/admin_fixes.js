(function () {
  'use strict';

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

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Tab') return;
    const editor = event.target && event.target.closest
      ? event.target.closest('[contenteditable="true"]')
      : null;
    if (!editor) return;
    event.preventDefault();
    event.stopPropagation();
    editor.focus();
    document.execCommand(event.shiftKey ? 'outdent' : 'indent', false, null);
  }, true);

  document.addEventListener('mousedown', function (event) {
    const control = event.target.closest && event.target.closest('.toolbar button, .toolbar select, .toolbar input');
    if (control && control.tagName === 'BUTTON') event.preventDefault();
  }, true);

  const style = document.createElement('style');
  style.textContent = `
    html, body { min-height: 100%; }
    body { overflow-y: scroll; overscroll-behavior: none; }
    .shell, #dashboard { width: 100%; }
    .tabs { position: relative; }
    .editor { overflow-y: auto; overflow-x: hidden; }
    .toolbar { flex: 0 0 auto; min-height: 42px; align-items: center; }
    .toolbar select, .toolbar button, .toolbar input[type=color] { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
    .toolbar input[type=color] { width: 34px !important; height: 30px; padding: 2px; cursor: pointer; }
    .editor h1 { font-size: 2em; margin: .55em 0 .3em; }
    .editor h2 { font-size: 1.5em; margin: .5em 0 .25em; }
    .editor h3 { font-size: 1.25em; margin: .45em 0 .2em; }
    .editor p { margin: .55em 0; }
    .published-filter-bar { display:flex; flex-wrap:wrap; gap:8px; margin:0 0 14px; padding:10px; background:#EFE7D8; border:1px solid var(--line); border-radius:7px; }
    .published-filter-bar button.active { background:var(--brown); color:#fff; }
    .published-filter-count { opacity:.75; font-size:.85em; }
  `;
  document.head.appendChild(style);

  function editableEditors() {
    return Array.from(document.querySelectorAll('.editor[contenteditable="true"]'));
  }

  function selectionIn(editor) {
    const sel = window.getSelection();
    return !!(sel && sel.rangeCount && editor.contains(sel.anchorNode));
  }

  function focusEditor(editor) {
    if (!editor) return;
    editor.focus();
  }

  function execIn(editor, command, value) {
    focusEditor(editor);
    document.execCommand('styleWithCSS', false, true);
    document.execCommand(command, false, value == null ? null : value);
  }

  function applyExactFontSize(editor, pt) {
    if (!editor) return;
    focusEditor(editor);
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !selectionIn(editor)) return;
    const range = sel.getRangeAt(0);
    if (range.collapsed) {
      const span = document.createElement('span');
      span.style.fontSize = `${pt}pt`;
      span.appendChild(document.createTextNode('\u200b'));
      range.insertNode(span);
      const newRange = document.createRange();
      newRange.setStart(span.firstChild, 1);
      newRange.collapse(true);
      sel.removeAllRanges();
      sel.addRange(newRange);
      return;
    }
    const span = document.createElement('span');
    span.style.fontSize = `${pt}pt`;
    try {
      range.surroundContents(span);
    } catch (_) {
      const fragment = range.extractContents();
      span.appendChild(fragment);
      range.insertNode(span);
    }
    sel.removeAllRanges();
    const newRange = document.createRange();
    newRange.selectNodeContents(span);
    sel.addRange(newRange);
  }

  function addOption(select, value, label) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }

  function installToolbar(toolbar) {
    if (!toolbar || toolbar.dataset.enhanced === '1') return;
    toolbar.dataset.enhanced = '1';
    const editor = toolbar.nextElementSibling && toolbar.nextElementSibling.matches('.editor')
      ? toolbar.nextElementSibling : null;
    if (!editor) return;

    const selects = toolbar.querySelectorAll('select');
    const fontSelect = selects[0];
    const sizeSelect = selects[1];

    if (sizeSelect) {
      sizeSelect.innerHTML = '';
      addOption(sizeSelect, '', 'Size');
      for (let pt = 8; pt <= 64; pt += 2) addOption(sizeSelect, String(pt), `${pt}pt`);
      sizeSelect.value = '';
      sizeSelect.onchange = function () {
        if (this.value) applyExactFontSize(editor, Number(this.value));
        this.value = '';
      };
      sizeSelect.title = 'Font size (8–64 pt)';
    }

    if (fontSelect) {
      fontSelect.onchange = function () {
        if (this.value) execIn(editor, 'fontName', this.value);
        this.selectedIndex = 0;
      };
    }

    const firstDivider = toolbar.querySelector('.divider');
    const color = document.createElement('input');
    color.type = 'color';
    color.value = '#24333B';
    color.title = 'Font color';
    color.setAttribute('aria-label', 'Font color');
    color.addEventListener('change', function () { execIn(editor, 'foreColor', this.value); });
    if (firstDivider) toolbar.insertBefore(color, firstDivider);
    else toolbar.appendChild(color);

    const format = document.createElement('select');
    format.title = 'Paragraph / heading style';
    format.setAttribute('aria-label', 'Paragraph / heading style');
    [['P','Paragraph'],['H1','Heading 1'],['H2','Heading 2'],['H3','Heading 3'],['H4','Heading 4'],['BLOCKQUOTE','Quote'],['PRE','Preformatted']].forEach(([v,l]) => addOption(format, v, l));
    format.addEventListener('change', function () {
      if (this.value) execIn(editor, 'formatBlock', this.value);
      this.value = 'P';
    });
    if (fontSelect) toolbar.insertBefore(format, fontSelect);
    else toolbar.prepend(format);

    // Keep list buttons from accidentally changing focus before the selection is used.
    toolbar.querySelectorAll('button').forEach(btn => {
      btn.addEventListener('mousedown', function (e) { e.preventDefault(); });
    });
  }

  function enhanceToolbars() {
    document.querySelectorAll('.toolbar').forEach(installToolbar);
  }

  function publishedCategoryLabel(category) {
    return {
      curations: 'Book Curations',
      reviews: 'Book Reviews',
      curiosity: 'Curiosity Cabinet',
      kw_short_stories: 'K. W. Snyder Writing — Short Stories',
      kw_poems: 'K. W. Snyder Writing — Poems',
      kw_vignettes: 'K. W. Snyder Writing — Vignettes',
      kwsnyderwriting: 'K. W. Snyder Writing — Essays'
    }[category] || 'Other';
  }

  function organizePublishedPosts() {
    const list = document.getElementById('publishedList');
    const section = document.getElementById('published');
    if (!list || !section) return;
    const cards = Array.from(list.children).filter(el => el.classList.contains('card'));
    if (!cards.length) return;

    cards.forEach(card => {
      const small = card.querySelector('small');
      const text = small ? small.textContent : '';
      let category = 'Other';
      Object.values({
        curations: 'Book Curations', reviews: 'Book Reviews', curiosity: 'Curiosity Cabinet',
        kw_short_stories: 'K. W. Snyder Writing — Short Stories', kw_poems: 'K. W. Snyder Writing — Poems',
        kw_vignettes: 'K. W. Snyder Writing — Vignettes', kwsnyderwriting: 'K. W. Snyder Writing — Essays'
      }).forEach(label => { if (text.includes(label)) category = label; });
      card.dataset.category = category;
    });

    let bar = section.querySelector('.published-filter-bar');
    if (!bar) {
      bar = document.createElement('div');
      bar.className = 'published-filter-bar';
      list.parentNode.insertBefore(bar, list);
    }
    bar.innerHTML = '';
    const counts = {};
    cards.forEach(c => { counts[c.dataset.category] = (counts[c.dataset.category] || 0) + 1; });
    const categories = ['All Posts','Book Curations','Book Reviews','Curiosity Cabinet','K. W. Snyder Writing — Essays','K. W. Snyder Writing — Short Stories','K. W. Snyder Writing — Poems','K. W. Snyder Writing — Vignettes'];
    const show = category => {
      cards.forEach(card => { card.style.display = (category === 'All Posts' || card.dataset.category === category) ? '' : 'none'; });
      bar.querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.category === category));
    };
    categories.forEach(category => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.category = category;
      button.textContent = category;
      const count = category === 'All Posts' ? cards.length : (counts[category] || 0);
      const badge = document.createElement('span');
      badge.className = 'published-filter-count';
      badge.textContent = ` (${count})`;
      button.appendChild(badge);
      button.addEventListener('click', () => show(category));
      bar.appendChild(button);
    });
    show('All Posts');
  }

  function wrapPublishedLoader() {
    if (typeof window.loadPublished !== 'function' || window.loadPublished.__organized) return;
    const original = window.loadPublished;
    async function wrapped() {
      const result = await original.apply(this, arguments);
      organizePublishedPosts();
      enhanceToolbars();
      return result;
    }
    wrapped.__organized = true;
    window.loadPublished = wrapped;
  }

  window.resetManuscriptEditor = resetChapterEditor;
  window.applyExactFontSize = applyExactFontSize;

  document.addEventListener('DOMContentLoaded', function () {
    enhanceToolbars();
    wrapPublishedLoader();
    setTimeout(function () { enhanceToolbars(); organizePublishedPosts(); }, 250);
  });

  window.addEventListener('load', function () {
    if (typeof window.saveChapter !== 'function') return;
    if (window.saveChapter.__resetWrapped) return;
    const originalSaveChapter = window.saveChapter;
    const wrappedSave = async function () {
      const result = await originalSaveChapter.apply(this, arguments);
      resetChapterEditor();
      return result;
    };
    wrappedSave.__resetWrapped = true;
    window.saveChapter = wrappedSave;
  });
})();

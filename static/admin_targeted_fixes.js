(function () {
  'use strict';

  function currentEditorTarget(target) {
    return target && target.closest ? target.closest('#postEditor, #chapterEditor') : null;
  }

  function paragraphBlock(editor) {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount || !editor.contains(selection.anchorNode)) return null;
    let node = selection.anchorNode;
    if (node && node.nodeType === Node.TEXT_NODE) node = node.parentElement;
    return node && node.closest ? (node.closest('p, h1, h2, h3, h4, h5, h6, blockquote, li, div') || editor) : editor;
  }

  function indentParagraph(editor, outdent) {
    editor.focus({ preventScroll: true });
    let block = paragraphBlock(editor);
    if (!block || block === editor) {
      document.execCommand('formatBlock', false, 'p');
      block = paragraphBlock(editor);
    }
    if (!block || block === editor) return;
    const current = parseFloat(block.style.textIndent) || 0;
    const next = Math.max(0, current + (outdent ? -2 : 2));
    if (next === 0) block.style.removeProperty('text-indent');
    else block.style.textIndent = next + 'em';
  }

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Tab') return;
    const editor = currentEditorTarget(event.target);
    if (!editor) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    indentParagraph(editor, event.shiftKey);
  }, true);

  function setPostEditorCategoryMode() {
    const category = document.getElementById('postCategory');
    const wrapper = document.getElementById('postKWSubcategoryWrap');
    const sub = document.getElementById('postKWSubcategory');
    if (!category || !wrapper || !sub) return;

    const oldValue = category.value;
    const oldKW = ['kw_short_stories', 'kw_poems', 'kw_vignettes'].includes(oldValue) ? oldValue : (oldValue === 'kwsnyderwriting' ? 'kwsnyderwriting' : null);

    category.innerHTML = '';
    [['curations','Book Curations'],['reviews','Book Reviews'],['curiosity','Curiosity Cabinet'],['kwsnyderwriting','K. W. Snyder Writing']].forEach(([value,label]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      category.appendChild(option);
    });

    category.value = oldKW ? 'kwsnyderwriting' : (oldValue || 'curations');
    if (oldKW && oldKW !== 'kwsnyderwriting') sub.value = oldKW;

    function sync() {
      const isKW = category.value === 'kwsnyderwriting';
      wrapper.classList.toggle('hidden', !isKW);
      const access = document.getElementById('postAccess');
      if (access) {
        access.value = isKW ? 'members' : 'public';
        access.disabled = isKW;
      }
    }

    category.addEventListener('change', sync);
    sub.addEventListener('change', sync);
    sync();
  }

  function removeDuplicateSizeSelectors() {
    document.querySelectorAll('.toolbar').forEach(toolbar => {
      const sizes = Array.from(toolbar.querySelectorAll('select')).filter(select => {
        const first = select.options && select.options[0];
        return first && String(first.textContent || '').trim().toLowerCase() === 'size';
      });
      sizes.slice(1).forEach(select => select.remove());
    });
  }

  function addPublishedFilters() {
    const section = document.getElementById('published');
    const list = document.getElementById('publishedList');
    if (!section || !list || document.getElementById('publishedFilters')) return;

    const wrap = document.createElement('div');
    wrap.id = 'publishedFilters';
    wrap.className = 'actions';
    wrap.style.marginBottom = '8px';

    const title = document.createElement('strong');
    title.textContent = 'Show:';
    title.style.color = 'var(--brown)';
    wrap.appendChild(title);

    const filters = [['all','All'],['curations','Book Curations'],['reviews','Book Reviews'],['curiosity','Curiosity Cabinet'],['kwsnyderwriting','K. W. Snyder Writing']];
    let active = 'all';

    function classify(card) {
      const text = String(card.textContent || '').toLowerCase();
      if (text.includes('book curations')) return 'curations';
      if (text.includes('book reviews')) return 'reviews';
      if (text.includes('curiosity cabinet')) return 'curiosity';
      if (text.includes('k. w. snyder writing')) return 'kwsnyderwriting';
      return 'other';
    }

    function apply() {
      Array.from(list.children).forEach(card => {
        if (!card.classList || !card.classList.contains('card')) return;
        card.classList.toggle('hidden', active !== 'all' && classify(card) !== active);
      });
      wrap.querySelectorAll('button[data-filter]').forEach(button => {
        button.className = button.dataset.filter === active ? '' : 'light';
      });
    }

    filters.forEach(([value,label]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.filter = value;
      button.textContent = label;
      button.className = value === active ? '' : 'light';
      button.addEventListener('click', () => { active = value; apply(); });
      wrap.appendChild(button);
    });

    const note = section.querySelector('.note');
    if (note) note.insertAdjacentElement('afterend', wrap);
    else section.insertBefore(wrap, list);

    const observer = new MutationObserver(apply);
    observer.observe(list, { childList: true });
    apply();
  }

  function start() {
    setPostEditorCategoryMode();
    removeDuplicateSizeSelectors();
    addPublishedFilters();
    setTimeout(removeDuplicateSizeSelectors, 50);
    setTimeout(removeDuplicateSizeSelectors, 250);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();

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
    const control = event.target.closest && event.target.closest('.toolbar button, .toolbar select');
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
    .toolbar select, .toolbar button { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
  `;
  document.head.appendChild(style);

  window.resetManuscriptEditor = resetChapterEditor;

  // Ensure a successful chapter save starts a genuinely fresh chapter form.
  window.addEventListener('load', function () {
    if (typeof window.saveChapter !== 'function') return;
    const originalSaveChapter = window.saveChapter;
    window.saveChapter = async function () {
      const result = await originalSaveChapter.apply(this, arguments);
      resetChapterEditor();
      return result;
    };
  });
})();

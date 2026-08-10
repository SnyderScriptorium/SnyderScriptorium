(function () {
  'use strict';

  function editorFor(id) {
    return document.getElementById(id);
  }

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

  // Keep Tab inside the rich-text editor. Shift+Tab outdents.
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Tab') return;
    const editor = event.target && event.target.closest
      ? event.target.closest('[contenteditable="true"]')
      : null;
    if (!editor) return;
    event.preventDefault();
    event.stopPropagation();
    editor.focus();
    try {
      document.execCommand(event.shiftKey ? 'outdent' : 'indent', false, null);
    } catch (_) {
      document.execCommand('insertHTML', false, '&nbsp;&nbsp;&nbsp;&nbsp;');
    }
  }, true);

  // Prevent toolbar controls from stealing the editor selection before formatting.
  document.addEventListener('mousedown', function (event) {
    const control = event.target.closest && event.target.closest('.toolbar button, .toolbar select');
    if (!control) return;
    if (control.tagName === 'BUTTON') event.preventDefault();
  }, true);

  // Make the dashboard stable while its internal editors/lists scroll.
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

  // Expose a safe reset helper for the existing saveChapter() flow.
  window.resetManuscriptEditor = resetChapterEditor;
})();

/* Snyder Scriptorium — blog editor photo insert + drag-to-resize.
 * - insertBlogPhoto(): toolbar button → phone file picker → upload → insert at cursor.
 * - Tap any image in #postEditor to get corner resize dots (touch + mouse).
 * - Width is stored as inline style so it survives save/publish via innerHTML.
 */
(function () {
  'use strict';

  var EDITOR_ID = 'postEditor';
  var UPLOAD_URL = '/api/blog/upload-image';

  function $(id) { return document.getElementById(id); }
  function editor() { return $(EDITOR_ID); }

  /* ---------- photo insert ---------- */

  var fileInput = null;
  function getFileInput() {
    if (fileInput) return fileInput;
    fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/*';
    // Let the phone offer camera or gallery.
    fileInput.style.display = 'none';
    document.body.appendChild(fileInput);
    fileInput.addEventListener('change', onFileChosen);
    return fileInput;
  }

  window.insertBlogPhoto = function () {
    getFileInput().click();
  };

  function onFileChosen() {
    var files = fileInput.files;
    if (!files || !files.length) return;
    var file = files[0];
    // Reset so the same file can be picked twice in a row.
    fileInput.value = '';
    uploadAndInsert(file);
  }

  function status(msg, isError) {
    if (typeof window.showStatus === 'function') window.showStatus(msg, !!isError);
  }

  function uploadAndInsert(file) {
    var ed = editor();
    if (!ed) { status('Editor not found.', true); return; }
    status('Uploading photo…');
    var form = new FormData();
    form.append('photo', file, file.name || 'photo.jpg');
    fetch(UPLOAD_URL, { method: 'POST', body: form, credentials: 'same-origin' })
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) throw new Error(data.error || 'Upload failed.');
          return data;
        });
      })
      .then(function (data) {
        insertImageAtCursor(ed, data.url);
        status('Photo inserted — tap it to resize.');
      })
      .catch(function (err) {
        status('Photo upload failed: ' + (err.message || err), true);
      });
  }

  function insertImageAtCursor(ed, url) {
    ed.focus();
    if (typeof window.restoreSel === 'function') { try { window.restoreSel(); } catch (e) {} }
    var img = document.createElement('img');
    img.src = url;
    img.alt = '';
    img.setAttribute('draggable', 'false');
    img.style.cssText = 'max-width:100%;height:auto;display:block;margin:8px auto;';
    var sel = window.getSelection();
    if (sel && sel.rangeCount) {
      var range = sel.getRangeAt(0);
      // Only insert inside the editor.
      if (ed.contains(range.commonAncestorContainer)) {
        range.deleteContents();
        range.insertNode(img);
        // Put the cursor after the image.
        range.setStartAfter(img);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
        if (typeof window.saveSel === 'function') { try { window.saveSel(); } catch (e) {} }
        return;
      }
    }
    // Fallback: append at the end.
    ed.appendChild(img);
  }

  /* ---------- drag-to-resize ---------- */

  var overlay = null;
  var activeImg = null;
  var handles = [];

  function getOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.id = 'blogImgResizeOverlay';
    overlay.style.cssText = [
      'position:fixed', 'z-index:9999', 'pointer-events:none',
      'display:none', 'margin:0', 'padding:0'
    ].join(';');
    // Selection outline.
    var frame = document.createElement('div');
    frame.id = 'blogImgResizeFrame';
    frame.style.cssText = [
      'position:absolute', 'inset:0', 'pointer-events:none',
      'border:2px solid #A67B5B', 'border-radius:2px', 'box-sizing:border-box'
    ].join(';');
    overlay.appendChild(frame);
    // Four corner handles.
    var corners = ['nw', 'ne', 'sw', 'se'];
    corners.forEach(function (corner) {
      var h = document.createElement('div');
      h.dataset.corner = corner;
      h.style.cssText = [
        'position:absolute', 'width:26px', 'height:26px',
        'background:#A67B5B', 'border:2px solid #FFFDF8', 'border-radius:50%',
        'pointer-events:auto', 'cursor:nwse-resize', 'box-sizing:border-box',
        'box-shadow:0 1px 4px rgba(0,0,0,.35)', 'touch-action:none'
      ].join(';');
      // Offset so the dot centers on the corner.
      if (corner.indexOf('n') === 0) h.style.top = '-13px'; else h.style.bottom = '-13px';
      if (corner.indexOf('w') === 1) h.style.left = '-13px'; else h.style.right = '-13px';
      if (corner === 'ne' || corner === 'sw') h.style.cursor = 'nesw-resize';
      h.addEventListener('pointerdown', onHandleDown);
      overlay.appendChild(h);
      handles.push(h);
    });
    document.body.appendChild(overlay);
    return overlay;
  }

  function showOverlay(img) {
    activeImg = img;
    var ov = getOverlay();
    positionOverlay();
    ov.style.display = 'block';
  }

  function hideOverlay() {
    activeImg = null;
    if (overlay) overlay.style.display = 'none';
  }

  function positionOverlay() {
    if (!activeImg || !overlay) return;
    // If the image left the document, dismiss.
    if (!document.contains(activeImg)) { hideOverlay(); return; }
    var r = activeImg.getBoundingClientRect();
    overlay.style.left = r.left + 'px';
    overlay.style.top = r.top + 'px';
    overlay.style.width = r.width + 'px';
    overlay.style.height = r.height + 'px';
  }

  // Tap an image in the editor to select it; tap elsewhere to dismiss.
  function onEditorPointerDown(e) {
    var ed = editor();
    if (!ed) return;
    var target = e.target;
    if (target && target.tagName === 'IMG' && ed.contains(target)) {
      // Let the tap complete, then show handles.
      setTimeout(function () { showOverlay(target); }, 30);
    } else if (activeImg) {
      // Tapped outside the image — dismiss, but not when tapping a handle.
      if (!overlay || !overlay.contains(target)) hideOverlay();
    }
  }

  /* Resize drag state */
  var dragState = null;

  function onHandleDown(e) {
    if (!activeImg) return;
    e.preventDefault();
    e.stopPropagation();
    var corner = e.currentTarget.dataset.corner;
    var startX = e.clientX, startY = e.clientY;
    var rect = activeImg.getBoundingClientRect();
    var aspect = rect.height / Math.max(1, rect.width);
    dragState = { corner: corner, startX: startX, startY: startY,
                  startW: rect.width, aspect: aspect };
    var move = function (ev) { onHandleMove(ev); };
    var up = function () {
      dragState = null;
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up);
      document.removeEventListener('pointercancel', up);
      positionOverlay();
    };
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
    document.addEventListener('pointercancel', up);
  }

  function onHandleMove(e) {
    if (!dragState || !activeImg) return;
    var dx = e.clientX - dragState.startX;
    var dy = e.clientY - dragState.startY;
    var corner = dragState.corner;
    // Horizontal-dominant resize; vertical follows aspect ratio.
    var delta = dx;
    // East corners grow with +dx, west corners grow with -dx.
    if (corner.charAt(1) === 'w') delta = -dx;
    // Blend in vertical for a natural diagonal feel.
    var vDelta = dy;
    if (corner.charAt(0) === 'n') vDelta = -dy;
    delta = (delta + vDelta * dragState.aspect) / 2;
    var newW = Math.max(60, dragState.startW + delta);
    // Don't exceed the editor width.
    var ed = editor();
    if (ed) {
      var maxW = ed.getBoundingClientRect().width - 16;
      newW = Math.min(newW, maxW);
    }
    activeImg.style.width = Math.round(newW) + 'px';
    activeImg.style.maxWidth = '100%';
    activeImg.style.height = 'auto';
    positionOverlay();
  }

  function wireEditor() {
    var ed = editor();
    if (!ed || ed.dataset.blogImgWired === '1') return;
    ed.dataset.blogImgWired = '1';
    // Prevent native image dragging from fighting the handles.
    ed.addEventListener('dragstart', function (e) {
      if (e.target && e.target.tagName === 'IMG') e.preventDefault();
    });
    ed.addEventListener('pointerdown', onEditorPointerDown);
    // Keep the overlay tracking on scroll / resize / typing.
    window.addEventListener('scroll', function () { if (activeImg) positionOverlay(); }, true);
    window.addEventListener('resize', function () { if (activeImg) positionOverlay(); });
  }

  // Images inserted before this script loaded still get handles on tap.
  function init() {
    wireEditor();
    // Re-wire after tab switches re-render (admin SPA-ish tabs).
    setTimeout(wireEditor, 800);
    setTimeout(wireEditor, 2500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

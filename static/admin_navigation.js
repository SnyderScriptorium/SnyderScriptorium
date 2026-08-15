/* Canonical admin dashboard navigation.
   This is intentionally independent of the editor, analytics, and authentication code.
   It is the only click handler allowed to own the dashboard's section tabs. */
(function () {
  'use strict';

  const TAB_NAMES = ['write', 'drafts', 'published', 'manuscripts', 'about', 'kwpreview', 'stats', 'inbox'];

  function showTab(name) {
    if (!TAB_NAMES.includes(name)) return;

    TAB_NAMES.forEach(function (tabName) {
      const section = document.getElementById(tabName);
      if (section) section.classList.toggle('hidden', tabName !== name);

      const button = document.getElementById('tab-' + tabName);
      if (button) button.className = tabName === name ? '' : 'light';
    });

    // Run the section's loader only after the section is visible.
    try {
      if (name === 'drafts' && typeof window.loadDrafts === 'function') window.loadDrafts();
      if (name === 'published' && typeof window.loadPublished === 'function') window.loadPublished();
      if (name === 'manuscripts' && typeof window.loadBooks === 'function') window.loadBooks();
      if (name === 'about' && typeof window.loadAbout === 'function') window.loadAbout();
      if (name === 'kwpreview' && typeof window.loadKWPreview === 'function') window.loadKWPreview();
      if (name === 'stats' && typeof window.loadStats === 'function') window.loadStats(window.analyticsPeriod || '30');
      if (name === 'inbox' && typeof window.loadInbox === 'function') window.loadInbox();
    } catch (error) {
      if (typeof window.showStatus === 'function') window.showStatus('The selected section could not be loaded.', true);
      console.error('Admin section loader failed:', error);
    }
  }

  window.adminShowTab = showTab;
  window.switchTab = showTab;

  function install() {
    const tabs = document.querySelector('.tabs');
    if (!tabs || tabs.dataset.navigationInstalled === '1') return;
    tabs.dataset.navigationInstalled = '1';

    // Capture the click before any stale inline handler can run. This prevents
    // competing tab systems from firing twice or leaving a section stuck.
    tabs.addEventListener('click', function (event) {
      const button = event.target.closest('button[id^="tab-"]');
      if (!button || !tabs.contains(button)) return;
      const name = button.id.slice(4);
      if (!TAB_NAMES.includes(name)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      showTab(name);
    }, true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install, { once: true });
  } else {
    install();
  }
})();

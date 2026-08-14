(function () {
  'use strict';

  const KW_CATEGORIES = new Set(['kwsnyderwriting','kw_short_stories','kw_poems','kw_vignettes','journal']);
  const LABELS = {
    all: 'All',
    curations: 'Book Curations',
    reviews: 'Book Reviews',
    curiosity: 'Curiosity Cabinet',
    kwsnyderwriting: 'K. W. Snyder Writing',
    kw_short_stories: 'K. W. Snyder Writing — Short Stories',
    kw_poems: 'K. W. Snyder Writing — Poems',
    kw_vignettes: 'K. W. Snyder Writing — Vignettes'
  };

  function normalizeCategory(category) {
    const value = String(category || '').trim().toLowerCase();
    return value === 'journal' ? 'kwsnyderwriting' : value;
  }

  function displayCategory(category) {
    const normalized = normalizeCategory(category);
    return LABELS[normalized] || (normalized ? normalized.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : 'Page');
  }

  function updatePublishedCount() {
    const tab = document.getElementById('tab-published');
    if (!tab) return;
    let count = tab.querySelector('.published-count');
    if (!count) {
      tab.appendChild(document.createTextNode(' ('));
      count = document.createElement('span');
      count.className = 'published-count';
      tab.appendChild(count);
      tab.appendChild(document.createTextNode(')'));
    }
    fetch('/api/published', {credentials:'same-origin'})
      .then(r => r.ok ? r.json() : [])
      .then(rows => { count.textContent = Array.isArray(rows) ? rows.length : 0; })
      .catch(() => {});
  }

  function numberPublished() {
    const list = document.getElementById('publishedList');
    if (!list) return;
    Array.from(list.querySelectorAll('.published-card')).forEach((card, index) => {
      const heading = card.querySelector('h3');
      if (!heading) return;
      if (!heading.dataset.numbered) {
        heading.dataset.numbered = '1';
        const number = document.createElement('span');
        number.className = 'published-post-number';
        number.textContent = (index + 1) + '.';
        heading.prepend(number, ' ');
      } else {
        const number = heading.querySelector('.published-post-number');
        if (number) number.textContent = (index + 1) + '.';
      }
    });
    updatePublishedCount();
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

    function cards() {
      return Array.from(list.children).filter(card => card.classList && card.classList.contains('card'));
    }

    function classify(card) {
      const category = normalizeCategory(card.dataset.category || '');
      if (category) return KW_CATEGORIES.has(category) ? 'kwsnyderwriting' : category;
      const text = String(card.textContent || '').toLowerCase();
      if (text.includes('journal') || text.includes('k. w. snyder writing')) return 'kwsnyderwriting';
      if (text.includes('book curations')) return 'curations';
      if (text.includes('book reviews')) return 'reviews';
      if (text.includes('curiosity cabinet')) return 'curiosity';
      return 'other';
    }

    function counts() {
      const result = {all:0,curations:0,reviews:0,curiosity:0,kwsnyderwriting:0};
      cards().forEach(card => {
        const category = classify(card);
        result.all += 1;
        if (Object.prototype.hasOwnProperty.call(result, category)) result[category] += 1;
      });
      return result;
    }

    function apply() {
      const totals = counts();
      Array.from(wrap.querySelectorAll('button[data-filter]')).forEach(button => {
        const key = button.dataset.filter;
        button.textContent = `${LABELS[key] || key} (${totals[key] || 0})`;
        button.className = key === active ? '' : 'light';
      });
      cards().forEach(card => card.classList.toggle('hidden', active !== 'all' && classify(card) !== active));
    }

    filters.forEach(([value]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.filter = value;
      button.addEventListener('click', () => { active = value; apply(); });
      wrap.appendChild(button);
    });

    const note = section.querySelector('.note');
    if (note) note.insertAdjacentElement('afterend', wrap);
    else section.insertBefore(wrap, list);

    const observer = new MutationObserver(() => { numberPublished(); apply(); });
    observer.observe(list, { childList:true, subtree:true });
    apply();
  }

  function ready() {
    const category = document.getElementById('postCategory');
    if (category && !document.getElementById('postCategoryLabel')) {
      const wrap = document.createElement('div');
      wrap.id = 'postCategoryLabelWrap';
      wrap.style.display = 'none';
      wrap.innerHTML = '<label id="postCategoryLabelText">Genre / Topic Label</label><input id="postCategoryLabel" type="text" placeholder="e.g. Fantasy, Biology, Endangered Species">';
      category.closest('.two')?.insertAdjacentElement('afterend', wrap);
      const input = document.getElementById('postCategoryLabel');
      function sync() {
        const show = category.value === 'reviews' || category.value === 'curiosity';
        wrap.style.display = show ? 'block' : 'none';
        const label = document.getElementById('postCategoryLabelText');
        if (label) label.textContent = category.value === 'reviews' ? 'Book Review Genre' : 'Curiosity Cabinet Topic Label';
      }
      category.addEventListener('change', sync);
      sync();
      const originalFetch = window.fetch.bind(window);
      window.fetch = async function (resource, options) {
        options = options || {};
        const url = typeof resource === 'string' ? resource : (resource && resource.url) || '';
        if (/\/api\/published(?:\/\d+)?$/.test(url) && /^(POST|PUT)$/i.test(options.method || '')) {
          try {
            const data = JSON.parse(options.body || '{}');
            if ((data.category === 'reviews' || data.category === 'curiosity') && input) data.categoryName = input.value.trim();
            options.body = JSON.stringify(data);
          } catch (_) {}
        }
        const response = await originalFetch(resource, options);
        if (/\/api\/published(?:\/\d+)?$/.test(url)) setTimeout(() => { updatePublishedCount(); addPublishedFilters(); }, 100);
        return response;
      };
    }

    const style = document.createElement('style');
    style.textContent = '.published-post-number{font-weight:600;color:var(--brown,#5C4033)} .published-count{font-weight:600} #publishedFilters{align-items:center}';
    document.head.appendChild(style);
    const list = document.getElementById('publishedList');
    if (list) new MutationObserver(() => { numberPublished(); addPublishedFilters(); }).observe(list, {childList:true,subtree:true});
    numberPublished();
    addPublishedFilters();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
})();

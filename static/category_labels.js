(function () {
  'use strict';
  function ready() {
    const category = document.getElementById('postCategory');
    if (!category || document.getElementById('postCategoryLabel')) return;

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
          if ((data.category === 'reviews' || data.category === 'curiosity') && input) {
            data.categoryName = input.value.trim();
          }
          options.body = JSON.stringify(data);
        } catch (_) {}
      }
      const response = await originalFetch(resource, options);
      if (/\/api\/published\/\d+$/.test(url) && response.ok) {
        try {
          const copy = response.clone();
          const data = await copy.json();
          if (data.categoryName && input && (category.value === 'reviews' || category.value === 'curiosity')) input.value = data.categoryName;
        } catch (_) {}
      }
      return response;
    };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
  else ready();
})();

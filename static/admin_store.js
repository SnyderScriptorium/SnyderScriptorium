(function(){
  'use strict';
  let editingId=null;
  const esc=v=>{const d=document.createElement('div');d.textContent=v==null?'':String(v);return d.innerHTML;};
  async function api(url,options={}){
    const r=await fetch(url,{credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
    let data={}; try{data=await r.json();}catch(_){}
    if(!r.ok)throw new Error(data.error||`Request failed (${r.status})`);
    return data;
  }
  function mount(){
    const mount=document.getElementById('storeAdminMount'); if(!mount||mount.dataset.ready==='1')return;
    mount.dataset.ready='1';
    mount.innerHTML=`
      <div class="two">
        <div class="preview">
          <h3 class="section-title" id="storeFormHeading">Add a Book to the Store</h3>
          <p class="note">These are finished books for sale. Your Manuscripts Studio books remain separate.</p>
          <label>Title</label><input id="storeTitle" type="text">
          <label>Author</label><input id="storeAuthor" type="text" value="K. W. Snyder">
          <label>Description</label><textarea id="storeDescription" style="min-height:180px"></textarea>
          <div class="two"><div><label>Price (USD)</label><input id="storePrice" type="number" min="0" step="0.01"></div><div><label>Format</label><select id="storeFormat"><option>Paperback</option><option>Hardcover</option><option>eBook</option><option>Other</option></select></div></div>
          <div class="two"><div><label>ISBN</label><input id="storeIsbn" type="text"></div><div><label>Stock Quantity</label><input id="storeStock" type="number" min="0" step="1" value="0"></div></div>
          <label>Cover Image URL</label><input id="storeCover" type="url" placeholder="https://...">
          <label>Category</label><input id="storeCategory" type="text" value="Books">
          <label>Status</label><select id="storeStatus"><option value="draft">Draft</option><option value="active">Active — show on the store</option><option value="archived">Archived</option></select>
          <div class="actions"><button type="button" id="storeSaveButton" onclick="window.saveStoreProduct()">Add Book</button><button type="button" class="light" onclick="window.clearStoreForm()">Clear</button></div>
        </div>
        <div class="preview">
          <h3 class="section-title">Books in the Store</h3>
          <p class="note">Drafts stay hidden from customers. Active books appear on The Scriptorium shelves.</p>
          <div id="storeProductList" class="list"><p class="note">Loading...</p></div>
        </div>
      </div>`;
  }
  function clearForm(){
    editingId=null;
    document.getElementById('storeFormHeading').textContent='Add a Book to the Store';
    document.getElementById('storeSaveButton').textContent='Add Book';
    ['storeTitle','storeDescription','storeIsbn','storeCover'].forEach(id=>document.getElementById(id).value='');
    document.getElementById('storeAuthor').value='K. W. Snyder';
    document.getElementById('storePrice').value='';
    document.getElementById('storeStock').value='0';
    document.getElementById('storeCategory').value='Books';
    document.getElementById('storeFormat').value='Paperback';
    document.getElementById('storeStatus').value='draft';
  }
  function fill(p){
    editingId=p.id;
    document.getElementById('storeFormHeading').textContent='Edit Book';
    document.getElementById('storeSaveButton').textContent='Save Book Changes';
    document.getElementById('storeTitle').value=p.title||'';
    document.getElementById('storeAuthor').value=p.author||'';
    document.getElementById('storeDescription').value=p.description||'';
    document.getElementById('storePrice').value=p.price||'';
    document.getElementById('storeFormat').value=p.format||'Paperback';
    document.getElementById('storeIsbn').value=p.isbn||'';
    document.getElementById('storeStock').value=p.stock_quantity??0;
    document.getElementById('storeCover').value=p.cover_image_url||'';
    document.getElementById('storeCategory').value=p.category||'Books';
    document.getElementById('storeStatus').value=p.status||'draft';
    document.getElementById('storeTitle').focus();
  }
  async function load(){
    mount();
    const list=document.getElementById('storeProductList'); if(!list)return;
    list.innerHTML='<p class="note">Loading books...</p>';
    try{
      const products=await api('/api/store/admin/products');
      list.innerHTML=products.length?'':'<p class="note">No books have been added to the store yet. Add your first finished book on the left.</p>';
      products.forEach(p=>{
        const card=document.createElement('div'); card.className='card';
        const status=p.status||'draft';
        card.innerHTML=`<div style="flex:1"><h3>${esc(p.title)}</h3><small>${esc(p.author||'')} · ${esc(p.format||'')} · $${esc(p.price||'0.00')} · <strong>${esc(status)}</strong></small><p>${esc((p.description||'').slice(0,180))}${(p.description||'').length>180?'…':''}</p><small>ISBN: ${esc(p.isbn||'—')} · Stock: ${esc(p.stock_quantity??0)}</small></div><div class="small-actions"><button type="button" onclick="window.editStoreProduct(${p.id})">Edit</button><button type="button" class="gold" onclick="window.viewStoreProduct('${esc(p.slug)}')">View</button>${status!=='archived'?'<button type="button" class="danger" onclick="window.archiveStoreProduct('+p.id+')">Archive</button>':''}</div>`;
        list.appendChild(card);
      });
    }catch(e){list.innerHTML=`<p class="note">${esc(e.message)}</p>`;}
  }
  async function save(){
    const body={title:document.getElementById('storeTitle').value.trim(),author:document.getElementById('storeAuthor').value.trim(),description:document.getElementById('storeDescription').value.trim(),price:document.getElementById('storePrice').value,format:document.getElementById('storeFormat').value,isbn:document.getElementById('storeIsbn').value.trim(),stock_quantity:document.getElementById('storeStock').value,cover_image_url:document.getElementById('storeCover').value.trim(),category:document.getElementById('storeCategory').value.trim()||'Books',status:document.getElementById('storeStatus').value};
    if(!body.title){return window.showStatus&&window.showStatus('Give the book a title first.',true);}
    try{
      if(editingId) await api(`/api/store/admin/products/${editingId}`,{method:'PUT',body:JSON.stringify(body)});
      else await api('/api/store/admin/products',{method:'POST',body:JSON.stringify(body)});
      clearForm(); await load(); if(window.showStatus)window.showStatus(editingId?'Book updated.':'Book added to The Scriptorium Store.');
    }catch(e){if(window.showStatus)window.showStatus(e.message,true);}
  }
  async function edit(id){try{fill(await api(`/api/store/admin/products/${id}`));}catch(e){window.showStatus&&window.showStatus(e.message,true);}}
  async function archive(id){if(!confirm('Archive this book? It will no longer appear on the public store.'))return;try{await api(`/api/store/admin/products/${id}`,{method:'DELETE'});await load();window.showStatus&&window.showStatus('Book archived.');}catch(e){window.showStatus&&window.showStatus(e.message,true);}}
  function view(slug){window.open('/store/book/'+encodeURIComponent(slug),'_blank','noopener');}
  window.initStoreAdmin=mount;
  window.loadStoreAdmin=load;
  window.clearStoreForm=clearForm;
  window.saveStoreProduct=save;
  window.editStoreProduct=edit;
  window.archiveStoreProduct=archive;
  window.viewStoreProduct=view;
})();

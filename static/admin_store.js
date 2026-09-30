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
          <label>Book Photo</label><input id="storePhoto" type="file" accept="image/png,image/jpeg,image/gif,image/webp">
          <img id="storePhotoPreview" alt="Photo preview" style="display:none;max-width:160px;margin-top:6px;border:1px solid #C9B78F;border-radius:4px">
          <label>Cover Image URL <span class="note">(optional — paste a link instead of uploading)</span></label><input id="storeCover" type="url" placeholder="https://...">
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
    const photoInput=document.getElementById('storePhoto');
    photoInput.addEventListener('change',()=>{
      const f=photoInput.files[0]; const prev=document.getElementById('storePhotoPreview');
      if(f){prev.src=URL.createObjectURL(f);prev.style.display='block';}
      else{prev.src='';prev.style.display='none';}
    });
  }
  function clearForm(){
    editingId=null;
    document.getElementById('storeFormHeading').textContent='Add a Book to the Store';
    document.getElementById('storeSaveButton').textContent='Add Book';
    ['storeTitle','storeDescription','storeIsbn','storeCover'].forEach(id=>document.getElementById(id).value='');
    document.getElementById('storePhoto').value='';
    const prev0=document.getElementById('storePhotoPreview'); prev0.src=''; prev0.style.display='none';
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
    document.getElementById('storePhoto').value='';
    const prev=document.getElementById('storePhotoPreview');
    if(p.cover_image_url){prev.src=p.cover_image_url;prev.style.display='block';}
    else{prev.src='';prev.style.display='none';}
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
        card.innerHTML=`<div style="flex:1"><h3>${esc(p.title)}</h3><small>${esc(p.author||'')} · ${esc(p.format||'')} · $${esc(p.price||'0.00')} · <strong>${esc(status)}</strong></small><p>${esc((p.description||'').slice(0,180))}${(p.description||'').length>180?'…':''}</p><small>ISBN: ${esc(p.isbn||'—')} · Stock: ${esc(p.stock_quantity??0)}</small></div><div class="small-actions"><button type="button" onclick="window.editStoreProduct(${p.id})">Edit</button><button type="button" class="gold" onclick="window.viewStoreProduct('${esc(p.slug)}')">View</button>${status!=='archived'?'<button type="button" class="danger" onclick="window.archiveStoreProduct('+p.id+')">Archive</button>':''}<button type="button" class="danger" onclick="window.deleteStoreProduct('+p.id+')">Delete</button></div>`;
        list.appendChild(card);
      });
    }catch(e){list.innerHTML=`<p class="note">${esc(e.message)}</p>`;}
  }
  async function save(){
    const title=document.getElementById('storeTitle').value.trim();
    if(!title){return window.showStatus&&window.showStatus('Give the book a title first.',true);}
    const fd=new FormData();
    fd.append('title',title);
    fd.append('author',document.getElementById('storeAuthor').value.trim());
    fd.append('description',document.getElementById('storeDescription').value.trim());
    fd.append('price',document.getElementById('storePrice').value);
    fd.append('format',document.getElementById('storeFormat').value);
    fd.append('isbn',document.getElementById('storeIsbn').value.trim());
    fd.append('stock_quantity',document.getElementById('storeStock').value);
    const url=document.getElementById('storeCover').value.trim();
    if(url)fd.append('cover_image_url',url);
    fd.append('category',document.getElementById('storeCategory').value.trim()||'Books');
    fd.append('status',document.getElementById('storeStatus').value);
    const f=document.getElementById('storePhoto').files[0];
    if(f)fd.append('photo',f);
    try{
      const r=await fetch(editingId?`/api/store/admin/products/${editingId}`:'/api/store/admin/products',{method:editingId?'PUT':'POST',credentials:'same-origin',body:fd});
      let data={}; try{data=await r.json();}catch(_){ /* non-JSON: treat as failure below */ }
      if(!r.ok||data.success===false)throw new Error(data.error||`Could not save the book (${r.status}).`);
      clearForm(); await load();
      if(window.showStatus)window.showStatus(data.photo_warning?('Book saved, but the photo was not: '+data.photo_warning):(editingId?'Book updated.':'Book added to The Scriptorium Store.'));
    }catch(e){if(window.showStatus)window.showStatus(e.message,true);}
  }
  async function edit(id){try{fill(await api(`/api/store/admin/products/${id}`));}catch(e){window.showStatus&&window.showStatus(e.message,true);}}
  async function archive(id){if(!confirm('Archive this book? It will no longer appear on the public store.'))return;try{await api(`/api/store/admin/products/${id}`,{method:'DELETE'});await load();window.showStatus&&window.showStatus('Book archived.');}catch(e){window.showStatus&&window.showStatus(e.message,true);}}
  async function del(id){if(!confirm('Delete this book permanently? This cannot be undone.'))return;try{await api(`/api/store/admin/products/${id}?permanent=1`,{method:'DELETE'});await load();window.showStatus&&window.showStatus('Book deleted.');}catch(e){window.showStatus&&window.showStatus(e.message,true);}}
  function view(slug){window.open('/store/book/'+encodeURIComponent(slug),'_blank','noopener');}
  window.initStoreAdmin=mount;
  window.loadStoreAdmin=load;
  window.clearStoreForm=clearForm;
  window.saveStoreProduct=save;
  window.editStoreProduct=edit;
  window.archiveStoreProduct=archive;
  window.deleteStoreProduct=del;
  window.viewStoreProduct=view;
})();

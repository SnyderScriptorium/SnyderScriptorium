(function(){
  'use strict';
  let editingId=null;
  let allProducts=[];
  const filters={q:'',genre:'all',letter:'all'};
  const esc=v=>{const d=document.createElement('div');d.textContent=v==null?'':String(v);return d.innerHTML;};
  async function api(url,options={}){
    const r=await fetch(url,{credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
    const ct=r.headers.get('content-type')||'';
    if(!ct.includes('application/json'))
      throw new Error('Your admin login expired — refresh the page and log in again, then retry.');
    const data=await r.json();
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
          <label>More Photos <span class="note">(optional — up to 6; customers swipe through them like eBay)</span></label><input id="storePhotos" type="file" multiple accept="image/png,image/jpeg,image/gif,image/webp">
          <div id="storePhotosPreview" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px"></div>
          <div id="storeGalleryExisting" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px"></div>
          <label>Cover Image URL <span class="note">(optional — paste a link instead of uploading)</span></label><input id="storeCover" type="url" placeholder="https://...">
          <div class="two"><div><label>Section</label><select id="storeCategory"><option>Antique</option><option selected>Vintage</option><option>Used</option><option>New</option></select></div><div><label>Genre <span class="note">(used under New — e.g. Mystery)</span></label><input id="storeGenre" type="text" list="storeGenreList" placeholder="e.g. Mystery"><datalist id="storeGenreList"></datalist></div></div>
          <label>Status</label><select id="storeStatus"><option value="draft">Draft</option><option value="active">Active — show on the store</option><option value="archived">Archived</option></select>
          <div class="actions"><button type="button" id="storeSaveButton" onclick="window.saveStoreProduct()">Add Book</button><button type="button" class="light" onclick="window.clearStoreForm()">Clear</button></div>
        </div>
        <div class="preview">
          <h3 class="section-title">Books in the Store</h3>
          <p class="note">Drafts stay hidden from customers. Active books appear on The Scriptorium shelves.</p>
          <div id="storeFilterBar" style="margin-bottom:10px">
            <input id="storeSearch" type="search" placeholder="Search title, author, ISBN…" style="width:100%;box-sizing:border-box;margin-bottom:8px">
            <div id="storeGenrePills" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px"></div>
            <div id="storeLetterRow" style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px"></div>
            <p class="note" id="storeFilterCount" style="margin:0"></p>
          </div>
          <div id="storeProductList" class="list"><p class="note">Loading...</p></div>
        </div>
      </div>`;
    const photoInput=document.getElementById('storePhoto');
    photoInput.addEventListener('change',()=>{
      const f=photoInput.files[0]; const prev=document.getElementById('storePhotoPreview');
      if(f){prev.src=URL.createObjectURL(f);prev.style.display='block';}
      else{prev.src='';prev.style.display='none';}
    });
    const multiInput=document.getElementById('storePhotos');
    multiInput.addEventListener('change',()=>{
      const wrap=document.getElementById('storePhotosPreview'); wrap.innerHTML='';
      [...multiInput.files].forEach(f=>{
        const img=document.createElement('img');
        img.src=URL.createObjectURL(f); img.alt='New photo preview';
        img.style.cssText='width:72px;height:72px;object-fit:cover;border:1px solid #C9B78F;border-radius:4px';
        wrap.appendChild(img);
      });
    });
    const searchInput=document.getElementById('storeSearch');
    searchInput.addEventListener('input',()=>{filters.q=searchInput.value.trim().toLowerCase();renderList();});
  }
  function clearForm(){
    editingId=null;
    document.getElementById('storeFormHeading').textContent='Add a Book to the Store';
    document.getElementById('storeSaveButton').textContent='Add Book';
    ['storeTitle','storeDescription','storeIsbn','storeCover'].forEach(id=>document.getElementById(id).value='');
    document.getElementById('storePhoto').value='';
    const prev0=document.getElementById('storePhotoPreview'); prev0.src=''; prev0.style.display='none';
    document.getElementById('storePhotos').value='';
    document.getElementById('storePhotosPreview').innerHTML='';
    document.getElementById('storeGalleryExisting').innerHTML='';
    document.getElementById('storeAuthor').value='K. W. Snyder';
    document.getElementById('storePrice').value='';
    document.getElementById('storeStock').value='0';
    document.getElementById('storeCategory').value='Vintage';
    document.getElementById('storeGenre').value='';
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
    const ex=document.getElementById('storeGalleryExisting'); ex.innerHTML='';
    (p.images||[]).forEach(img=>{
      const d=document.createElement('div');
      d.style.cssText='position:relative;width:72px;height:72px';
      const thumb=document.createElement('img');
      thumb.src=img.image_url; thumb.alt='Gallery photo';
      thumb.style.cssText='width:72px;height:72px;object-fit:cover;border:1px solid #C9B78F;border-radius:4px';
      const x=document.createElement('button');
      x.type='button'; x.textContent='×'; x.title='Remove this photo';
      x.style.cssText='position:absolute;top:-8px;right:-8px;width:22px;height:22px;border-radius:50%;border:1px solid #8a6d3b;background:#fff;color:#8a6d3b;font-weight:bold;cursor:pointer;line-height:1';
      x.addEventListener('click',()=>window.deleteStoreImage(img.id));
      d.appendChild(thumb); d.appendChild(x); ex.appendChild(d);
    });
    document.getElementById('storePhotos').value='';
    document.getElementById('storePhotosPreview').innerHTML='';
    const catSel=document.getElementById('storeCategory');
    const cat=p.category||'Vintage';
    if(![...catSel.options].some(o=>o.value===cat)){
      const opt=document.createElement('option');opt.value=cat;opt.textContent=cat+' (legacy)';catSel.appendChild(opt);
    }
    catSel.value=cat;
    document.getElementById('storeGenre').value=p.genre||'';
    document.getElementById('storeStatus').value=p.status||'draft';
    document.getElementById('storeTitle').focus();
  }
  function pillButton(label,active){
    const b=document.createElement('button');
    b.type='button'; b.textContent=label;
    b.style.cssText='padding:4px 10px;border-radius:999px;border:1px solid #C9B78F;background:'+(active?'#8a6d3b':'#fff')+';color:'+(active?'#fff':'#5C4033')+';cursor:pointer;font-size:.85rem';
    return b;
  }
  function buildFilterControls(){
    const genreWrap=document.getElementById('storeGenrePills');
    if(genreWrap){
      genreWrap.innerHTML='';
      const genres=[...new Set(allProducts.map(p=>(p.genre||'').trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
      [['all','All']].concat(genres.map(g=>[g,g])).forEach(pair=>{
        const b=pillButton(pair[1],filters.genre===pair[0]);
        b.addEventListener('click',()=>{filters.genre=pair[0];buildFilterControls();renderList();});
        genreWrap.appendChild(b);
      });
    }
    const letterWrap=document.getElementById('storeLetterRow');
    if(letterWrap){
      letterWrap.innerHTML='';
      const letters=[...new Set(allProducts.map(p=>{const c=(p.title||'').trim().toUpperCase().charAt(0);return (c>='A'&&c<='Z')?c:'';}).filter(Boolean))].sort();
      [['all','All']].concat(letters.map(l=>[l,l])).forEach(pair=>{
        const b=pillButton(pair[1],filters.letter===pair[0]);
        b.addEventListener('click',()=>{filters.letter=pair[0];buildFilterControls();renderList();});
        letterWrap.appendChild(b);
      });
    }
  }
  function renderList(){
    const list=document.getElementById('storeProductList'); if(!list)return;
    const q=filters.q;
    const items=allProducts.filter(p=>{
      if(filters.genre!=='all'&&(p.genre||'').trim()!==filters.genre)return false;
      if(filters.letter!=='all'&&(p.title||'').trim().toUpperCase().charAt(0)!==filters.letter)return false;
      if(q){
        const hay=((p.title||'')+' '+(p.author||'')+' '+(p.isbn||'')).toLowerCase();
        if(hay.indexOf(q)<0)return false;
      }
      return true;
    });
    const count=document.getElementById('storeFilterCount');
    if(count)count.textContent=allProducts.length?(items.length+' of '+allProducts.length+' books'):'';
    list.innerHTML=items.length?'':'<p class="note">'+(allProducts.length?'No books match these filters.':'No books have been added to the store yet. Add your first finished book on the left.')+'</p>';
    items.forEach(p=>{
      const card=document.createElement('div'); card.className='card';
      const status=p.status||'draft';
      card.innerHTML=`<div style="flex:1"><h3>${esc(p.title)}</h3><small>${esc(p.author||'')} · ${esc(p.format||'')} · $${esc(p.price||'0.00')} · <strong>${esc(status)}</strong> · Section: ${esc(p.section||p.category||'—')}${p.genre?(' · Genre: '+esc(p.genre)):''}</small><p>${esc((p.description||'').slice(0,180))}${(p.description||'').length>180?'…':''}</p><small>ISBN: ${esc(p.isbn||'—')} · Stock: ${esc(p.stock_quantity??0)}</small></div><div class="small-actions"><button type="button" onclick="window.editStoreProduct(${p.id})">Edit</button><button type="button" class="gold" onclick="window.viewStoreProduct('${esc(p.slug)}')">View</button>${status!=='archived'?'<button type="button" class="danger" onclick="window.archiveStoreProduct('+p.id+')">Archive</button>':''}<button type="button" class="danger" onclick="window.deleteStoreProduct('+p.id+')">Delete</button></div>`;
      list.appendChild(card);
    });
  }
  async function load(){
    mount();
    const list=document.getElementById('storeProductList'); if(!list)return;
    list.innerHTML='<p class="note">Loading books...</p>';
    try{
      allProducts=await api('/api/store/admin/products');
      const dl=document.getElementById('storeGenreList');
      if(dl){
        const genres=[...new Set(allProducts.map(p=>(p.genre||'').trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
        dl.innerHTML=genres.map(g=>`<option value="${esc(g)}">`).join('');
      }
      buildFilterControls();
      renderList();
    }catch(e){list.innerHTML=`<p class="note">${esc(e.message)}</p>`;}
  }
  async function fileToUpload(file){
    // Shrink phone photos so they clear the 5 MB server limit.
    let bitmap=null;
    try{bitmap=await createImageBitmap(file);}catch(_){return file;}
    const MAX=1600;
    let w=bitmap.width,h=bitmap.height;
    if(Math.max(w,h)<=MAX&&file.size<=4500000){bitmap.close();return file;}
    const scale=Math.min(1,MAX/Math.max(w,h));
    w=Math.max(1,Math.round(w*scale));h=Math.max(1,Math.round(h*scale));
    const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
    canvas.getContext('2d').drawImage(bitmap,0,0,w,h);
    bitmap.close();
    const blob=await new Promise(res=>{try{canvas.toBlob(res,'image/jpeg',0.85);}catch(_){res(null);}});
    if(!blob)return file;
    return new File([blob],String(file.name||'photo').replace(/\.[^.]+$/,'')+'.jpg',{type:'image/jpeg'});
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
    fd.append('category',document.getElementById('storeCategory').value.trim()||'Vintage');
    fd.append('genre',document.getElementById('storeGenre').value.trim());
    fd.append('status',document.getElementById('storeStatus').value);
    const f=document.getElementById('storePhoto').files[0];
    if(f)fd.append('photo',await fileToUpload(f));
    const extras=[...document.getElementById('storePhotos').files];
    for(const g of extras){fd.append('photos',await fileToUpload(g));}
    try{
      const r=await fetch(editingId?`/api/store/admin/products/${editingId}`:'/api/store/admin/products',{method:editingId?'PUT':'POST',credentials:'same-origin',body:fd});
      const ct=r.headers.get('content-type')||'';
      if(!ct.includes('application/json'))
        throw new Error('Your admin login expired — refresh the page and log in again, then retry.');
      const data=await r.json();
      if(!r.ok||data.success===false)throw new Error(data.error||`Could not save the book (${r.status}).`);
      clearForm(); await load();
      if(window.showStatus)window.showStatus(data.photo_warning?('Book saved, but the photo was not: '+data.photo_warning):(editingId?'Book updated.':'Book added to The Scriptorium Store.'));
    }catch(e){if(window.showStatus)window.showStatus(e.message,true);}
  }
  async function edit(id){try{fill(await api(`/api/store/admin/products/${id}`));}catch(e){window.showStatus&&window.showStatus(e.message,true);}}
  async function archive(id){if(!confirm('Archive this book? It will no longer appear on the public store.'))return;try{await api(`/api/store/admin/products/${id}`,{method:'DELETE'});await load();window.showStatus&&window.showStatus('Book archived.');}catch(e){window.showStatus&&window.showStatus(e.message,true);}}
  async function del(id){if(!confirm('Delete this book permanently? This cannot be undone.'))return;try{await api(`/api/store/admin/products/${id}?permanent=1`,{method:'DELETE'});await load();window.showStatus&&window.showStatus('Book deleted.');}catch(e){window.showStatus&&window.showStatus(e.message,true);}}
  async function deleteImage(id){if(!confirm('Remove this photo?'))return;try{await api(`/api/store/admin/product-images/${id}`,{method:'DELETE'});if(editingId)await edit(editingId);window.showStatus&&window.showStatus('Photo removed.');}catch(e){window.showStatus&&window.showStatus(e.message,true);}}
  function view(slug){window.open('/store/book/'+encodeURIComponent(slug),'_blank','noopener');}
  window.initStoreAdmin=mount;
  window.loadStoreAdmin=load;
  window.clearStoreForm=clearForm;
  window.saveStoreProduct=save;
  window.editStoreProduct=edit;
  window.archiveStoreProduct=archive;
  window.deleteStoreProduct=del;
  window.deleteStoreImage=deleteImage;
  window.viewStoreProduct=view;
})();

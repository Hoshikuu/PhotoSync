const login = document.querySelector('#login');
const gallery = document.querySelector('#gallery');
const form = document.querySelector('#login-form');
const tokenInput = document.querySelector('#token');
const error = document.querySelector('#login-error');
const status = document.querySelector('#status');
const grid = document.querySelector('#grid');
const next = document.querySelector('#next');
const logout = document.querySelector('#logout');
let token = '';
let offset = 0;
let objectUrls = [];
let generation = 0;
const maxPreviewBytes = 20 * 1024 * 1024;
const imageTypes = {jpg:'image/jpeg', jpeg:'image/jpeg', png:'image/png', gif:'image/gif', webp:'image/webp', avif:'image/avif'};

async function request(path) {
  const response = await fetch(path, {headers:{Authorization:`Bearer ${token}`}, cache:'no-store'});
  if (!response.ok) throw new Error(response.status === 401 ? 'El token no es válido o ha sido revocado.' : `No se pudo acceder al servidor (${response.status}).`);
  return response;
}

function clearGallery() {
  generation++;
  for (const url of objectUrls) URL.revokeObjectURL(url);
  objectUrls = [];
  grid.replaceChildren();
}

async function loadPage() {
  const current = generation;
  next.hidden = true;
  status.textContent = 'Cargando archivos…';
  try {
    const data = await (await request(`/gallery/items?offset=${offset}&limit=12`)).json();
    if (current !== generation) return;
    if (!data.items.length) status.textContent = offset ? 'No hay más archivos.' : 'Aún no hay archivos sincronizados para este dispositivo.';
    else status.textContent = '';
    for (const item of data.items) {
      if (current !== generation) return;
      const card = document.createElement('article'); card.className = 'card';
      const wrap = document.createElement('div'); wrap.className = 'image-wrap';
      const placeholder = document.createElement('span'); placeholder.className = 'placeholder';
      const ext = item.filename.split('.').pop().toLowerCase();
      placeholder.textContent = imageTypes[ext] ? (item.size > maxPreviewBytes ? 'Imagen demasiado grande para la vista previa' : 'Cargando imagen…') : 'Vista previa no disponible';
      wrap.append(placeholder);
      const name = document.createElement('p'); name.className = 'filename'; name.textContent = item.filename; name.title = item.filename;
      const meta = document.createElement('div'); meta.className = 'meta'; meta.textContent = `${(item.size / 1048576).toFixed(1)} MB · ${item.created_at.slice(0, 10)}`;
      card.append(wrap, name, meta); grid.append(card);
      if (imageTypes[ext] && item.size <= maxPreviewBytes) {
        try {
          const response = await request(`/gallery/items/${encodeURIComponent(item.client_id)}/content`);
          const bytes = await response.blob();
          if (current !== generation) return;
          const url = URL.createObjectURL(new Blob([bytes], {type:imageTypes[ext]})); objectUrls.push(url);
          const img = document.createElement('img'); img.alt = item.filename; img.loading = 'lazy'; img.src = url;
          img.onerror = () => { wrap.replaceChildren(placeholder); placeholder.textContent = 'No se pudo mostrar la imagen'; };
          wrap.replaceChildren(img);
        } catch (_) { placeholder.textContent = 'No se pudo cargar la imagen'; }
      }
    }
    if (current !== generation) return;
    offset = data.next_offset;
    next.hidden = offset === null;
  } catch (e) { if (current === generation) { status.textContent = e.message; next.hidden = false; } }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault(); error.textContent = ''; token = tokenInput.value.trim();
  try {
    const info = await (await request('/backups/status')).json();
    document.querySelector('#count').textContent = info.count;
    tokenInput.value = ''; login.hidden = true; gallery.hidden = false; logout.hidden = false;
    clearGallery(); offset = 0; await loadPage();
  } catch (e) { token = ''; error.textContent = e.message; }
});
next.addEventListener('click', () => { clearGallery(); loadPage(); });
logout.addEventListener('click', () => { token = ''; clearGallery(); login.hidden = false; gallery.hidden = true; logout.hidden = true; status.textContent = ''; tokenInput.focus(); });

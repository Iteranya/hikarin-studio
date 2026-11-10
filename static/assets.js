/* Hikarin Studio — the asset manager window.
 *
 * One modal, three tabs, and the same two trees the engine reads:
 *
 *   images/characters/<id>/<outfit>/<emotion>.png   sprites
 *   images/<folder>/<image>.png                     backgrounds, image boxes, ui
 *   sounds/music/<track>.ogg   sounds/sound/<sfx>.ogg
 *
 * What it is for: adding a character should not mean opening Explorer and
 * guessing at folder names. Every list here is read from disk, every write goes
 * back to the server, and every mutation re-renders from the inventory the
 * server returns — no local guessing about what landed.
 *
 * Uploads are base64 JSON to the server. The alternative is multipart, which
 * means adding python-multipart to the project; a sprite is small enough that
 * the encoding tax is cheaper than an extra install that can break `uv run`.
 */

const $ = (id) => document.getElementById(id);

const IMAGE_EXT = ['png', 'jpg', 'jpeg', 'webp'];
const AUDIO_EXT = ['ogg', 'wav', 'mp3'];

let ctx = null;              // { state, onChange }
let activeTab = 'characters';
let dragging = 0;

// ── boot ────────────────────────────────────────────────────────────────────

export function initAssets(context) {
  ctx = context;

  $('assets-close').onclick = closeAssets;
  $('assets-refresh').onclick = () => refresh();

  $('assets-backdrop').addEventListener('click', (e) => {
    if (e.target === $('assets-backdrop')) closeAssets();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('assets-backdrop').hidden) closeAssets();
  });

  $('asset-tabs').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-tab]');
    if (!btn) return;
    activeTab = btn.dataset.tab;
    render();
  });

  $('assets-body').addEventListener('click', onBodyClick);

  $('asset-target').onchange = () => paintDropTarget();
  $('asset-browse').onclick = () => $('asset-file').click();
  $('asset-file').onchange = async () => {
    const files = Array.from($('asset-file').files ?? []);
    $('asset-file').value = '';
    if (files.length) await upload(files, $('asset-target').value);
  };

  // Drag and drop, on the drop strip and anywhere on the modal. The strip stops
  // propagation so a drop on it is not handled twice.
  const drop = $('asset-drop');
  const enter = (e) => { e.preventDefault(); dragging += 1; drop.classList.add('over'); };
  const leave = (e) => { e.preventDefault(); dragging = Math.max(0, dragging - 1); if (!dragging) drop.classList.remove('over'); };

  drop.addEventListener('dragenter', enter);
  drop.addEventListener('dragover', (e) => e.preventDefault());
  drop.addEventListener('dragleave', leave);
  drop.addEventListener('drop', async (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragging = 0;
    drop.classList.remove('over');
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length) await upload(files, $('asset-target').value);
  });

  const backdrop = $('assets-backdrop');
  backdrop.addEventListener('dragover', (e) => e.preventDefault());
  backdrop.addEventListener('drop', async (e) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length) await upload(files, $('asset-target').value);
  });
}

export function openAssets(tab) {
  if (!ctx?.state.project) {
    alert('Open a project first.');
    return;
  }
  if (tab) activeTab = tab;
  $('assets-backdrop').hidden = false;
  render();
  refresh();
}

export function closeAssets() {
  $('assets-backdrop').hidden = true;
}

/** Delete one asset path, used by the Show block's character field too. */
export async function deleteAssetPath(path) {
  const data = await api('DELETE', `/assets?path=${encodeURIComponent(path)}`);
  apply(data.assets);
  return data;
}

// ── data ────────────────────────────────────────────────────────────────────

function inv() {
  return ctx?.state?.project?.assets ?? {};
}

function slug() {
  return ctx?.state?.project?.slug ?? '';
}

async function api(method, path, body) {
  const res = await fetch(`/api/projects/${slug()}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  let data = {};
  try {
    data = await res.json();
  } catch {
    /* an empty body is not an error by itself */
  }
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`);
  return data;
}

function apply(assets) {
  if (!assets) return;
  ctx.state.project.assets = assets;
  ctx.onChange?.();
  render();
}

async function refresh() {
  setStatus('reading the project folders…');
  try {
    apply(await api('GET', '/asset-list'));
    setStatus('');
  } catch (err) {
    setStatus(String(err.message ?? err), 'error');
  }
}

// ── helpers ─────────────────────────────────────────────────────────────────

function esc(value) {
  return String(value ?? '').replace(/[<>&"']/g, (c) => (
    { '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function humanSize(n) {
  const bytes = Number(n) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 102.4) / 10} KB`;
  return `${Math.round(bytes / (1024 * 1024) * 10) / 10} MB`;
}

function setStatus(text, level = '') {
  const el = $('assets-status');
  if (!el) return;
  el.textContent = text;
  el.className = 'assets-status' + (level ? ` ${level}` : '');
}

function assetUrl(entry) {
  if (!entry?.file) return '';
  let rel = entry.file;
  // The server maps textures/<x> -> images/<x>, so drop the images/ prefix;
  // sounds/ keeps its prefix because that is the mapping it is served through.
  if (rel.startsWith('images/')) rel = rel.slice('images/'.length);
  const encoded = rel.split('/').map(encodeURIComponent).join('/');
  const version = entry.mtime ? `?v=${entry.mtime}` : '';
  return `/api/projects/${slug()}/assets/${encoded}${version}`;
}

function readBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result ?? '');
      resolve(result.slice(result.indexOf(',') + 1));
    };
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    reader.readAsDataURL(file);
  });
}

function tile(entry, label) {
  return `<div class="tile">
    <div class="tile-img"><img src="${assetUrl(entry)}" alt="${esc(label ?? entry.name)}" loading="lazy"></div>
    <div class="tile-name" title="${esc(entry.filename)}">${esc(label ?? entry.name)}</div>
    <button class="tile-del" data-act="delete" data-path="${esc(entry.file)}"
            data-label="${esc(entry.filename)}" title="Delete this file">✕</button>
  </div>`;
}

function emptyBox(title, hint) {
  return `<div class="asset-empty"><div class="asset-empty-title">${esc(title)}</div>
    <div class="asset-empty-hint">${hint}</div></div>`;
}

// ── render ──────────────────────────────────────────────────────────────────

function render() {
  if ($('assets-backdrop').hidden) return;

  $('assets-project').textContent = ctx.state.project.meta?.packName || slug();
  renderTabs();
  renderTargets();

  const body = $('assets-body');
  if (activeTab === 'characters') body.innerHTML = charactersHTML();
  else if (activeTab === 'images') body.innerHTML = imagesHTML();
  else body.innerHTML = audioHTML();

  renderFoot();
}

function renderTabs() {
  const t = inv().totals ?? {};
  const tabs = [
    ['characters', 'Characters', t.characters ?? 0],
    ['images', 'Images', t.images ?? 0],
    ['audio', 'Audio', t.audio ?? 0],
  ];

  $('asset-tabs').innerHTML = tabs.map(([key, label, count]) => `
    <button class="asset-tab${key === activeTab ? ' active' : ''}" data-tab="${key}">
      ${label}<span class="asset-tab-count">${count}</span>
    </button>`).join('');
}

function renderTargets() {
  const options = [];
  for (const char of inv().characterTree ?? []) {
    for (const outfit of char.outfits) {
      options.push({ value: outfit.dir, label: `character · ${char.id} / ${outfit.name}` });
    }
  }
  for (const folder of inv().imageFolders ?? []) {
    options.push({ value: folder.dir, label: `images · ${folder.name}` });
  }
  options.push({ value: 'images', label: 'images · root (pack.png)' });
  options.push({ value: 'sounds/music', label: 'audio · music' });
  options.push({ value: 'sounds/sound', label: 'audio · sound effects' });

  const select = $('asset-target');
  const previous = select.value;
  select.innerHTML = options
    .map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`)
    .join('');

  const preferred = options.some((o) => o.value === previous)
    ? previous
    : defaultTargetForTab(options);

  select.value = preferred ?? options[0]?.value ?? '';
  paintDropTarget();
}

function defaultTargetForTab(options) {
  if (activeTab === 'characters') {
    return options.find((o) => o.value.startsWith('images/characters/'))?.value;
  }
  if (activeTab === 'audio') {
    return 'sounds/music';
  }
  if (activeTab === 'images') {
    return options.find((o) => o.value === 'images/asset')?.value ?? 'images';
  }
  return undefined;
}

function paintDropTarget() {
  const el = $('asset-drop-target');
  if (el) el.textContent = $('asset-target').value || '— pick a folder —';
}

function renderFoot() {
  const t = inv().totals ?? {};
  const limits = inv().limits ?? {};
  const ext = [...IMAGE_EXT, ...AUDIO_EXT].join(' ');
  $('assets-foot').innerHTML = `
    <span>${t.characters ?? 0} character(s) · ${t.images ?? 0} image(s) · ${t.audio ?? 0} sound(s) · ${humanSize(t.bytes)}</span>
    <span class="asset-hint-mini">names are lowercased and dashed on the way in · ${ext} · max
      ${Math.round((limits.maxUploadBytes ?? 0) / 1024 / 1024)} MB per file</span>`;
}

// ── characters ──────────────────────────────────────────────────────────────

function charactersHTML() {
  const chars = inv().characterTree ?? [];
  const parts = [];

  parts.push(`<div class="asset-toolbar">
    <button class="btn tiny primary" data-act="new-character">+ New character</button>
    <span class="asset-hint">A sprite is <code>characters/&lt;id&gt;/&lt;outfit&gt;/&lt;emotion&gt;.png</code> —
      the image file's name is the expression the Show block picks.</span>
  </div>`);

  if (chars.length === 0) {
    parts.push(emptyBox(
      'No characters yet',
      'Press <b>New character</b>, then drop sprite images into its <code>default</code> outfit.'
    ));
    return parts.join('');
  }

  for (const char of chars) {
    const images = char.outfits.flatMap((o) => o.images);
    const thumb = images[0];
    const firstOutfit = char.outfits[0];

    parts.push(`<section class="asset-block">
      <div class="block-head">
        <div class="block-thumb">${thumb ? `<img src="${assetUrl(thumb)}" alt="${esc(char.id)}">` : '<span>?</span>'}</div>
        <div class="block-title-wrap">
          <div class="block-title">${esc(char.id)}</div>
          <div class="asset-hint-mini">${esc(char.dir)} · ${images.length} image(s) · ${char.outfits.length} outfit(s)</div>
        </div>
        ${firstOutfit ? `<button class="btn tiny" data-act="upload" data-dir="${esc(firstOutfit.dir)}">＋ Add images</button>` : ''}
        <button class="btn tiny" data-act="new-outfit" data-char="${esc(char.id)}">+ Outfit</button>
        <button class="btn tiny danger" data-act="delete" data-path="${esc(char.dir)}"
                data-label="the whole character ${esc(char.id)}">Delete character</button>
      </div>`);

    for (const outfit of char.outfits) {
      parts.push(`<div class="outfit">
        <div class="outfit-head">
          <span class="outfit-name">${esc(outfit.name)}</span>
          <span class="asset-hint-mini">${esc(outfit.dir)}</span>
          <button class="icon-btn" data-act="upload" data-dir="${esc(outfit.dir)}" title="Add images to this outfit">＋</button>
          <button class="icon-btn danger" data-act="delete" data-path="${esc(outfit.dir)}"
                  data-label="the outfit ${esc(outfit.name)}" title="Delete this outfit">✕</button>
        </div>
        <div class="tiles">
          ${outfit.images.map((img) => tile(img)).join('')}
          <button class="tile tile-add" data-act="upload" data-dir="${esc(outfit.dir)}">
            <span>＋</span><small>add images</small>
          </button>
        </div>
        ${outfit.images.length ? '' : `<div class="asset-hint" style="margin-top:6px">
          Empty. Drop PNGs here — <code>happy.png</code> becomes the expression <code>happy</code>.</div>`}
      </div>`);
    }

    parts.push('</section>');
  }

  return parts.join('');
}

// ── images ──────────────────────────────────────────────────────────────────

function imagesHTML() {
  const parts = [];
  const icon = inv().packIcon;
  const loose = inv().looseImages ?? [];
  const folders = inv().imageFolders ?? [];

  parts.push(`<div class="asset-toolbar">
    <button class="btn tiny primary" data-act="new-folder">+ New folder</button>
    <span class="asset-hint">Anything under <code>images/</code>. Drop a background in <code>asset/</code>
      and the Background block will offer it.</span>
  </div>`);

  parts.push(`<section class="asset-block">
    <div class="block-head">
      <div class="block-title-wrap">
        <div class="block-title">Pack icon</div>
        <div class="asset-hint-mini">images/pack.png — the picture in Minecraft's resource pack list</div>
      </div>
      ${icon ? `<button class="icon-btn danger" data-act="delete" data-path="images/pack.png" data-label="the pack icon" title="Delete">✕</button>` : ''}
    </div>
    <div class="tiles">
      ${icon ? tile(icon, 'pack.png') : `<button class="tile tile-add" data-act="upload" data-dir="images">
        <span>＋</span><small>set pack icon</small></button>`}
    </div>
  </section>`);

  if (loose.length) {
    parts.push(`<section class="asset-block">
      <div class="block-head">
        <div class="block-title-wrap">
          <div class="block-title">Loose images</div>
          <div class="asset-hint-mini">directly in images/ — not in any folder</div>
        </div>
        <button class="btn tiny" data-act="upload" data-dir="images">＋ Add</button>
      </div>
      <div class="tiles">${loose.map((img) => tile(img)).join('')}</div>
    </section>`);
  }

  if (folders.length === 0 && loose.length === 0) {
    parts.push(emptyBox('No image folders', 'Press <b>New folder</b> to make one — <code>asset</code> is where backgrounds live.'));
  }

  for (const folder of folders) {
    parts.push(`<section class="asset-block">
      <div class="block-head">
        <div class="block-title-wrap">
          <div class="block-title">${esc(folder.name)}</div>
          <div class="asset-hint-mini">${esc(folder.dir)} · ${folder.images.length} image(s)</div>
        </div>
        <button class="btn tiny" data-act="upload" data-dir="${esc(folder.dir)}">＋ Add images</button>
        <button class="icon-btn danger" data-act="delete" data-path="${esc(folder.dir)}"
                data-label="the folder ${esc(folder.name)} and everything in it" title="Delete folder">✕</button>
      </div>
      <div class="tiles">
        ${folder.images.map((img) => tile(img)).join('')}
        <button class="tile tile-add" data-act="upload" data-dir="${esc(folder.dir)}">
          <span>＋</span><small>add images</small></button>
      </div>
    </section>`);
  }

  return parts.join('');
}

// ── audio ───────────────────────────────────────────────────────────────────

function audioHTML() {
  const audio = inv().audio ?? { music: [], sound: [] };
  const parts = [];

  parts.push(`<div class="asset-toolbar">
    <span class="asset-hint">Music loops under a scene, sound effects fire once. Scripts name them
      without the folder or extension — <code>haggstrom.ogg</code> is <code>haggstrom</code>.</span>
  </div>`);

  for (const [key, label, dir, hint] of [
    ['music', 'Music', 'sounds/music', 'sounds/music/'],
    ['sound', 'Sound effects', 'sounds/sound', 'sounds/sound/'],
  ]) {
    const rows = audio[key] ?? [];
    parts.push(`<section class="asset-block">
      <div class="block-head">
        <div class="block-title-wrap">
          <div class="block-title">${label}</div>
          <div class="asset-hint-mini">${hint} · ${rows.length} file(s)</div>
        </div>
        <button class="btn tiny" data-act="upload" data-dir="${dir}">＋ Add audio</button>
      </div>
      ${rows.length ? `<div class="audio-rows">${rows.map((entry) => `
        <div class="audio-row">
          <button class="icon-btn" data-act="play" data-file="${esc(entry.file)}" data-mtime="${entry.mtime}" title="Preview">▶</button>
          <span class="audio-name">${esc(entry.name)}</span>
          <span class="audio-meta">${esc(entry.filename)} · ${humanSize(entry.size)}</span>
          <button class="icon-btn danger" data-act="delete" data-path="${esc(entry.file)}"
                  data-label="${esc(entry.filename)}" title="Delete">✕</button>
        </div>`).join('')}</div>`
        : `<div class="asset-hint">Nothing here yet.</div>`}
    </section>`);
  }

  return parts.join('');
}

// ── actions ─────────────────────────────────────────────────────────────────

async function onBodyClick(event) {
  const btn = event.target.closest('[data-act]');
  if (!btn) return;

  const act = btn.dataset.act;

  try {
    switch (act) {
      case 'new-character':
        await newCharacter();
        break;

      case 'new-outfit':
        await newOutfit(btn.dataset.char);
        break;

      case 'new-folder':
        await newFolder();
        break;

      case 'upload':
        await pickFiles(btn.dataset.dir);
        break;

      case 'delete':
        await removePath(btn.dataset.path, btn.dataset.label);
        break;

      case 'play': {
        const url = `${assetUrl({ file: btn.dataset.file, mtime: Number(btn.dataset.mtime) })}`;
        // One preview at a time, so dragging through a folder does not become a
        // chorus of half-second ogg stubs.
        const current = document.querySelector('audio.asset-audio');
        current?.pause();
        const player = new Audio(url);
        player.className = 'asset-audio';
        player.play().catch(() => setStatus('Could not play that file', 'error'));
        break;
      }

      default:
        break;
    }
  } catch (err) {
    setStatus(String(err.message ?? err), 'error');
  }
}

async function pickFiles(dir) {
  if (!dir) {
    setStatus('Pick a target folder first', 'error');
    return;
  }
  const select = $('asset-target');
  if ([...select.options].some((o) => o.value === dir)) {
    select.value = dir;
    paintDropTarget();
  }
  $('asset-file').click();
}

async function newCharacter() {
  const name = prompt('Character name (lowercase, e.g. cupa)');
  if (!name) return;
  const outfit = prompt('First outfit folder', 'default') ?? 'default';

  setStatus('creating…');
  const data = await api('POST', '/assets/character', { character: name, outfit });
  apply(data.assets);

  const dir = data.created.dir;
  setStatus(`Created ${dir} — it is the upload target now`, 'ok');
  const select = $('asset-target');
  if ([...select.options].some((o) => o.value === dir)) {
    select.value = dir;
    paintDropTarget();
  }
  activeTab = 'characters';
  render();
}

async function newOutfit(character) {
  const outfit = prompt(`New outfit for ${character}`, 'summer');
  if (!outfit) return;

  setStatus('creating…');
  const data = await api('POST', '/assets/outfit', { character, outfit });
  apply(data.assets);
  setStatus(`Added outfit ${outfit} to ${character}`, 'ok');
}

async function newFolder() {
  const name = prompt('New image folder (e.g. ui)', 'ui');
  if (!name) return;

  setStatus('creating…');
  const data = await api('POST', '/assets/folder', { path: `images/${name}` });
  apply(data.assets);
  setStatus(`Created ${data.created.dir}`, 'ok');
}

async function removePath(path, label) {
  if (!path) return;
  const readable = label || path;
  if (!confirm(`Delete ${readable}?\n\n${path}\n\nThis removes it from disk and cannot be undone.`)) return;

  setStatus('deleting…');
  const data = await api('DELETE', `/assets?path=${encodeURIComponent(path)}`);
  apply(data.assets);
  setStatus(`Deleted ${data.deleted.deleted}`, 'ok');
}

async function upload(files, dir) {
  if (!dir) {
    setStatus('Pick a target folder first', 'error');
    return;
  }

  const maxBytes = inv().limits?.maxUploadBytes ?? 24 * 1024 * 1024;
  const accepted = [];
  let skipped = 0;
  let tooBig = 0;

  for (const file of files) {
    const ok = /\.(png|jpe?g|webp|ogg|wav|mp3)$/i.test(file.name);
    if (!ok) { skipped += 1; continue; }
    if (file.size > maxBytes) { tooBig += 1; continue; }
    accepted.push(file);
  }

  if (!accepted.length) {
    setStatus(
      `Nothing to upload — only ${IMAGE_EXT.join(', ')} and ${AUDIO_EXT.join(', ')}`
      + (tooBig ? `, and ${tooBig} file(s) over ${Math.round(maxBytes / 1024 / 1024)} MB` : ''),
      'error'
    );
    return;
  }

  setStatus(`uploading ${accepted.length} file(s) → ${dir} …`);

  const payload = [];
  for (const file of accepted) {
    payload.push({ name: file.name, data: await readBase64(file) });
  }

  const data = await api('POST', '/assets/upload', { dir, files: payload });
  apply(data.assets);

  const renamed = data.written.filter((w) => w.renamedFrom);
  const notes = [`added ${data.written.length} file(s) to ${dir}`];
  if (renamed.length) notes.push(`renamed: ${renamed.map((w) => `${w.renamedFrom} → ${w.file.split('/').pop()}`).join(', ')}`);
  if (skipped) notes.push(`skipped ${skipped} unsupported`);
  if (tooBig) notes.push(`skipped ${tooBig} too large`);

  setStatus(notes.join(' · '), 'ok');
}

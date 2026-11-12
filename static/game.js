/* Hikarin Studio — Game editor.
 *
 * Visual surface for kind === "game" projects. The world IS hikarin: flags
 * are @world.* variables, switching maps is a hikarin action (map → switch),
 * and triggers are hikarin dialogue — this file owns the map grid painter
 * and the shared-variable registry, nothing else. There is no secondary
 * graph language and never will be.
 */

const $ = (id) => document.getElementById(id);

const state = {
  project: null,
  worldFiles: [],
  events: [],
  data: null,             // { startMap, maps: { slug: map } }
  activeMapId: null,
  cellSize: 32,
  tool: 'tiles',          // tiles | entities | spawn
  activeTileId: null,     // tile being painted
  activeEntityIndex: null,
  dirty: false,
  imageCache: new Map(),  // url -> HTMLImageElement
};

const DEFAULT_GRASS = 'grass';

function defaultMap(id = 'home') {
  const tiles = Array(16 * 16).fill(DEFAULT_GRASS);
  return {
    cols: 16,
    rows: 16,
    tiles,
    palette: {
      [DEFAULT_GRASS]: { image: 'asset/grass.png', traversable: true },
    },
    entities: [],
    spawn: { col: 8, row: 8, facing: 'down' },
  };
}

function defaultWorld() {
  return { startMap: 'home', maps: { home: defaultMap('home') } };
}

export async function openGameEditor(project) {
  state.project = project;
  state.dirty = false;
  state.activeEntityIndex = null;
  state.imageCache.clear();
  registryLoaded = false;
  $('game-vars-tbody').innerHTML = '';
  $('game-build-status').textContent = 'not built';
  $('game-build-status').className = 'chip subtle';

  const world = await fetch(`/api/projects/${project.slug}/world`).then((r) => r.json());
  state.worldFiles = world.worldFiles ?? [];
  state.events = world.events ?? [];

  await loadMapsFile();
  await loadVariablesEditor();
  renderAll();
  wireGameChrome();
}

export function closeGameEditor() {
  $('game-shell').hidden = true;
}

// ── maps.json round-trip ──────────────────────────────────────────────────────

async function loadMapsFile() {
  let raw = null;
  try {
    const text = await fetch(`/api/projects/${state.project.slug}/worldfile/maps.json`).then((r) => (r.ok ? r.text() : null));
    raw = text ? JSON.parse(text) : null;
  } catch {
    raw = null;
  }
  if (!raw || typeof raw !== 'object' || !raw.maps) raw = defaultWorld();
  if (!raw.startMap) raw.startMap = Object.keys(raw.maps)[0];
  state.data = raw;

  for (const map of Object.values(raw.maps)) {
    if (!map.palette) map.palette = { [DEFAULT_GRASS]: { image: 'asset/grass.png', traversable: true } };
    if (!Array.isArray(map.tiles)) map.tiles = Array(map.cols * map.rows).fill(Object.keys(map.palette)[0]);
    if (!map.entities) map.entities = [];
    if (!map.spawn) map.spawn = { col: 0, row: 0, facing: 'down' };
  }

  if (!state.activeMapId || !raw.maps[state.activeMapId]) {
    state.activeMapId = raw.startMap ?? Object.keys(raw.maps)[0];
  }
  if (!state.activeTileId) {
    state.activeTileId = Object.keys(activeMap().palette)[0] ?? DEFAULT_GRASS;
  }
}

function activeMap() {
  return state.data.maps[state.activeMapId];
}

function mapsPayload() {
  return JSON.stringify(state.data, null, 2) + '\n';
}

async function saveMapsFile() {
  const res = await fetch(`/api/projects/${state.project.slug}/worldfile/maps.json`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: mapsPayload() }),
  });
  return res.ok;
}

async function saveAll() {
  const [maps] = await Promise.all([saveMapsFile(), saveVariablesRegistry()]);
  if (maps) {
    state.dirty = false;
    flashStatus('saved', 'chip subtle');
    return true;
  }
  flashStatus('✕ save failed', 'chip');
  return false;
}

function flashStatus(text, cls) {
  const el = $('game-build-status');
  el.textContent = text;
  el.className = cls;
}

function markDirty() {
  state.dirty = true;
  $('game-build-status').textContent = 'unsaved';
  $('game-build-status').className = 'chip';
}

// ── render ────────────────────────────────────────────────────────────────────

function renderAll() {
  renderMapList();
  renderTileTray();
  renderTileEditor();
  renderEntityTray();
  renderEntityEditor();
  renderCanvas();
  $('game-vars-count').textContent = `${$('game-vars-tbody').children.length} declared`;
  $('game-map-name').textContent = `${state.activeMapId}${state.data.startMap === state.activeMapId ? ' ⬢ start' : ''}`;
  const m = activeMap();
  $('game-map-dims').textContent = `${m.cols}×${m.rows} · spawn (${m.spawn.col},${m.spawn.row}) ${m.spawn.facing}`;
  $('game-map-zoom-label').textContent = `${state.cellSize}px`;
}

function renderMapList() {
  const list = $('game-map-list');
  const maps = state.data.maps;
  list.innerHTML = Object.keys(maps).map((id) => {
    const map = maps[id];
    const active = id === state.activeMapId ? ' active' : '';
    const star = id === state.data.startMap ? ' ⬢' : '';
    return `<button class="game-map-item${active}" data-map="${escapeHtml(id)}">
      <span class="game-map-item-name">${escapeHtml(id)}${star}</span>
      <span class="game-map-item-dims">${map.cols}×${map.rows}</span>
    </button>`;
  }).join('');
  list.querySelectorAll('.game-map-item').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.activeMapId = btn.dataset.map;
      state.activeEntityIndex = null;
      state.activeTileId = Object.keys(activeMap().palette)[0] ?? state.activeTileId;
      renderAll();
    });
    btn.addEventListener('contextmenu', (ev) => {
      ev.preventDefault();
      setStartMap(btn.dataset.map);
    });
  });
}

function renderTileTray() {
  const tray = $('game-tile-tray');
  const palette = activeMap().palette;
  if (!Object.keys(palette).length) {
    tray.innerHTML = '<div class="game-map-hint">No tiles yet — press ＋ Tile.</div>';
    return;
  }
  tray.innerHTML = Object.keys(palette).map((id) => {
    const entry = palette[id];
    const url = tileImageUrl(entry.image);
    const active = id === state.activeTileId ? ' active' : '';
    return `<button class="game-tile-chip${active}" data-tile="${escapeHtml(id)}" title="${escapeHtml(entry.image)}">
      <span class="tile-emoji">${tileEmoji(id)}</span>
      <span>${escapeHtml(id)}</span>
      <span class="tile-trav">${entry.traversable ? '↔' : '■'}</span>
    </button>`;
  }).join('');
  tray.querySelectorAll('.game-tile-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      state.activeTileId = chip.dataset.tile;
      renderAll();
    });
  });
}

function renderTileEditor() {
  const palette = activeMap().palette;
  const entry = palette[state.activeTileId];
  $('game-tile-id').value = state.activeTileId ?? '';
  $('game-tile-image').value = entry?.image ?? '';
  $('game-tile-trav').checked = Boolean(entry?.traversable);
}

function tileImageUrl(image) {
  if (!image) return '';
  const rel = image.replace(/^images\//, '');
  const encoded = rel.split('/').map(encodeURIComponent).join('/');
  return `/api/projects/${encodeURIComponent(state.project.slug)}/assets/${encoded}`;
}

function renderEntityTray() {
  const tray = $('game-entity-tray');
  const entities = activeMap().entities ?? [];
  if (!entities.length) {
    tray.innerHTML = '<div class="game-map-hint">No entities — press ＋ Place, then click the grid.</div>';
    return;
  }
  tray.innerHTML = entities.map((e, i) => {
    const active = i === state.activeEntityIndex ? ' active' : '';
    const pos = e.kind === 'static' ? `(${e.col},${e.row})` : 'global';
    return `<button class="game-entity-chip${active}" data-index="${i}"><span>${escapeHtml(e.id ?? '?')}</span><span class="tile-trav">${pos}</span></button>`;
  }).join('');
  tray.querySelectorAll('.game-entity-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      state.activeEntityIndex = Number(chip.dataset.index);
      renderAll();
    });
  });
}

function renderEntityEditor() {
  const entities = activeMap().entities ?? [];
  const e = entities[state.activeEntityIndex];
  $('game-entity-kind').value = e?.kind ?? 'static';
  $('game-entity-id').value = e?.id ?? '';
  $('game-entity-event').innerHTML = ['<option value="">— event…</option>']
    .concat(state.events.map((ev) => `<option value="${escapeHtml(ev)}"${e?.event === ev ? ' selected' : ''}>${escapeHtml(ev)}</option>`))
    .join('');
  $('game-entity-col').value = e?.col ?? '';
  $('game-entity-row').value = e?.row ?? '';
  $('game-entity-vis').value = e?.visible_if ?? '';
  $('game-entity-interact').value = e?.interact_if ?? '';
  $('game-entity-attach').value = e?.attach ?? '';
  const isStatic = (e?.kind ?? 'static') === 'static';
  $('game-entity-col').style.display = isStatic ? '' : 'none';
  $('game-entity-row').style.display = isStatic ? '' : 'none';
  $('game-entity-attach').style.display = isStatic ? 'none' : '';
}

// ── canvas ────────────────────────────────────────────────────────────────────

function renderCanvas() {
  const canvas = $('game-map-canvas');
  const m = activeMap();
  const size = state.cellSize;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = m.cols * size * dpr;
  canvas.height = m.rows * size * dpr;
  canvas.style.width = `${m.cols * size}px`;
  canvas.style.height = `${m.rows * size}px`;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  ctx.clearRect(0, 0, m.cols * size, m.rows * size);
  ctx.fillStyle = '#090b10';
  ctx.fillRect(0, 0, m.cols * size, m.rows * size);

  for (let row = 0; row < m.rows; row++) {
    for (let col = 0; col < m.cols; col++) {
      const tileId = m.tiles[row * m.cols + col];
      const entry = m.palette[tileId];
      if (!entry) continue;
      drawTileCell(ctx, tileId, entry, col * size, row * size, size);
    }
  }

  ctx.strokeStyle = 'rgba(127,134,152,0.25)';
  ctx.lineWidth = 1;
  for (let c = 0; c <= m.cols; c++) { ctx.beginPath(); ctx.moveTo(c * size + .5, 0); ctx.lineTo(c * size + .5, m.rows * size); ctx.stroke(); }
  for (let r = 0; r <= m.rows; r++) { ctx.beginPath(); ctx.moveTo(0, r * size + .5); ctx.lineTo(m.cols * size, r * size + .5); ctx.stroke(); }

  drawMarker(ctx, m.spawn.col, m.spawn.row, size, '🚶', '#38bdf8');

  (m.entities ?? []).forEach((entity, i) => {
    if (entity.kind !== 'static' || entity.col === undefined) return;
    const selected = i === state.activeEntityIndex;
    drawMarker(ctx, entity.col, entity.row, size, 'E', selected ? '#a78bfa' : '#818cf8', selected);
  });
}

function drawTileCell(ctx, tileId, entry, x, y, size) {
  const url = tileImageUrl(entry.image);
  const img = state.imageCache.get(url);
  if (img && img.complete && img.naturalWidth) {
    ctx.drawImage(img, x, y, size, size);
    return;
  }
  if (url && !state.imageCache.has(url)) {
    const image = new Image();
    image.src = url;
    image.onload = () => renderCanvas();
    image.onerror = () => { image._failed = true; renderCanvas(); };
    state.imageCache.set(url, image);
  }
  ctx.fillStyle = hashHue(tileId);
  ctx.fillRect(x, y, size, size);
  ctx.fillStyle = 'rgba(0,0,0,0.35)';
  ctx.fillRect(x + size * 0.2, y + size * 0.1, size * 0.6, size * 0.7);
  ctx.fillStyle = 'rgba(255,255,255,0.85)';
  ctx.font = `${Math.floor(size * 0.62)}px "Segoe UI Emoji", serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(tileEmoji(tileId), x + size / 2, y + size / 2 + 1);
}

function drawMarker(ctx, col, row, size, glyph, color, strong = false) {
  const x = col * size, y = row * size;
  ctx.save();
  ctx.fillStyle = strong ? color : `${color}55`;
  ctx.fillRect(x + 1, y + 1, size - 2, size - 2);
  ctx.fillStyle = '#0d0f14';
  ctx.font = `${Math.floor(size * 0.62)}px serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(glyph, x + size / 2, y + size / 2 + 1);
  ctx.restore();
}

function tileEmoji(id) {
  const key = String(id ?? '').toLowerCase();
  const table = {
    grass: '🌿', tree: '🌳', wall: '🧱', water: '🌊', stone: '🪨', sand: '🏜️',
    snow: '❄️', road: '🛣️', chest: '📦', door: '🚪', void: '⬛', light: '💡',
  };
  if (table[key]) return table[key];
  if (key.includes('grass')) return '🌿';
  if (key.includes('tree')) return '🌳';
  if (key.includes('water') || key.includes('sea') || key.includes('lake')) return '🌊';
  if (key.includes('wall') || key.includes('brick')) return '🧱';
  if (key.includes('stone') || key.includes('rock')) return '🪨';
  if (key.includes('road') || key.includes('path')) return '🛣️';
  return '◻️';
}

function hashHue(key) {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) & 0xffff;
  return `hsl(${h % 360} 40% 30%)`;
}

function cellFromEvent(ev) {
  const canvas = $('game-map-canvas');
  const rect = canvas.getBoundingClientRect();
  const m = activeMap();
  const x = ev.clientX - rect.left;
  const y = ev.clientY - rect.top;
  const col = Math.floor(x / state.cellSize);
  const row = Math.floor(y / state.cellSize);
  if (col < 0 || row < 0 || col >= m.cols || row >= m.rows) return null;
  return { col, row };
}

function paintAt(col, row) {
  const m = activeMap();
  if (state.tool === 'tiles') {
    const tileId = state.activeTileId ?? Object.keys(m.palette)[0];
    if (!tileId) return;
    m.tiles[row * m.cols + col] = tileId;
  } else if (state.tool === 'entities') {
    placeEntityAt(col, row);
    return;
  } else if (state.tool === 'spawn') {
    m.spawn.col = col;
    m.spawn.row = row;
  }
  markDirty();
  renderAll();
}

function pickTileAt(col, row) {
  const m = activeMap();
  state.activeTileId = m.tiles[row * m.cols + col];
  renderAll();
}

function placeEntityAt(col, row) {
  const entities = activeMap().entities;
  if (state.activeEntityIndex !== null && entities[state.activeEntityIndex]) {
    entities[state.activeEntityIndex].col = col;
    entities[state.activeEntityIndex].row = row;
  } else {
    entities.push({ id: `entity_${entities.length + 1}`, kind: 'static', col, row, event: state.events[0] ?? '' });
    state.activeEntityIndex = entities.length - 1;
  }
  markDirty();
  renderAll();
}

// ── entity + spawn editing ────────────────────────────────────────────────────

function wireEntityEditor() {
  if ($('game-entity-kind').__wired) return;
  $('game-entity-kind').__wired = true;
  $('game-entity-kind').addEventListener('change', (e) => {
    const entities = activeMap().entities;
    const ent = entities[state.activeEntityIndex];
    if (!ent) return;
    ent.kind = e.target.value;
    if (ent.kind !== 'static') { delete ent.col; delete ent.row; }
    markDirty(); renderAll();
  });
  $('game-entity-id').addEventListener('change', (e) => {
    const entities = activeMap().entities;
    if (entities[state.activeEntityIndex]) { entities[state.activeEntityIndex].id = e.target.value.trim(); markDirty(); renderAll(); }
  });
  $('game-entity-event').addEventListener('change', (e) => {
    const entities = activeMap().entities;
    if (entities[state.activeEntityIndex]) { entities[state.activeEntityIndex].event = e.target.value; markDirty(); renderAll(); }
  });
  $('game-entity-col').addEventListener('change', (e) => {
    const entities = activeMap().entities;
    if (entities[state.activeEntityIndex]) { entities[state.activeEntityIndex].col = clampInt(e.target.value, 0, activeMap().cols - 1); markDirty(); renderAll(); }
  });
  $('game-entity-row').addEventListener('change', (e) => {
    const entities = activeMap().entities;
    if (entities[state.activeEntityIndex]) { entities[state.activeEntityIndex].row = clampInt(e.target.value, 0, activeMap().rows - 1); markDirty(); renderAll(); }
  });
  $('game-entity-vis').addEventListener('change', (e) => {
    const entities = activeMap().entities;
    if (entities[state.activeEntityIndex]) { entities[state.activeEntityIndex].visible_if = e.target.value.trim(); markDirty(); }
  });
  $('game-entity-interact').addEventListener('change', (e) => {
    const entities = activeMap().entities;
    if (entities[state.activeEntityIndex]) { entities[state.activeEntityIndex].interact_if = e.target.value.trim(); markDirty(); }
  });
  $('game-entity-attach').addEventListener('change', (e) => {
    const entities = activeMap().entities;
    if (entities[state.activeEntityIndex]) { entities[state.activeEntityIndex].attach = e.target.value.trim(); markDirty(); }
  });
  $('game-entity-delete').addEventListener('click', () => {
    const entities = activeMap().entities;
    if (state.activeEntityIndex !== null && entities[state.activeEntityIndex]) {
      entities.splice(state.activeEntityIndex, 1);
      state.activeEntityIndex = null;
      markDirty(); renderAll();
    }
  });
}

function clampInt(raw, lo, hi) {
  const v = Math.round(Number(raw));
  if (Number.isNaN(v)) return lo;
  return Math.max(lo, Math.min(hi, v));
}

function setStartMap(id) {
  if (!state.data.maps[id]) return;
  if (state.data.startMap === id) delete state.data.startMap;
  else state.data.startMap = id;
  markDirty();
  renderAll();
}

// ── tile editing ──────────────────────────────────────────────────────────────

function wireTileEditor() {
  if ($('game-tile-add').__wired) return;
  $('game-tile-add').__wired = true;
  $('game-tile-add').addEventListener('click', () => {
    const palette = activeMap().palette;
    let i = Object.keys(palette).length + 1;
    let id = `tile_${i}`;
    while (palette[id]) { i += 1; id = `tile_${i}`; }
    palette[id] = { image: 'asset/tile.png', traversable: true };
    state.activeTileId = id;
    markDirty(); renderAll();
  });
  $('game-tile-id').addEventListener('change', (e) => renameActiveTile(e.target.value.trim()));
  $('game-tile-image').addEventListener('change', (e) => {
    const entry = activeMap().palette[state.activeTileId];
    if (entry) { entry.image = e.target.value.trim() || entry.image; markDirty(); renderAll(); }
  });
  $('game-tile-trav').addEventListener('change', (e) => {
    const entry = activeMap().palette[state.activeTileId];
    if (entry) { entry.traversable = e.target.checked; markDirty(); renderAll(); }
  });
}

function renameActiveTile(newId) {
  if (!newId) return;
  const palette = activeMap().palette;
  if (palette[newId] || newId === state.activeTileId) { renderTileEditor(); return; }
  palette[newId] = palette[state.activeTileId];
  delete palette[state.activeTileId];
  activeMap().tiles = activeMap().tiles.map((t) => (t === state.activeTileId ? newId : t));
  state.activeTileId = newId;
  markDirty(); renderAll();
}

// ── chrome ────────────────────────────────────────────────────────────────────

function wireGameChrome() {
  // tool tabs
  document.querySelectorAll('.game-map-tab').forEach((btn) => {
    if (btn.__wired) return;
    btn.__wired = true;
    btn.addEventListener('click', () => {
      state.tool = btn.dataset.tool;
      renderToolTabs();
    });
  });

  // canvas interactions
  const canvas = $('game-map-canvas');
  if (!canvas.__wired) {
    canvas.__wired = true;
    canvas.addEventListener('pointerdown', (ev) => {
      const cell = cellFromEvent(ev);
      if (!cell) return;
      if (ev.button === 2) { pickTileAt(cell.col, cell.row); return; }
      paintAt(cell.col, cell.row);
      const move = (e) => { const c = cellFromEvent(e); if (c) paintAt(c.col, c.row); };
      const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
    canvas.addEventListener('contextmenu', (ev) => ev.preventDefault());
  }

  $('game-map-zoom-in').onclick = () => { state.cellSize = Math.min(64, state.cellSize + 8); renderAll(); };
  $('game-map-zoom-out').onclick = () => { state.cellSize = Math.max(16, state.cellSize - 8); renderAll(); };

  $('game-map-add').onclick = () => {
    const id = prompt('Map id (lowercase, no spaces)', 'wastes');
    if (!id) return;
    if (state.data.maps[id]) { alert('That map id already exists.'); return; }
    state.data.maps[id] = defaultMap(id);
    state.activeMapId = id;
    if (!state.data.startMap) state.data.startMap = id;
    markDirty(); renderAll();
  };

  $('game-entity-add').onclick = () => { state.tool = 'entities'; state.activeEntityIndex = null; renderToolTabs(); };

  [['up', 'game-spawn-up'], ['down', 'game-spawn-down'], ['left', 'game-spawn-left'], ['right', 'game-spawn-right']].forEach(([facing, id]) => {
    $(id).onclick = () => { activeMap().spawn.facing = facing; markDirty(); renderAll(); };
  });

  wireEntityEditor();
  wireTileEditor();

  $('game-save').onclick = () => saveAll();
  $('game-validate').onclick = () => validateBuild();
  $('game-export').onclick = () => exportBuild();

  document.querySelectorAll('.game-tab').forEach((tab) => {
    if (tab.__wired) return;
    tab.__wired = true;
    tab.addEventListener('click', () => {
      document.querySelectorAll('.game-tab').forEach((t) => t.classList.toggle('active', t === tab));
      const isMap = tab.dataset.tab === 'map';
      $('game-map-pane').hidden = !isMap;
      $('game-vars-pane').hidden = isMap;
      $('game-inspector-body').innerHTML = isMap
        ? '<div class="empty-hint">Paint tiles · place entities · set spawn.</div>'
        : '<div class="empty-hint">Edit the registry rows on the left. Name, type, default, description.</div>';
    });
  });

  window.addEventListener('keydown', (ev) => {
    if ($('game-shell').hidden) return;
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 's') { ev.preventDefault(); saveAll(); }
    if (ev.key === 'Escape') { state.activeEntityIndex = null; renderAll(); }
  });
}

function renderToolTabs() {
  document.querySelectorAll('.game-map-tab').forEach((b) => b.classList.toggle('active', b.dataset.tool === state.tool));
  $('game-tool-tiles').hidden = state.tool !== 'tiles';
  $('game-tool-entities').hidden = state.tool !== 'entities';
  $('game-tool-spawn').hidden = state.tool !== 'spawn';
}

async function validateBuild() {
  flashStatus('building…', 'chip subtle');
  await saveAll();
  const res = await fetch(`/api/projects/${state.project.slug}/export?format=game`);
  const body = await res.text();
  if (!res.ok) {
    try {
      const report = JSON.parse(body);
      console.warn('build errors', report.errors, report.warnings);
      flashStatus(`✕ ${report.errors?.length ?? 1} error(s) — see console`, 'chip');
    } catch {
      flashStatus('✕ build failed — see console', 'chip');
    }
    return;
  }
  flashStatus('✓ build ok', 'chip');
}

async function exportBuild() {
  const ok = await saveAll();
  if (ok) window.location = `/api/projects/${state.project.slug}/export?format=game`;
}

// ── variables registry ─────────────────────────────────────────────────────

let registryLoaded = false;

async function loadVariablesEditor() {
  if (registryLoaded) return;
  registryLoaded = true;
  try {
    const text = await fetch(`/api/projects/${state.project.slug}/worldfile/variables.json`).then((r) => (r.ok ? r.text() : '{"variables": []}'));
    const raw = JSON.parse(text);
    $('game-vars-tbody').innerHTML = '';
    for (const entry of raw.variables ?? []) addVariableRow(entry);
  } catch (e) {
    console.warn('variables.json not readable', e);
  }
}

function addVariableRow(entry = null) {
  const tbody = $('game-vars-tbody');
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input class="gv-name" value="${entry?.name ?? ''}" placeholder="name"></td>
    <td><select class="gv-type"><option>string</option><option>number</option><option>boolean</option></select></td>
    <td><input class="gv-default" value="${entry ? String(entry.default) : ''}" placeholder="default"></td>
    <td><input class="gv-desc" value="${escapeHtml(entry?.desc ?? '')}" placeholder="description"></td>
    <td><button class="btn tiny ghost gv-remove" title="remove">✕</button></td>`;
  row.querySelector('.gv-type').value = entry?.type ?? 'string';
  row.querySelector('.gv-remove').addEventListener('click', () => { row.remove(); markDirty(); });
  row.querySelectorAll('input, select').forEach((el) => el.addEventListener('change', markDirty));
  tbody.appendChild(row);
  markDirty();
}

export function collectVariables() {
  const rows = [...$('game-vars-tbody').querySelectorAll('tr')];
  const variables = [];
  for (const row of rows) {
    const name = row.querySelector('.gv-name').value.trim();
    if (!name) continue;
    const type = row.querySelector('.gv-type').value;
    const desc = row.querySelector('.gv-desc').value;
    const defRaw = row.querySelector('.gv-default').value.trim();
    let def = parsePrimitive(defRaw);
    if (defRaw === '') def = type === 'boolean' ? false : type === 'number' ? 0 : '';
    variables.push({ name, type, default: def, desc });
  }
  return { variables };
}

export async function saveVariablesRegistry() {
  const payload = JSON.stringify(collectVariables(), null, 2) + '\n';
  const res = await fetch(`/api/projects/${state.project.slug}/worldfile/variables.json`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: payload }),
  });
  return res.ok;
}

function parsePrimitive(raw) {
  const t = String(raw).trim();
  if (t === 'true') return true;
  if (t === 'false') return false;
  if (t !== '' && !Number.isNaN(Number(t))) return Number(t);
  return t;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

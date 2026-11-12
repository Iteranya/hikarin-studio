/* Hikarin Studio — Game editor.
 *
 * The game editor is what you see when the open project has kind === "game":
 * a node canvas (Route A full), a world-variable registry table, and an
 * export path straight to `build/game.json`. Events are nested hikarin
 * story projects — they are edited in the story editor as usual; this file
 * is only the world glue.
 *
 * State:
 *   file:      currently open .orch (name only, world/ scope)
 *   graph:     { kind, start, nodes: [...], wires: [...] }
 *   selection: { id } | { wire: index } | null
 *   transform: { x, y, zoom }
 *   dirty:     boolean
 *
 * Round-trip rule: node ids and `at` coordinates are preserved verbatim; the
 * compiler in hikarin/orchestrator.py canonicalises order and resolves ids.
 */



const $ = (id) => document.getElementById(id);

const state = {
  project: null,          // { slug, meta }
  worldFiles: [],
  events: [],
  file: null,
  graph: null,
  selection: null,
  transform: { x: 80, y: 40, zoom: 1 },
  dirty: false,
  drag: null,             // active drag session
  pendingWire: null,      // { from: [node, socket], mouse: {x,y} }
  pan: null,
  undo: [],
  builtOnce: false,
};

// ── lifecycle ───────────────────────────────────────────────────────────────

export async function openGameEditor(project) {
  state.project = project;
  state.dirty = false;
  state.selection = null;
  state.builtOnce = false;
  registryLoaded = false;          // registry must reload with each project
  $('game-vars-tbody').innerHTML = '';
  $('game-build-status').textContent = 'not built';
  $('game-build-status').className = 'chip subtle';

  const world = await fetch(`/api/projects/${project.slug}/world`).then((r) => r.json());
  state.worldFiles = world.worldFiles ?? [];
  state.events = world.events ?? [];

  // Pick the first .orch available (map.orch by convention).
  const target = state.worldFiles.find((f) => f.endsWith('.orch')) ?? state.worldFiles.find((f) => f === 'map.orch') ?? state.worldFiles[0];
  $('game-orch-pick').value = target ?? '(no world files)';
  if (!target) {
    $('game-nodes').innerHTML = '';
    return;
  }
  await openOrchFile(target);
  wireGameChrome();
}

export function closeGameEditor() {
  $('game-shell').hidden = true;
}

async function openOrchFile(name) {
  state.file = name;
  $('game-orch-pick').value = name;
  const raw = await fetch(`/api/projects/${state.project.slug}/worldfile/${name}`).then((r) => {
    if (!r.ok) throw new Error('worldfile read failed');
    return r.text();
  });
  state.graph = JSON.parse(raw);
  state.dirty = false;
  state.selection = null;
  fitToContent(false); // silent initial fit but don't move
  if (state.graph.nodes.length) fitToContent(true);
  renderAll();
}

// ── save / validate / export ────────────────────────────────────────────────

async function saveWorldFile() {
  if (!state.graph) return;
  state.graph.start = state.graph.nodes.find((n) => n.verb === 'meta')?.id ?? state.graph.start;
  const payload = JSON.stringify(state.graph, null, 2) + '\n';
  const [res] = await Promise.all([
    fetch(`/api/projects/${state.project.slug}/worldfile/${state.file}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: payload }),
    }),
    saveVariablesRegistry(),
  ]);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    flashStatus(`✕ ${err.detail ?? 'save failed'}`, 'chip');
    return false;
  }
  state.dirty = false;
  flashStatus('saved', 'chip subtle');
  return true;
}

async function validateBuild() {
  flashStatus('building…', 'chip subtle');
  await saveWorldFile();
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
  await saveWorldFile();
  window.location = `/api/projects/${state.project.slug}/export?format=game`;
}

function flashStatus(text, cls) {
  const el = $('game-build-status');
  el.textContent = text;
  el.className = cls;
}

// ── nodes ──────────────────────────────────────────────────────────────────

const NODE_WIDTH = 200;

function nodeHeight(n) {
  const rows = Object.keys(fieldsFor(n)).length;
  return 34 /* header */ + rows * 24 /* rows */ + 14 /* padding */
    + (n.verb === 'conditional' ? 34 : 0) /* true/false labels */;
}

function familyOf(verb) {
  switch (verb) {
    case 'meta': case 'label': case 'jump': case 'conditional': return 'flow';
    case 'map': case 'entity': return 'world';
    case 'run_event': return 'event';
    case 'set_world': case 'save': return 'state';
    case 'ending': return 'end';
    default: return 'flow';
  }
}

function fieldsFor(n) {
  const f = n.fields ?? {};
  switch (n.verb) {
    case 'meta':        return {};
    case 'label':       return { label: f.label ?? '' };
    case 'jump':        return { label: f.label ?? '' };
    case 'conditional': return { condition: f.condition ?? 'equal', var: f.var ?? '', value: f.value ?? '' };
    case 'map':         return { map: f.map ?? '', x: f.x ?? 0, y: f.y ?? 0 };
    case 'entity':      return { entity: f.entity ?? '' };
    case 'run_event':   return { event: f.event ?? '' };
    case 'set_world':   return { var: f.var ?? '', value: f.value ?? '' };
    case 'save':        return {};
    case 'ending':      return {};
    default:            return {};
  }
}

const VERB_HINT = {
  meta: 'Entry point. Exactly one per game.',
  label: 'Label target for jumps.',
  jump: 'Unconditional control transfer.',
  conditional: 'Route selector: picks which event to dispatch. Blocking lives inside the event.',
  map: 'Load a map by id; x/y = player cell.',
  entity: 'Arm an interact handoff.',
  run_event: 'Run a compiled event (hikarin spine). The orchestrator resumes when it returns.',
  set_world: 'Write @world.* — the only world mutation channel.',
  save: 'Flush the profile now.',
  ending: 'Terminal. Engine halts.',
};

function addNode(verb, at = null) {
  const id = freshNodeId();
  const node = {
    id,
    verb,
    fields: defaultFields(verb),
    at: at ?? [Math.round((-state.transform.x + 200) / state.transform.zoom), Math.round((-state.transform.y + 120) / state.transform.zoom)],
  };
  state.graph.nodes.push(node);
  if (verb === 'meta') state.graph.start = id;
  selectNode(id);
  renderAll();
  markDirty();
}

function freshNodeId() {
  let n = Date.now().toString(36).slice(-4);
  while (state.graph?.nodes.some((x) => x.id === `n_${n}`)) n = ((Math.random() * 0xffff) | 0).toString(16);
  return `n_${n}`;
}

function defaultFields(verb) {
  switch (verb) {
    case 'label': return { label: '' };
    case 'jump': return { label: '' };
    case 'conditional': return { condition: 'equal', var: '@world.', value: '' };
    case 'map': return { map: '', x: 0, y: 0 };
    case 'entity': return { entity: '' };
    case 'run_event': return { event: state.events?.[0] ?? '' };
    case 'set_world': return { var: '@world.', value: 'true' };
    default: return {};
  }
}

function deleteNode(id) {
  state.graph.nodes = state.graph.nodes.filter((n) => n.id !== id);
  state.graph.wires = state.graph.wires.filter((w) => w.from[0] !== id && w.to[0] !== id);
  if (state.selection?.id === id) state.selection = null;
  renderAll();
  markDirty();
}

function renderAll() {
  renderNodes();
  renderWires();
  renderInspector();
  $('game-vars-count').textContent = `${$('game-vars-tbody').children.length} declared`;
}

function renderNodes() {
  const layer = $('game-nodes');
  layer.innerHTML = '';
  for (const n of state.graph.nodes) {
    const el = document.createElement('div');
    el.className = `game-node fam-${familyOf(n.verb)}${isSelected(n) ? ' selected' : ''}`;
    el.style.left = `${n.at[0]}px`;
    el.style.top = `${n.at[1]}px`;
    el.dataset.id = n.id;
    el.innerHTML = `
      <div class="game-node-head"><span class="game-node-verb">${verbLabel(n.verb)}</span><span class="game-node-badge">${n.id}</span></div>
      <div class="game-node-body">${bodyHtml(n)}</div>
      <div class="game-node-sockets">${socketsHtml(n)}</div>`;
    layer.appendChild(el);
    wireNodeEvents(el, n);
  }
}

function verbLabel(verb) {
  return {
    meta: 'Meta · start',
    label: 'Label',
    jump: 'Jump',
    conditional: 'If',
    map: 'Load map',
    entity: 'Entity',
    run_event: 'Run event',
    set_world: 'Set world',
    save: 'Save',
    ending: 'Ending',
  }[verb] ?? verb;
}

function bodyHtml(n) {
  const fields = fieldsFor(n);
  const rows = [];
  for (const [key, value] of Object.entries(fields)) {
    rows.push(`<div class="game-node-row"><label>${key}</label><div class="game-node-field" data-key="${key}">${escapeHtml(String(value))}</div></div>`);
  }
  return rows.join('') || '<div class="game-node-row"><span class="game-field-hint">no fields</span></div>';
}

function socketsHtml(n) {
  const out = [];
  if (n.verb === 'conditional') {
    out.push(`<div class="game-port out true" data-port="true" title="condition true"></div><div class="game-port-label">true</div>`);
    out.push(`<div class="game-port out false" data-port="false" title="condition false"></div><div class="game-port-label false">false</div>`);
  } else if (n.verb !== 'jump' && n.verb !== 'ending') {
    out.push(`<div class="game-port out" data-port="out" title="continue"></div>`);
  }
  if (n.verb !== 'meta') out.push(`<div class="game-port in" data-port="in" title="input"></div>`);
  return out.join('');
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

function isSelected(n) {
  return state.selection && state.selection.id === n.id;
}

function selectNode(id) {
  state.selection = { id };
  renderAll();
}

function wireNodeEvents(el, n) {
  el.addEventListener('pointerdown', (ev) => {
    if (ev.target.closest('.game-port')) return;
    ev.preventDefault();
    selectNode(n.id);
    const startX = ev.clientX, startY = ev.clientY;
    const originX = n.at[0], originY = n.at[1];
    const move = (e) => {
      const dx = (e.clientX - startX) / state.transform.zoom;
      const dy = (e.clientY - startY) / state.transform.zoom;
      n.at = [Math.round(originX + dx), Math.round(originY + dy)];
      el.style.left = `${n.at[0]}px`;
      el.style.top = `${n.at[1]}px`;
      renderWires();
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      markDirty();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });

  el.querySelectorAll('.game-port').forEach((port) => {
    port.addEventListener('pointerdown', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const socket = port.dataset.port;
      const isOut = port.classList.contains('out');
      if (!isOut) return; // wires start from outlets only
      state.pendingWire = { from: [n.id, socket], mouse: { x: ev.clientX, y: ev.clientY } };
      $('game-canvas').classList.add('wiring');
      const move = (e) => {
        state.pendingWire.mouse = { x: e.clientX, y: e.clientY };
        renderWires();
      };
      const up = (e) => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        $('game-canvas').classList.remove('wiring');
        const target = document.elementFromPoint(e.clientX, e.clientY)?.closest?.('.game-port.in');
        if (target) {
          const targetNodeEl = target.closest('.game-node');
          const targetNodeId = targetNodeEl?.dataset.id;
          if (targetNodeId && targetNodeId !== n.id) {
            state.graph.wires.push({ from: [n.id, socket], to: [targetNodeId, 'in'] });
            markDirty();
          }
        }
        state.pendingWire = null;
        renderAll();
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
  });
}

// ── wires ───────────────────────────────────────────────────────────────────

function portWorldPosition(nodeId, socket) {
  const n = state.graph.nodes.find((x) => x.id === nodeId);
  if (!n) return { x: 0, y: 0 };
  const el = $('game-nodes').querySelector(`[data-id="${nodeId}"]`);
  const baseY = n.at[1];
  if (!el) return { x: n.at[0] + NODE_WIDTH, y: baseY };
  const port = el.querySelector(`.game-port[data-port="${socket}"]`);
  if (!port) return { x: n.at[0] + NODE_WIDTH, y: baseY };
  return { x: n.at[0] + port.offsetLeft + 6, y: n.at[1] + port.offsetTop + 6 };
}

function renderWires() {
  const svg = $('game-wires');
  const wires = state.graph.wires.map((w, i) => ({ w, i }));
  const parts = [];
  for (const { w, i } of wires) {
    const from = portWorldPosition(w.from[0], w.from[1]);
    const to = portWorldPosition(w.to[0], 'in');
    const mid = Math.max(40, Math.abs(to.x - from.x) / 2);
    const d = `M ${from.x} ${from.y} C ${from.x + mid} ${from.y}, ${to.x - mid} ${to.y}, ${to.x} ${to.y}`;
    const sel = state.selection?.wire === i ? ' selected' : '';
    parts.push(`<path class="game-wire${sel}" data-index="${i}" d="${d}"/>`);
  }
  if (state.pendingWire) {
    const from = portWorldPosition(state.pendingWire.from[0], state.pendingWire.from[1]);
    const mouse = screenToWorld(state.pendingWire.mouse.x, state.pendingWire.mouse.y);
    const mid = Math.max(40, Math.abs(mouse.x - from.x) / 2);
    const d = `M ${from.x} ${from.y} C ${from.x + mid} ${from.y}, ${mouse.x - mid} ${mouse.y}, ${mouse.x} ${mouse.y}`;
    parts.push(`<path class="game-wire pending" d="${d}"/>`);
  }
  svg.innerHTML = parts.join('');
  svg.querySelectorAll('.game-wire[data-index]').forEach((p) => {
    p.addEventListener('pointerdown', (ev) => {
      ev.stopPropagation();
      const i = Number(p.dataset.index);
      state.selection = { wire: i };
      renderAll();
    });
  });
}

function screenToWorld(clientX, clientY) {
  const rect = $('game-canvas').getBoundingClientRect();
  return {
    x: (clientX - rect.left - state.transform.x) / state.transform.zoom,
    y: (clientY - rect.top - state.transform.y) / state.transform.zoom,
  };
}

// ── inspector ───────────────────────────────────────────────────────────────

function renderInspector() {
  const body = $('game-inspector-body');
  const selection = state.selection;
  if (selection && selection.id != null) {
    const n = state.graph.nodes.find((x) => x.id === selection.id);
    if (!n) { body.innerHTML = '<div class="empty-hint">Node gone.</div>'; return; }
    body.innerHTML = inspectorHtml(n);
    wireInspector(body, n);
    return;
  }
  if (selection && selection.wire != null) {
    body.innerHTML = `<div class="empty-hint">Wire selected — press Delete to remove.</div>`;
    return;
  }
  body.innerHTML = '<div class="empty-hint">Select a node to edit it.</div>';
}

function inspectorHtml(n) {
  const fields = fieldsFor(n);
  const rows = [];
  for (const [key, value] of Object.entries(fields)) {
    if (n.verb === 'conditional' && key === 'condition') {
      rows.push(`<div class="game-field"><label>condition</label>
        <select data-field="condition">${CONDITION_OPTIONS.map((c) => `<option value="${c}"${value === c ? ' selected' : ''}>${c}</option>`).join('')}</select></div>`);
    } else {
      rows.push(`<div class="game-field"><label>${key}</label><input data-field="${key}" value="${escapeHtml(String(value))}"></div>`);
    }
  }
  rows.push(`<div class="game-field-hint">${VERB_HINT[n.verb] ?? ''}</div>`);
  rows.push(`<button class="game-node-delete" id="game-delete-node">Delete node</button>`);
  return rows.join('');
}

const CONDITION_OPTIONS = ['equal', 'not_equal', 'greater_than', 'less_than', 'greater_or_equal', 'less_or_equal', 'exists', 'not_exists', 'day', 'night'];

function wireInspector(body, n) {
  body.querySelectorAll('[data-field]').forEach((input) => {
    const key = input.dataset.field;
    input.addEventListener('change', () => {
      let value = input.value;
      if (key === 'x' || key === 'y') value = Number(value) || 0;
      if (n.verb === 'set_world' && key === 'value') value = parsePrimitive(value);
      n.fields[key] = value;
      markDirty();
      renderAll();
    });
  });
  body.querySelector('#game-delete-node')?.addEventListener('click', () => deleteNode(n.id));
}

function parsePrimitive(raw) {
  const t = String(raw).trim();
  if (t === 'true') return true;
  if (t === 'false') return false;
  if (t !== '' && !Number.isNaN(Number(t))) return Number(t);
  return t;
}

function markDirty() {
  state.dirty = true;
  $('game-build-status').textContent = 'unsaved';
  $('game-build-status').className = 'chip';
}

// ── canvas chrome ───────────────────────────────────────────────────────────

function wireGameChrome() {
  const canvas = $('game-canvas');

  $('game-save').onclick = () => saveWorldFile();
  $('game-validate').onclick = () => validateBuild();
  $('game-export').onclick = () => exportBuild();

  $('game-zoom-in').onclick = () => zoomBy(1.2);
  $('game-zoom-out').onclick = () => zoomBy(1 / 1.2);
  $('game-zoom-fit').onclick = () => fitToContent(true);

  $('game-add-node').addEventListener('change', (ev) => {
    const verb = ev.target.value;
    if (verb) addNode(verb);
    ev.target.value = '';
  });

  // tab switching
  document.querySelectorAll('.game-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.game-tab').forEach((t) => t.classList.toggle('active', t === tab));
      $('game-flow-pane').hidden = tab.dataset.tab !== 'flow';
      $('game-vars-pane').hidden = tab.dataset.tab !== 'vars';
      $('game-inspector-body').innerHTML = tab.dataset.tab === 'vars'
        ? '<div class="empty-hint">Edit the registry rows on the left. Name, type, default, description.</div>'
        : '<div class="empty-hint">Select a node to edit it.</div>';
    });
  });

  // variables table
  $('game-vars-add').addEventListener('click', () => addVariableRow());
  loadVariablesEditor();

  // canvas interactions
  canvas.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    zoomBy(ev.deltaY < 0 ? 1.1 : 1 / 1.1, { x: ev.clientX, y: ev.clientY });
  }, { passive: false });

  canvas.addEventListener('pointerdown', (ev) => {
    const onNode = ev.target.closest('.game-node');
    const onPort = ev.target.closest('.game-port');
    const onStage = !onNode && !onPort;
    if (ev.button === 1 || ev.button === 2 || (ev.button === 0 && onStage && ev.target.closest('.game-wires'))) {
      startPan(ev);
    } else if (ev.button === 0 && onStage) {
      // click empty canvas: clear selection
      state.selection = null;
      renderAll();
      startPan(ev);
    }
  });

  canvas.addEventListener('contextmenu', (ev) => ev.preventDefault());

  window.addEventListener('keydown', (ev) => {
    if ($('game-shell').hidden) return;
    const targetIsInput = ev.target.closest?.('input, textarea, select');
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 's') {
      ev.preventDefault();
      saveWorldFile();
    }
    if (targetIsInput) return;
    if (ev.key === 'Delete' || ev.key === 'Backspace') {
      ev.preventDefault();
      if (state.selection?.id != null) deleteNode(state.selection.id);
      else if (state.selection?.wire != null) {
        state.graph.wires.splice(state.selection.wire, 1);
        state.selection = null;
        renderAll();
        markDirty();
      }
    }
    if (ev.key === 'f' && !ev.ctrlKey && !ev.metaKey) fitToContent(true);
  });
}

function startPan(ev) {
  ev.preventDefault();
  $('game-canvas').classList.add('panning');
  const sx = ev.clientX, sy = ev.clientY;
  const tx = state.transform.x, ty = state.transform.y;
  const move = (e) => {
    state.transform.x = tx + (e.clientX - sx);
    state.transform.y = ty + (e.clientY - sy);
    applyTransform();
  };
  const up = () => {
    $('game-canvas').classList.remove('panning');
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

function applyTransform() {
  const t = state.transform;
  $('game-world').style.transform = `translate(${t.x}px, ${t.y}px) scale(${t.zoom})`;
  $('game-zoom-label').textContent = `${Math.round(t.zoom * 100)}%`;
  const canvas = $('game-canvas');
  canvas.style.backgroundPosition = `${t.x}px ${t.y}px`;
  canvas.style.backgroundSize = `${24 * t.zoom}px ${24 * t.zoom}px`;
}

function zoomBy(factor, anchor = null) {
  const t = state.transform;
  const rect = $('game-canvas').getBoundingClientRect();
  const ax = anchor ? anchor.x - rect.left : rect.width / 2;
  const ay = anchor ? anchor.y - rect.top : rect.height / 2;
  const before = screenToWorld(rect.left + ax, rect.top + ay);
  t.zoom = Math.min(2, Math.max(0.25, t.zoom * factor));
  t.x = ax - before.x * t.zoom;
  t.y = ay - before.y * t.zoom;
  applyTransform();
}

function fitToContent(animate) {
  if (!state.graph?.nodes.length) {
    applyTransform();
    return;
  }
  const pad = 60;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of state.graph.nodes) {
    minX = Math.min(minX, n.at[0]);
    minY = Math.min(minY, n.at[1]);
    maxX = Math.max(maxX, n.at[0] + NODE_WIDTH);
    maxY = Math.max(maxY, n.at[1] + nodeHeight(n));
  }
  const rect = $('game-canvas').getBoundingClientRect();
  const w = maxX - minX + pad * 2, h = maxY - minY + pad * 2;
  const zoom = Math.min(2, Math.max(0.25, Math.min(rect.width / w, rect.height / h)));
  state.transform = {
    zoom,
    x: (rect.width - w * zoom) / 2 - minX * zoom + pad * zoom,
    y: (rect.height - h * zoom) / 2 - minY * zoom + pad * zoom,
  };
  applyTransform();
}

// ── variables registry editor ───────────────────────────────────────────────

let registryLoaded = false;

async function loadVariablesEditor() {
  if (registryLoaded) return;
  registryLoaded = true;
  try {
    const text = await fetch(`/api/projects/${state.project.slug}/worldfile/variables.json`).then((r) => (r.ok ? r.text() : '{"variables": []}'));
    const raw = JSON.parse(text);
    const entries = raw.variables ?? [];
    $('game-vars-tbody').innerHTML = '';
    for (const entry of entries) addVariableRow(entry);
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

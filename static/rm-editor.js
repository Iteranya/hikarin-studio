/* Hikarin Studio — resource management designer.
 *
 * One schema, edited as primitives. Nothing in this file knows what a "Tower"
 * or a "waifu" is — resources, generators, converters, assignables, nodes,
 * events and tech nodes are all the runtime needs. The VN seam is a Resource
 * flagged visible_to_vn: the backend syncs it into the variables registry, so
 * the story editor sees it as an ordinary global.
 *
 * Editing mutates state.schema in place (autosave flushes it); structural edits
 * (add/duplicate/delete/reorder) re-render the panes.
 */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const TABS = [
  { key: 'resources', label: 'Resources' },
  { key: 'generators', label: 'Generators' },
  { key: 'converters', label: 'Converters' },
  { key: 'nodes', label: 'Nodes' },
  { key: 'tech_nodes', label: 'Tech Tree' },
  { key: 'events', label: 'Events' },
  { key: 'assignables', label: 'Assignables' },
  { key: 'settings', label: 'Settings' },
];
const COLLECTIONS = TABS.filter((t) => t.key !== 'settings').map((t) => t.key);

const REQ_TYPES = ['resource', 'tag', 'tech', 'generator_level', 'flag', 'assignable', 'time', 'custom'];
const EFFECT_TYPES = ['add_resource', 'multiply_output', 'unlock', 'set_flag', 'add_tag', 'trigger_event', 'custom'];
const NODE_TYPES = ['expedition', 'encounter', 'location', 'story', 'trade'];
const SOURCE_TYPES = ['manual', 'vn_character', 'procedural'];

const state = {
  project: null,
  schema: null,
  problems: [],
  dirty: false,
  saving: false,
  activeTab: 'resources',
  selected: null,
  stories: [],
  saveTimer: null,
};

function emptySchema() {
  return {
    version: 1,
    tick_rate_hz: 1,
    max_offline_hours: 24,
    resources: [],
    generators: [],
    converters: [],
    nodes: [],
    tech_nodes: [],
    events: [],
    assignables: [],
  };
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
    else if (k === 'style') Object.assign(node.style, v);
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

function toast(message, kind = 'ok') {
  const t = el('div', { class: `rm-toast ${kind}`, text: message });
  $('body').append(t);
  setTimeout(() => t.remove(), kind === 'error' ? 6000 : 2500);
}

function markDirty() {
  state.dirty = true;
  renderStatus();
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => save(true), 1200);
}

async function save(silent = false) {
  if (state.saving || !state.dirty) return;
  if ($('.json-bad')) { toast('A JSON field is malformed — fix it before saving.', 'error'); return; }
  state.saving = true;
  renderStatus('saving…');
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(state.project)}/resource-management`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: state.schema }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      toast(err.detail || 'Save failed', 'error');
      renderStatus('save failed');
      return;
    }
    const body = await res.json();
    state.schema = body.schema;
    state.problems = body.problems || [];
    state.dirty = false;
    renderTabs();
    renderProblems();
    renderStatus(silent ? 'autosaved' : 'saved');
    if (!silent) toast('Saved');
  } catch (e) {
    toast(`Save failed — ${e.message || e}`, 'error');
    renderStatus('save failed');
  } finally {
    state.saving = false;
  }
}

async function validateNow() {
  const res = await fetch(`/api/projects/${encodeURIComponent(state.project)}/resource-management/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data: state.schema }),
  });
  const body = await res.json();
  state.problems = body.problems || [];
  renderProblems();
  if (body.ok) toast('Schema valid');
  else toast(`${state.problems.filter((p) => !p.includes('(warning)')).length} error(s) found`, 'error');
}

async function exportKit() {
  const res = await fetch(`/api/projects/${encodeURIComponent(state.project)}/export?format=rmkit`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    toast(err.detail || 'Export failed', 'error');
    return;
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const match = cd.match(/filename="?([^";]+)"?/);
  const url = URL.createObjectURL(blob);
  const a = el('a', { href: url, download: match ? match[1] : 'resource-management.rmkit.zip' });
  $('body').append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function renderStatus(text) {
  const pill = $('#rm-status');
  const problems = state.problems || [];
  const hard = problems.filter((p) => !p.includes('(warning)'));
  if (state.dirty) { pill.textContent = text || 'editing…'; pill.className = 'chip warn'; return; }
  if (hard.length) { pill.textContent = `${hard.length} error${hard.length > 1 ? 's' : ''}`; pill.className = 'chip error'; return; }
  if (problems.length) { pill.textContent = `${problems.length} warning${problems.length > 1 ? 's' : ''}`; pill.className = 'chip warn'; return; }
  pill.textContent = text || `clean · v${state.schema?.version ?? 1}`;
  pill.className = 'chip ok';
}

function renderProblems() {
  const box = $('#rm-problems');
  const problems = state.problems || [];
  box.innerHTML = '';
  if (!problems.length) { box.hidden = true; return; }
  box.hidden = false;
  const hard = problems.filter((p) => !p.includes('(warning)'));
  const warns = problems.filter((p) => p.includes('(warning)'));
  if (hard.length) box.append(el('div', { class: 'p-error', text: `${hard.length} error(s):` }));
  if (warns.length) box.append(el('div', { class: 'p-warn', text: `${warns.length} warning(s):` }));
  const ul = el('ul');
  for (const p of problems) {
    ul.append(el('li', { class: p.includes('(warning)') ? 'p-warn' : 'p-error', text: p.replace(/\s*\(warning\)\s*$/, '') }));
  }
  box.append(ul);
}

function counts() {
  const s = state.schema;
  if (!s) return {};
  return {
    resources: s.resources.length,
    generators: s.generators.length,
    converters: s.converters.length,
    nodes: s.nodes.length,
    tech_nodes: s.tech_nodes.length,
    events: s.events.length,
    assignables: s.assignables.length,
  };
}

function renderTabs() {
  const nav = $('#rm-tabs');
  nav.innerHTML = '';
  const c = counts();
  for (const tab of TABS) {
    const count = tab.key === 'settings' ? '' : `<span class="count">${c[tab.key] ?? 0}</span>`;
    const btn = el('button', {
      class: `rm-tab${state.activeTab === tab.key ? ' active' : ''}`,
      role: 'tab',
      html: `${tab.label}${count}`,
      onclick: () => { state.activeTab = tab.key; state.selected = null; renderAll(); },
    });
    nav.append(btn);
  }
  $('#rm-list-title').textContent = TABS.find((t) => t.key === state.activeTab)?.label ?? '';
}

function rebuildDatalists() {
  const s = state.schema;
  if (!s) return;
  const setOptions = (id, values) => {
    const dl = document.getElementById(id);
    if (!dl) return;
    dl.innerHTML = '';
    for (const v of [...new Set(values)].sort()) dl.append(el('option', { value: v }));
  };
  setOptions('rm-resource-ids', s.resources.map((r) => r.id));
  setOptions('rm-assignable-ids', s.assignables.map((a) => a.id));
  const tags = new Set();
  for (const a of s.assignables) for (const t of a.tags || []) tags.add(t);
  for (const g of s.generators) for (const t of Object.keys(g.assignment_bonuses || {})) tags.add(t);
  for (const c of s.converters) for (const t of Object.keys(c.assignment_bonuses || {})) tags.add(t);
  setOptions('rm-tag-names', [...tags]);
  setOptions('rm-node-ids', s.nodes.map((n) => n.id));
  setOptions('rm-event-ids', s.events.map((e) => e.id));
  setOptions('rm-tech-ids', s.tech_nodes.map((t) => t.id));
  setOptions('rm-story-slugs', state.stories);
}

function currentCollection() {
  return state.schema[state.activeTab] ?? null;
}

/** Keep a valid selection for the active collection — tab switches blank it. */
function ensureSelection() {
  if (state.activeTab === 'settings' || !state.schema) return;
  const coll = currentCollection();
  if (!coll) { state.selected = null; return; }
  if (!state.selected || !coll.some((i) => i.id === state.selected)) {
    state.selected = coll.length ? coll[0].id : null;
  }
}

function renderList() {
  const list = $('#rm-list');
  list.innerHTML = '';
  const coll = currentCollection();
  if (!coll) return;
  const filter = ($('#rm-search').value || '').trim().toLowerCase();
  const shown = coll.filter((item) =>
    !filter || `${item.id} ${item.name ?? ''}`.toLowerCase().includes(filter));

  $('#rm-counts').textContent = `${coll.length} ${state.activeTab}`;

  if (!shown.length) {
    list.append(el('div', { class: 'manager-empty-note', text: coll.length ? 'Nothing matches the filter.' : 'No entries yet — press + Add.' }));
    return;
  }

  for (const item of shown) {
    const row = el('button', {
      class: `rm-row${state.selected === item.id ? ' active' : ''}`,
      onclick: () => { state.selected = item.id; renderAll(); },
    },
      el('span', { class: 'r-name', text: item.name || item.id }),
      el('span', { class: 'r-id', text: item.id }),
      el('span', { class: 'r-del', text: '✕', title: 'Delete', onclick: (e) => { e.stopPropagation(); deleteItem(item.id); } }));
    list.append(row);
  }
}

function uniqueId(base, coll) {
  let candidate = base;
  let n = 2;
  const taken = new Set(coll.map((i) => i.id));
  while (taken.has(candidate)) candidate = `${base}_${n++}`;
  return candidate;
}

function addItem() {
  const coll = currentCollection();
  if (!coll) return;
  const kind = state.activeTab.replace(/s$/, '');
  const item = { id: uniqueId(`new_${kind}`, coll), name: 'New entry' };
  if (state.activeTab === 'generators') Object.assign(item, { levels: [{ level: 1, cost: {}, output: {}, upkeep: {}, unlocks: [], requirements: [] }], slots: 1, assignment_bonuses: {} });
  if (state.activeTab === 'converters') Object.assign(item, { recipes: [], slots: 1, assignment_bonuses: {} });
  if (state.activeTab === 'resources') Object.assign(item, { base_cap: 999999, resource_type: 'integer', color: '#FFFFFF', icon: 'circle', visible_to_vn: false, vn_scope: 'GLOBAL', show_in_hud: false, format_string: '{value} {icon}' });
  if (state.activeTab === 'nodes') Object.assign(item, { node_type: 'expedition', duration: 0, rewards: {}, chance_rewards: [], event_pool: [], connects_to: [], requirements: [], x: 0, y: 0 });
  if (state.activeTab === 'tech_nodes') Object.assign(item, { cost: {}, unlocks: [], effects: [], requirements: [], x: 0, y: 0 });
  if (state.activeTab === 'events') Object.assign(item, { weight: 1.0, requirements: [], effects: [] });
  if (state.activeTab === 'assignables') Object.assign(item, { tags: [], base_stats: {}, source: 'manual' });
  coll.push(item);
  state.selected = item.id;
  markDirty();
  renderAll();
}

function duplicateItem(id) {
  const coll = currentCollection();
  const item = coll.find((i) => i.id === id);
  if (!item) return;
  const copy = JSON.parse(JSON.stringify(item));
  copy.id = uniqueId(`${id}_copy`, coll);
  copy.name = `${item.name || item.id} copy`;
  const idx = coll.findIndex((i) => i.id === id);
  coll.splice(idx + 1, 0, copy);
  state.selected = copy.id;
  markDirty();
  renderAll();
}

function deleteItem(id) {
  const coll = currentCollection();
  if (!coll) return;
  if (!confirm(`Delete ${id}? This cannot be undone.`)) return;
  const idx = coll.findIndex((i) => i.id === id);
  if (idx >= 0) coll.splice(idx, 1);
  if (state.selected === id) state.selected = null;
  markDirty();
  renderAll();
}

/* ── form field helpers ─────────────────────────────────────────────── */

function textField(label, value, { hint, onInput, list, pattern, width } = {}) {
  const input = el('input', { type: 'text', class: 'input', value: value ?? '', autocomplete: 'off' });
  if (list) input.setAttribute('list', list);
  if (pattern) input.setAttribute('pattern', pattern);
  if (width) input.style.width = width;
  input.addEventListener('input', () => onInput?.(input.value));
  const field = el('label', { class: 'field' }, el('span', { class: 'field-label', text: label }), input);
  if (hint) field.append(el('span', { class: 'field-hint', text: hint }));
  return field;
}

function numField(label, value, { hint, onInput, step = 'any', min } = {}) {
  const input = el('input', { type: 'number', class: 'input', value: value ?? 0, step });
  if (min !== undefined) input.min = min;
  input.addEventListener('input', () => { const v = parseFloat(input.value); onInput?.(Number.isFinite(v) ? v : 0); });
  const field = el('label', { class: 'field' }, el('span', { class: 'field-label', text: label }), input);
  if (hint) field.append(el('span', { class: 'field-hint', text: hint }));
  return field;
}

function selectField(label, value, options, { hint, onInput } = {}) {
  const select = el('select', { class: 'input' });
  for (const opt of options) {
    const o = el('option', { value: opt }, opt);
    if (opt === value) o.selected = true;
    select.append(o);
  }
  select.addEventListener('change', () => onInput?.(select.value));
  const field = el('label', { class: 'field' }, el('span', { class: 'field-label', text: label }), select);
  if (hint) field.append(el('span', { class: 'field-hint', text: hint }));
  return field;
}

function checkField(label, value, { hint, onInput } = {}) {
  const input = el('input', { type: 'checkbox', class: 'input', ...(value ? { checked: 'checked' } : {}) });
  if (value) input.checked = true;
  input.addEventListener('change', () => onInput?.(input.checked));
  const field = el('label', { class: 'field check-row' }, input, el('span', { class: 'field-label', text: label }));
  if (hint) field.append(el('span', { class: 'field-hint', text: hint }));
  return field;
}

function csvField(label, values, { hint, onInput, list } = {}) {
  const input = el('input', { type: 'text', class: 'input', value: (values || []).join(', '), autocomplete: 'off', placeholder: 'comma-separated' });
  if (list) input.setAttribute('list', list);
  input.addEventListener('input', () => {
    onInput?.(input.value.split(',').map((s) => s.trim()).filter(Boolean));
  });
  const field = el('label', { class: 'field' }, el('span', { class: 'field-label', text: label }), input);
  if (hint) field.append(el('span', { class: 'field-hint', text: hint }));
  return field;
}

function colorField(label, value, { onInput } = {}) {
  const input = el('input', { type: 'color', class: 'input', value: value || '#FFFFFF' });
  input.addEventListener('input', () => onInput?.(input.value));
  return el('label', { class: 'field' }, el('span', { class: 'field-label', text: label }), input);
}

/** Key→amount dict editor. Keys default to known resource ids via datalist. */
function kvEditor(title, obj, { keysList = 'rm-resource-ids', allowFreeKeys = false, onChange, addLabel = '+ Add' } = {}) {
  const wrap = el('div', { class: 'sub-block' },
    el('div', { class: 'sub-title' }, el('span', { text: title }), el('span', { class: 'spacer' }),
      el('button', { class: 'btn tiny', text: addLabel, onclick: () => { obj[''] = 0; onChange?.(); rerender(); markDirty(); } })));

  function rerender() {
    for (const row of $$('.kv-row', wrap)) row.remove();
    const entries = Object.entries(obj);
    entries.forEach(([key, val], index) => {
      const keyInput = el('input', { type: 'text', class: 'input', value: key, autocomplete: 'off', placeholder: 'resource id' });
      if (!allowFreeKeys && keysList) keyInput.setAttribute('list', keysList);
      const num = el('input', { type: 'number', class: 'input', value: val, step: 'any', min: '0' });
      const remove = el('button', { class: 'icon-btn', text: '✕' });
      keyInput.addEventListener('change', () => {
        const newKey = keyInput.value.trim();
        const next = {};
        for (const [k, v] of Object.entries(obj)) next[k === key ? newKey : k] = v;
        for (const k of Object.keys(obj)) delete obj[k];
        Object.assign(obj, next);
        key = newKey;
        onChange?.();
        markDirty();
      });
      num.addEventListener('input', () => { obj[key] = parseFloat(num.value) || 0; onChange?.(); markDirty(); });
      remove.addEventListener('click', () => { delete obj[key]; onChange?.(); rerender(); markDirty(); });
      wrap.append(el('div', { class: 'kv-row' }, keyInput, num, remove));
    });
  }

  rerender();
  return wrap;
}

/** Requirement/effect list editor: type <select> + data as JSON. */
function reqEffectEditor(title, list, types, { addLabel = '+ Add' } = {}) {
  const wrap = el('div', { class: 'sub-block' },
    el('div', { class: 'sub-title' }, el('span', { text: title }), el('span', { class: 'spacer' }),
      el('button', { class: 'btn tiny', text: addLabel, onclick: () => { list.push({ type: types[0], data: {} }); rerender(); markDirty(); } })));

  function rerender() {
    for (const row of $$('.req-row', wrap)) row.remove();
    list.forEach((entry, index) => {
      const typeSelect = el('select', { class: 'input' });
      for (const t of types) {
        const o = el('option', { value: t, text: t });
        if (t === entry.type) o.selected = true;
        typeSelect.append(o);
      }
      const dataArea = el('textarea', { class: 'input json-area', spellcheck: 'false' });
      dataArea.value = JSON.stringify(entry.data ?? {}, null, 2);
      const remove = el('button', { class: 'icon-btn', text: '✕' });
      typeSelect.addEventListener('change', () => { entry.type = typeSelect.value; markDirty(); });
      dataArea.addEventListener('input', () => {
        try {
          entry.data = JSON.parse(dataArea.value || '{}');
          dataArea.classList.remove('bad', 'json-bad');
          markDirty();
        } catch {
          dataArea.classList.add('bad', 'json-bad');
        }
      });
      remove.addEventListener('click', () => { list.splice(index, 1); rerender(); markDirty(); });
      wrap.append(el('div', { class: 'req-row' }, typeSelect, dataArea, remove));
    });
  }

  rerender();
  return wrap;
}

const reqEditor = (title, list) => reqEffectEditor(title, list, REQ_TYPES);
const effEditor = (title, list) => reqEffectEditor(title, list, EFFECT_TYPES);

/** assignment_bonuses editor: {tag: AssignmentBonus}. */
function bonusEditor(obj) {
  const wrap = el('div', { class: 'sub-block' },
    el('div', { class: 'sub-title' }, el('span', { text: 'Assignment bonuses' }), el('span', { class: 'spacer' }),
      el('button', { class: 'btn tiny', text: '+ Add tag', onclick: () => { const t = `tag_${Object.keys(obj).length + 1}`; obj[t] = { output_mult: 1.0, efficiency_mult: 1.0, speed_mult: 1.0, quality_bonus: 0.0, stat_mods: {}, special_key: null, conditions: [] }; rerender(); markDirty(); } })));

  function rerender() {
    for (const row of $$('.bonus-row', wrap)) row.remove();
    wrap.append(el('div', { class: 'bonus-row' },
      el('span', { class: 'hdr', text: 'tag' }),
      el('span', { class: 'hdr', text: 'output×' }),
      el('span', { class: 'hdr', text: 'effic.×' }),
      el('span', { class: 'hdr', text: 'speed×' }),
      el('span', { class: 'hdr', text: 'quality+' }),
      el('span', { class: 'hdr', text: 'special key' }),
      el('span', { class: 'hdr', text: '' })));
    for (const [tag, bonus] of Object.entries(obj)) {
      const tagInput = el('input', { type: 'text', class: 'input', value: tag, autocomplete: 'off', list: 'rm-tag-names' });
      const out = el('input', { type: 'number', class: 'input', value: bonus.output_mult ?? 1, step: '0.05' });
      const eff = el('input', { type: 'number', class: 'input', value: bonus.efficiency_mult ?? 1, step: '0.05' });
      const spd = el('input', { type: 'number', class: 'input', value: bonus.speed_mult ?? 1, step: '0.05' });
      const qual = el('input', { type: 'number', class: 'input', value: bonus.quality_bonus ?? 0, step: '0.05' });
      const key = el('input', { type: 'text', class: 'input', value: bonus.special_key ?? '', placeholder: '—', autocomplete: 'off' });
      const remove = el('button', { class: 'icon-btn', text: '✕' });
      tagInput.addEventListener('change', () => {
        const newTag = tagInput.value.trim();
        if (!newTag) return;
        obj[newTag] = obj[tag];
        delete obj[tag];
        rerender();
        markDirty();
      });
      const num = (input, field) => input.addEventListener('input', () => { obj[tag][field] = parseFloat(input.value) || 0; markDirty(); });
      num(out, 'output_mult'); num(eff, 'efficiency_mult'); num(spd, 'speed_mult'); num(qual, 'quality_bonus');
      key.addEventListener('input', () => { obj[tag].special_key = key.value.trim() || null; markDirty(); });
      remove.addEventListener('click', () => { delete obj[tag]; rerender(); markDirty(); });
      wrap.append(el('div', { class: 'bonus-row' }, tagInput, out, eff, spd, qual, key, remove));
    }
  }

  rerender();
  return wrap;
}

/* ── per-tab forms ──────────────────────────────────────────────────── */

function selectedItem() {
  const coll = currentCollection();
  if (!coll) return null;
  return coll.find((i) => i.id === state.selected) ?? null;
}

function idField(item) {
  return textField('ID', item.id, {
    hint: 'Lowercase letters, digits, - and _. Start with a letter.',
    onInput: (v) => { item.id = v.trim().toLowerCase(); markDirty(); },
    pattern: '^[a-z][a-z0-9_-]{0,63}$',
  });
}

function formHeader(title, sub) {
  return [
    el('h2', {}, title),
    sub ? el('p', { class: 'form-sub', text: sub }) : null,
  ];
}

function renderResourceForm(item) {
  const frag = el('div');
  frag.append(
    ...formHeader('Resource', 'A named value the game tracks. Caps gate spending; visible_to_vn shares it with the story editor.'),
    el('div', { class: 'field-row' },
      idField(item),
      textField('Display name', item.name, { onInput: (v) => { item.name = v; markDirty(); } })),
    textField('Description', item.description, { onInput: (v) => { item.description = v; markDirty(); } }),
    el('div', { class: 'field-row' },
      numField('Base capacity', item.base_cap, { min: 0, onInput: (v) => { item.base_cap = v; markDirty(); } }),
      selectField('Type', item.resource_type, ['integer', 'decimal', 'boolean'], { onInput: (v) => { item.resource_type = v; markDirty(); } }),
      colorField('Color', item.color, { onInput: (v) => { item.color = v; markDirty(); } })),
    el('div', { class: 'field-row' },
      textField('Icon', item.icon, { hint: 'Key your UI understands (coin, heart, bolt…)', onInput: (v) => { item.icon = v; markDirty(); } }),
      textField('Format string', item.format_string, { hint: 'e.g. "{value} {icon}"', onInput: (v) => { item.format_string = v; markDirty(); } })),
    checkField('Show in HUD', item.show_in_hud, { onInput: (v) => { item.show_in_hud = v; markDirty(); } }),
    el('div', { class: 'sub-block' },
      el('div', { class: 'sub-title' }, el('span', { text: 'Visual novel integration' })),
      checkField('Visible to the VN', item.visible_to_vn, { hint: 'The story editor sees this as a declared global. One value, two editors.', onInput: (v) => { item.visible_to_vn = v; markDirty(); renderAll(); } }),
      el('div', { class: 'field-row' },
        selectField('VN scope', item.vn_scope, ['GLOBAL', 'LOCAL'], { hint: 'GLOBAL = shared by the whole pack (engine: WORLD). LOCAL = this story only.', onInput: (v) => { item.vn_scope = v; markDirty(); } }),
        textField('VN variable name', item.vn_name, { hint: 'Defaults to the id with - replaced by _', onInput: (v) => { item.vn_name = v.trim(); markDirty(); } }))));
  return frag;
}

function renderGeneratorForm(item) {
  const frag = el('div');
  frag.append(
    ...formHeader('Generator', 'Produces resources per tick. Assignables plug into slots and scale it.'),
    el('div', { class: 'field-row' },
      idField(item),
      textField('Display name', item.name, { onInput: (v) => { item.name = v; markDirty(); } })),
    textField('Description', item.description, { onInput: (v) => { item.description = v; markDirty(); } }),
    el('div', { class: 'field-row' },
      textField('Category', item.category, { hint: 'Free-form grouping for the UI (generation, training…)', onInput: (v) => { item.category = v; markDirty(); } }),
      numField('Slots', item.slots, { min: 0, step: '1', onInput: (v) => { item.slots = Math.max(0, Math.floor(v)); markDirty(); } }),
      numField('Grid X', item.grid_x ?? 0, { hint: 'Optional base-layout column', step: '1', onInput: (v) => { item.grid_x = Math.floor(v); markDirty(); } }),
      numField('Grid Y', item.grid_y ?? 0, { step: '1', onInput: (v) => { item.grid_y = Math.floor(v); markDirty(); } })),
    reqEditor('Requirements (to build)', item.requirements ?? (item.requirements = [])),
    bonusEditor(item.assignment_bonuses ?? (item.assignment_bonuses = {})),
    levelsEditor(item),
  );
  return frag;
}

function levelsEditor(item) {
  const wrap = el('div', { class: 'sub-block' },
    el('div', { class: 'sub-title' }, el('span', { text: `Levels (${item.levels.length})` }), el('span', { class: 'spacer' }),
      el('button', { class: 'btn tiny', text: '+ Add level', onclick: () => {
        item.levels.push({ level: item.levels.length + 1, cost: {}, output: {}, upkeep: {}, unlocks: [], requirements: [] });
        markDirty(); renderAll();
      } })));
  item.levels.sort((a, b) => a.level - b.level);
  item.levels.forEach((lv, i) => {
    lv.level = i + 1;
    const details = el('details', { class: 'lvl', ...(i === 0 ? { open: 'open' } : {}) },
      el('summary', {}, `Level ${lv.level}`,
        el('span', { class: 'spacer' }),
        el('button', { class: 'btn tiny danger', text: 'Remove', onclick: (e) => {
          e.preventDefault();
          if (item.levels.length <= 1) { toast('A generator needs at least one level.', 'error'); return; }
          item.levels.splice(i, 1);
          markDirty(); renderAll();
        } })),
      el('div', { class: 'lvl-body' },
        kvEditor('Cost (one-time)', lv.cost ?? (lv.cost = {}), { onChange: markDirty }),
        kvEditor('Output / tick', lv.output ?? (lv.output = {}), { onChange: markDirty }),
        kvEditor('Upkeep / tick', lv.upkeep ?? (lv.upkeep = {}), { onChange: markDirty }),
        csvField('Unlocks on reaching', lv.unlocks, { hint: 'Generator, converter, node or tech ids this level unlocks', onInput: (v) => { lv.unlocks = v; markDirty(); } }),
        reqEditor('Requirements (for this level)', lv.requirements ?? (lv.requirements = []))));
    wrap.append(details);
  });
  return wrap;
}

function renderConverterForm(item) {
  const frag = el('div');
  frag.append(
    ...formHeader('Converter', 'Transforms resources into resources. Recipes run one at a time per slot.'),
    el('div', { class: 'field-row' },
      idField(item),
      textField('Display name', item.name, { onInput: (v) => { item.name = v; markDirty(); } })),
    textField('Description', item.description, { onInput: (v) => { item.description = v; markDirty(); } }),
    el('div', { class: 'field-row' },
      textField('Category', item.category, { hint: 'Free-form grouping (crafting, refining…)', onInput: (v) => { item.category = v; markDirty(); } }),
      numField('Slots', item.slots, { min: 0, step: '1', onInput: (v) => { item.slots = Math.max(0, Math.floor(v)); markDirty(); } })),
    reqEditor('Requirements (to use)', item.requirements ?? (item.requirements = [])),
    bonusEditor(item.assignment_bonuses ?? (item.assignment_bonuses = {})),
    recipesEditor(item),
  );
  return frag;
}

function recipesEditor(item) {
  const wrap = el('div', { class: 'sub-block' },
    el('div', { class: 'sub-title' }, el('span', { text: `Recipes (${(item.recipes ?? []).length})` }), el('span', { class: 'spacer' }),
      el('button', { class: 'btn tiny', text: '+ Add recipe', onclick: () => {
        (item.recipes ?? (item.recipes = [])).push({ id: `recipe_${(item.recipes ?? []).length + 1}`, name: 'New recipe', inputs: {}, outputs: {}, duration: 1, chance_bonus: {}, requirements: [] });
        markDirty(); renderAll();
      } })));
  (item.recipes ?? []).forEach((rcp, i) => {
    const details = el('details', { class: 'rcp', open: 'open' },
      el('summary', {}, rcp.name || rcp.id,
        el('span', { class: 'spacer' }),
        el('button', { class: 'btn tiny danger', text: 'Remove', onclick: (e) => { e.preventDefault(); item.recipes.splice(i, 1); markDirty(); renderAll(); } })),
      el('div', { class: 'rcp-body' },
        el('div', { class: 'field-row' },
          textField('Recipe id', rcp.id, { onInput: (v) => { rcp.id = v.trim().toLowerCase(); markDirty(); } }),
          textField('Name', rcp.name, { onInput: (v) => { rcp.name = v; markDirty(); } }),
          numField('Duration (ticks)', rcp.duration, { min: 0.05, onInput: (v) => { rcp.duration = Math.max(0.05, v); markDirty(); } })),
        kvEditor('Inputs (consumed)', rcp.inputs ?? (rcp.inputs = {}), { onChange: markDirty }),
        kvEditor('Outputs (produced)', rcp.outputs ?? (rcp.outputs = {}), { onChange: markDirty }),
        kvEditor('Chance bonus (+1 probability)', rcp.chance_bonus ?? (rcp.chance_bonus = {}), { onChange: markDirty }),
        reqEditor('Requirements', rcp.requirements ?? (rcp.requirements = []))));
    wrap.append(details);
  });
  return wrap;
}

function renderNodeForm(item) {
  const frag = el('div');
  frag.append(
    ...formHeader('Node', 'A point on a map or tree: expedition, encounter, location, story beat or trade.'),
    el('div', { class: 'field-row' },
      idField(item),
      textField('Display name', item.name, { onInput: (v) => { item.name = v; markDirty(); } }),
      selectField('Type', item.node_type, NODE_TYPES, { onInput: (v) => { item.node_type = v; markDirty(); } })),
    textField('Description', item.description, { onInput: (v) => { item.description = v; markDirty(); } }),
    el('div', { class: 'field-row' },
      numField('Duration (s)', item.duration, { min: 0, hint: '0 = instant', onInput: (v) => { item.duration = Math.max(0, v); markDirty(); } }),
      numField('Map X', item.x, { step: '10', onInput: (v) => { item.x = v; markDirty(); } }),
      numField('Map Y', item.y, { step: '10', onInput: (v) => { item.y = v; markDirty(); } })),
    reqEditor('Requirements', item.requirements ?? (item.requirements = [])),
    kvEditor('Fixed rewards', item.rewards ?? (item.rewards = {}), { onChange: markDirty }),
    chanceRewardsEditor(item),
    csvField('Event pool', item.event_pool, { list: 'rm-event-ids', hint: 'Events rolled when this node resolves', onInput: (v) => { item.event_pool = v; markDirty(); } }),
    csvField('Connects to', item.connects_to, { list: 'rm-node-ids', hint: 'Nodes unlocked when this node completes', onInput: (v) => { item.connects_to = v; markDirty(); } }),
    textField('VN label', item.vn_label, { hint: 'Story nodes only — label the VN jumps to on completion', onInput: (v) => { item.vn_label = v.trim() || null; markDirty(); } }));
  return frag;
}

function chanceRewardsEditor(item) {
  const wrap = el('div', { class: 'sub-block' },
    el('div', { class: 'sub-title' }, el('span', { text: 'Chance rewards' }), el('span', { class: 'spacer' }),
      el('button', { class: 'btn tiny', text: '+ Add', onclick: () => { (item.chance_rewards ?? (item.chance_rewards = [])).push({ resource: '', probability: 0.1, amount: 1 }); rerender(); markDirty(); } })));

  function rerender() {
    for (const row of $$('.cr-row', wrap)) row.remove();
    (item.chance_rewards ?? []).forEach((cr, index) => {
      const res = el('input', { type: 'text', class: 'input', value: cr.resource, placeholder: 'resource id', list: 'rm-resource-ids', autocomplete: 'off' });
      const prob = el('input', { type: 'number', class: 'input', value: cr.probability, min: 0, max: 1, step: '0.01' });
      const amt = el('input', { type: 'number', class: 'input', value: cr.amount, min: 0.01, step: 'any' });
      const remove = el('button', { class: 'icon-btn', text: '✕' });
      res.addEventListener('change', () => { cr.resource = res.value.trim(); markDirty(); });
      prob.addEventListener('input', () => { cr.probability = parseFloat(prob.value) || 0; markDirty(); });
      amt.addEventListener('input', () => { cr.amount = parseFloat(amt.value) || 1; markDirty(); });
      remove.addEventListener('click', () => { item.chance_rewards.splice(index, 1); rerender(); markDirty(); });
      wrap.append(el('div', { class: 'cr-row' }, res, prob, amt, remove));
    });
  }

  rerender();
  return wrap;
}

function renderTechForm(item) {
  const frag = el('div');
  frag.append(
    ...formHeader('Tech node', 'Research unlock: gates content and applies global effects on completion.'),
    el('div', { class: 'field-row' },
      idField(item),
      textField('Display name', item.name, { onInput: (v) => { item.name = v; markDirty(); } })),
    textField('Description', item.description, { onInput: (v) => { item.description = v; markDirty(); } }),
    el('div', { class: 'field-row' },
      numField('Tree X', item.x, { step: '10', onInput: (v) => { item.x = v; markDirty(); } }),
      numField('Tree Y', item.y, { step: '10', onInput: (v) => { item.y = v; markDirty(); } })),
    kvEditor('Cost', item.cost ?? (item.cost = {}), { onChange: markDirty }),
    reqEditor('Requirements', item.requirements ?? (item.requirements = [])),
    csvField('Unlocks', item.unlocks, { hint: 'Generator, converter, node, tech or event ids', onInput: (v) => { item.unlocks = v; markDirty(); } }),
    effEditor('Effects (on research)', item.effects ?? (item.effects = [])));
  return frag;
}

function renderEventForm(item) {
  const frag = el('div');
  frag.append(
    ...formHeader('Event', 'A random outcome rolled from a node event pool. Weight biases the dice.'),
    el('div', { class: 'field-row' },
      idField(item),
      textField('Display name', item.name, { onInput: (v) => { item.name = v; markDirty(); } }),
      numField('Weight', item.weight, { min: 0.01, hint: 'Relative probability against sibling events', onInput: (v) => { item.weight = Math.max(0.01, v); markDirty(); } })),
    textField('Description', item.description, { onInput: (v) => { item.description = v; markDirty(); } }),
    reqEditor('Requirements (can this fire?)', item.requirements ?? (item.requirements = [])),
    effEditor('Effects (when it fires)', item.effects ?? (item.effects = [])));
  return frag;
}

function renderAssignableForm(item) {
  const frag = el('div');
  const vnField = item.source === 'vn_character'
    ? textField('VN character', item.vn_character_slug ?? '', { list: 'rm-story-slugs', hint: 'Story slug in this pack (e.g. cupa)', onInput: (v) => { item.vn_character_slug = v.trim() || null; markDirty(); } })
    : null;
  frag.append(
    ...formHeader('Assignable', 'A worker, hero, module or spirit — tags drive assignment bonuses.'),
    el('div', { class: 'field-row' },
      idField(item),
      textField('Display name', item.name, { onInput: (v) => { item.name = v; markDirty(); } })),
    textField('Description', item.description, { onInput: (v) => { item.description = v; markDirty(); } }),
    el('div', { class: 'field-row' },
      selectField('Source', item.source, SOURCE_TYPES, { hint: 'vn_character = comes from a story in this pack', onInput: (v) => { item.source = v; markDirty(); renderAll(); } }),
      vnField),
    csvField('Tags', item.tags, { list: 'rm-tag-names', hint: 'The whole point — generators and converters read these', onInput: (v) => { item.tags = v; markDirty(); rebuildDatalists(); } }),
    kvEditor('Base stats (open vocabulary)', item.base_stats ?? (item.base_stats = {}), { allowFreeKeys: true, keysList: null, onChange: markDirty, addLabel: '+ Add stat' }));
  return frag;
}

function renderSettingsForm() {
  const s = state.schema;
  const frag = el('div');
  frag.append(
    el('h2', {}, 'Settings'),
    el('p', { class: 'form-sub', text: 'Schema-wide switches. Everything else lives on the tabs.' }),
    el('div', { class: 'sub-block' },
      el('div', { class: 'sub-title' }, el('span', { text: 'Simulation' })),
      el('div', { class: 'field-row' },
        numField('Tick rate (Hz)', s.tick_rate_hz, { min: 0.1, step: '0.5', hint: 'Resource ticks per second', onInput: (v) => { s.tick_rate_hz = Math.max(0.1, v); markDirty(); } }),
        numField('Max offline hours', s.max_offline_hours, { min: 0, step: '1', hint: 'How much progress accrues while away', onInput: (v) => { s.max_offline_hours = Math.max(0, v); markDirty(); } })),
      el('div', { class: 'field-row' },
        numField('Schema version', s.version, { step: '1', onInput: () => {} }))),
    rmVnSummaryBlock());
  const versionField = frag.querySelector('input[type="number"]');
  if (versionField) versionField.disabled = true;
  return frag;
}

function rmVnSummaryBlock() {
  const s = state.schema;
  const synced = s.resources.filter((r) => r.visible_to_vn);
  const wrap = el('div', { class: 'sub-block' },
    el('div', { class: 'sub-title' }, el('span', { text: `VN variables synced (${synced.length})` })),
    el('p', { class: 'field-hint', text: 'Derived from Resources with "Visible to the VN" on. They appear in the Variables tab as declared globals. Editing happens on the Resources tab.' }));
  if (!synced.length) {
    wrap.append(el('p', { class: 'form-sub', text: 'Nothing synced yet.' }));
    return wrap;
  }
  const table = el('table', { class: 'plain' });
  table.append(el('tr', {},
    el('th', { text: 'Resource' }),
    el('th', { text: 'VN name' }),
    el('th', { text: 'Scope' }),
    el('th', { text: 'Type' })));
  for (const r of synced) {
    table.append(el('tr', {},
      el('td', {}, `${r.icon || '•'} ${r.name}`),
      el('td', { text: r.vn_name || String(r.id).replace(/-/g, '_') }),
      el('td', { text: r.vn_scope }),
      el('td', { text: r.resource_type })));
  }
  wrap.append(table);
  return wrap;
}

const FORM_RENDERERS = {
  resources: renderResourceForm,
  generators: renderGeneratorForm,
  converters: renderConverterForm,
  nodes: renderNodeForm,
  tech_nodes: renderTechForm,
  events: renderEventForm,
  assignables: renderAssignableForm,
};

function renderForm() {
  const container = $('#rm-form');
  container.innerHTML = '';
  if (state.activeTab === 'settings') {
    container.append(renderSettingsForm());
    return;
  }
  const render = FORM_RENDERERS[state.activeTab];
  const item = selectedItem();
  if (!item || !render) return;
  container.append(render(item));
}

function renderAll() {
  ensureSelection();
  rebuildDatalists();
  renderTabs();
  renderList();
  renderForm();
  renderProblems();
  renderStatus();
}

/* ── boot ───────────────────────────────────────────────────────────── */

async function boot() {
  const params = new URLSearchParams(window.location.search);
  const project = params.get('project');
  if (!project) {
    $('#rm-form').innerHTML = '<p class="empty-hint">No project selected. <a href="/manager">Go back to the manager</a> and pick one.</p>';
    $('#rm-status').textContent = 'no project';
    return;
  }
  state.project = project;
  document.title = `Hikarin Studio — Resource Management — ${project}`;
  $('#rm-project').textContent = `projects/${project}/`;

  const res = await fetch(`/api/projects/${encodeURIComponent(project)}/resource-management`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    $('#rm-status').textContent = 'load failed';
    $('#rm-form').innerHTML = `<p class="empty-hint">${err.detail || 'Could not load the schema.'}</p>`;
    return;
  }
  const body = await res.json();
  state.schema = body.schema;
  state.problems = body.problems || [];

  try {
    const detail = await fetch(`/api/projects/${encodeURIComponent(project)}`).then((r) => r.json());
    state.stories = (detail.stories || []).map((s) => s.slug);
  } catch { state.stories = []; }

  const first = state.schema.resources[0] || state.schema.generators[0] || state.schema.converters[0];
  if (first) {
    state.activeTab =
      state.schema.resources.length ? 'resources' :
      state.schema.generators.length ? 'generators' : 'converters';
    state.selected = first.id;
  }

  $('#btn-save').addEventListener('click', () => { state.dirty = true; save(false); });
  $('#btn-validate').addEventListener('click', () => validateNow());
  $('#btn-export').addEventListener('click', () => exportKit());
  $('#rm-add').addEventListener('click', addItem);
  $('#rm-search').addEventListener('input', renderList);
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      state.dirty = true;
      save(false);
    }
  });

  renderAll();
}

boot();

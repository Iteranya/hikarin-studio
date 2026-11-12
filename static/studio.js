/* Hikarin Studio — editor logic.
 *
 * State lives in `state.projects[slug]`. The server owns the files; this module
 * only needs to render blocks and POST changes back.
 *
 * The editor never assigns action ids — the compiler does. Blocks are
 * {kind, data} and every reference is a label name, so a writer can reorder
 * tabs and blocks freely without breaking anything.
 */

import { initAssets, openAssets, deleteAssetPath } from './assets.js';
import { openGameEditor, closeGameEditor } from './game.js';

const $ = (id) => document.getElementById(id);

// ── state ───────────────────────────────────────────────────────────────────

const state = {
  meta: null,              // block definitions from /api/meta
  project: null,           // { slug, meta, files, assets }
  activeFile: null,
  selected: null,          // { file, index }
  dirty: false,
  lastCompile: null,
};

// ── autosave ────────────────────────────────────────────────────────────────
//
// Everything writes itself. There is no "remember to save" step to forget, and
// no amber chip to lose an afternoon to.
//
// The shape is write-behind: an edit marks the project dirty and starts a timer;
// further edits restart it. When it fires, the whole project goes up in one PUT,
// because that is the endpoint that exists and a story is small.
//
// Two rules keep it honest:
//   * one PUT at a time. A second save while the first is open sets `queued`
//     and the in-flight one re-schedules when it lands — two overlapping writes
//     racing on the same file is how a save silently reverts an edit.
//   * a save is flushed before anything that reads the files from disk (project
//     switch, preview) so the disk and the screen never disagree.
const AUTOSAVE_DELAY = 900;      // ms of idle after the last edit

const autosave = {
  timer: null,
  inFlight: null,
  queued: false,
  retry: null,
};

// ── boot ────────────────────────────────────────────────────────────────────

async function boot() {
  state.meta = await fetch('/api/meta').then((r) => r.json());
  renderPalette();
  // The asset window reads and writes media folders directly, so it needs the
  // live state object and a way to tell the editor that a picker's options
  // changed underneath it.
  initAssets({ state, onChange: onAssetsChanged });
  await refreshProjectList();
  wireChrome();
  wireLauncher();
  wireMobileNav();
}

// ── mobile pane switching ───────────────────────────────────────────────────
// On ≤900px the four panes are stacked and only one is visible; the bottom
// nav picks which. On desktop the nav is display:none and this is inert.

const MOBILE_PANES = ['palette', 'centre', 'inspector', 'outline'];

function showMobilePane(name) {
  for (const p of MOBILE_PANES) {
    const el = p === 'centre' ? document.getElementById('centre') : document.getElementById(p);
    el?.classList.toggle('mobile-active', p === name);
  }
  document.querySelectorAll('#mobile-nav .mobile-nav-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.pane === name);
  });
}

function wireMobileNav() {
  const nav = document.getElementById('mobile-nav');
  if (!nav) return;
  nav.addEventListener('click', (e) => {
    const btn = e.target.closest('.mobile-nav-btn');
    if (btn) showMobilePane(btn.dataset.pane);
  });
  // Default visible pane on small screens.
  const mq = window.matchMedia('(max-width: 900px)');
  if (mq.matches) showMobilePane('centre');
  mq.addEventListener?.('change', (e) => { if (e.matches) showMobilePane('centre'); });
}

function isMobileLayout() {
  return window.matchMedia('(max-width: 900px)').matches;
}

/** Re-render whatever the asset window may have just changed. */
function onAssetsChanged() {
  if (!state.project) return;
  renderInspector();
  renderBlocks();
}

// ── project launcher (page) ──────────────────────────────────────────────────

const launcher = {
  projects: [],
  filter: '',
};

async function showLauncher() {
  launcher.projects = await fetch('/api/projects').then((r) => r.json()).catch(() => []);
  document.getElementById('launcher').hidden = false;
  const input = document.getElementById('launcher-search');
  if (input) input.value = launcher.filter;
  renderLauncher();
}

function hideLauncher() {
  const el = document.getElementById('launcher');
  if (el) el.hidden = true;
}

function renderLauncher() {
  const grid = document.getElementById('launcher-grid');
  if (!grid) return;
  const q = launcher.filter.trim().toLowerCase();
  const list = launcher.projects.filter((p) => !q
    || p.slug.toLowerCase().includes(q)
    || (p.packName ?? '').toLowerCase().includes(q)
    || (p.description ?? '').toLowerCase().includes(q));

  const countEl = document.getElementById('launcher-count');
  if (countEl) countEl.textContent = `${launcher.projects.length} project${launcher.projects.length === 1 ? '' : 's'}`;

  if (!list.length) {
    grid.innerHTML = launcher.filter
      ? `<div class="launcher-empty"><div class="launcher-empty-title">No matches for "${escapeLauncher(launcher.filter)}"</div><div>Try clearing the filter.</div></div>`
      : `<div class="launcher-empty"><div class="launcher-empty-title">No projects yet</div><div>Press <b>New Story</b> for a visual-novel script, or <b>New Game</b> for an orchestrator-driven world.</div></div>`;
    return;
  }

  grid.innerHTML = list.map((p) => `
    <div class="launch-card" data-slug="${escapeLauncher(p.slug)}" tabindex="0" role="button">
      <div class="launch-card-top">
        <div class="launch-icon ${p.kind === 'game' ? 'game' : 'story'}">${p.kind === 'game' ? '🎮' : '📖'}</div>
        <div>
          <div class="launch-card-name">${escapeLauncher(p.packName || p.slug)}</div>
          <div class="launch-card-slug">${escapeLauncher(p.slug)}</div>
        </div>
        <span class="launch-kind ${p.kind === 'game' ? 'game' : 'story'}">${escapeLauncher(p.kind ?? 'story')}</span>
      </div>
      <div class="launch-desc">${escapeLauncher(p.description ?? '')}</div>
      <div class="launch-meta">
        <span>${(p.files ?? []).length} file${(p.files ?? []).length === 1 ? '' : 's'}</span>
        <span>·</span>
        <span>${relTime(p.modified)}</span>
      </div>
      <div class="launch-card-actions">
        <button class="btn tiny primary launch-open">Open</button>
        <button class="btn tiny launch-duplicate">Duplicate</button>
        <button class="btn tiny danger launch-delete" title="Delete">Delete</button>
      </div>
    </div>`).join('');

  grid.querySelectorAll('.launch-card').forEach((card) => {
    const slug = card.dataset.slug;
    card.addEventListener('click', (ev) => {
      if (ev.target.closest('button')) return;
      hideLauncher();
      openProject(slug);
    });
    card.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') { hideLauncher(); openProject(slug); }
    });
    card.querySelector('.launch-open').addEventListener('click', () => { hideLauncher(); openProject(slug); });
    card.querySelector('.launch-duplicate').addEventListener('click', () => launcherDuplicate(slug));
    card.querySelector('.launch-delete').addEventListener('click', () => launcherDelete(slug));
  });
}

function escapeLauncher(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

function relTime(ms) {
  const s = Math.floor((Date.now() - Number(ms || 0)) / 1000);
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24); return `${d}d ago`;
}

async function launcherDuplicate(slug) {
  const new_slug = prompt('New project name (lowercase, no spaces)', slug + '-copy');
  if (!new_slug) return;
  const res = await fetch(`/api/projects/${slug}/duplicate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_slug }),
  });
  if (!res.ok) { alert((await res.json()).detail || 'Duplicate failed'); return; }
  await showLauncher();
}

async function launcherDelete(slug) {
  if (!confirm(`Delete project "${slug}"? This removes its folder and all files inside it.`)) return;
  const res = await fetch(`/api/projects/${slug}`, { method: 'DELETE' });
  if (!res.ok) { alert((await res.json()).detail || 'Delete failed'); return; }
  if (state.project?.slug === slug) state.project = null;
  await showLauncher();
}

async function launcherNew(kind) {
  const slug = prompt(kind === 'game' ? 'Game name (lowercase, no spaces)' : 'Project name (lowercase, no spaces)');
  if (!slug) return;
  const packName = prompt(kind === 'game' ? 'Game title' : 'Story title', slug) || slug;
  const res = await fetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug, meta: { kind, packName, character: slug } }),
  });
  if (!res.ok) { alert((await res.json()).detail || 'Could not create the project.'); return; }
  hideLauncher();
  await openProject(slug);
}

function wireLauncher() {
  document.getElementById('btn-launcher')?.addEventListener('click', () => {
    if (document.getElementById('launcher').hidden) showLauncher();
    else hideLauncher();
  });
  document.getElementById('launcher-search')?.addEventListener('input', (e) => {
    launcher.filter = e.target.value;
    renderLauncher();
  });
  document.getElementById('launcher-new-story')?.addEventListener('click', () => launcherNew('story'));
  document.getElementById('launcher-new-game')?.addEventListener('click', () => launcherNew('game'));
  document.getElementById('launcher-import')?.addEventListener('click', () => document.getElementById('file-import').click());
}

async function refreshProjectList() {
  const projects = await fetch('/api/projects').then((r) => r.json());
  const sel = document.getElementById('project-select');
  if (sel) {
    const current = state.project?.slug;
    sel.innerHTML = '';
    for (const p of projects) {
      const opt = document.createElement('option');
      opt.value = p.slug;
      opt.textContent = (p.packName || p.slug) + ' (' + p.slug + ')';
      if (p.slug === current) opt.selected = true;
      sel.appendChild(opt);
    }
  }
  if (projects.length === 0) {
    setStatus('compile', 'no projects yet — press New', 'warn');
    return;
  }
  // Auto-open the most recently modified project so a reload resumes work.
  // Boot (and fresh returns) land on the project manager page, not a story.
  await showLauncher();
}

async function openProject(slug) {
  hideLauncher();
  // Whatever is on screen has to be on disk before the next project's files are
  // read, or an autosave can land on the project you just left.
  if (state.project) await flushAutosave();

  const data = await fetch(`/api/projects/${slug}`).then((r) => r.json());
  state.project = data;
  const sel = document.getElementById('project-select'); if (sel) sel.value = slug;
  if (data.meta?.kind === 'game') {
    // Game projects bypass the story editor entirely; nobody should be
    // staring at the dialogue blocks for a world graph.
    closeGameEditor(); // closed state reset, then re-open below
    $('game-shell').hidden = false;
    document.querySelector('.workspace').style.visibility = 'hidden';
    document.getElementById('empty-state')?.setAttribute('hidden', 'hidden');
    state.project.meta.files = [];
    state.project.files = {};
    state.project.assets = data.assets ?? state.project.assets;
    $('mobile-nav')?.setAttribute('hidden', 'hidden');
    await openGameEditor(data);
    return;
  }
  closeGameEditor();
  $('game-shell').hidden = true;
  $('mobile-nav')?.removeAttribute('hidden');
  document.querySelector('.workspace').style.visibility = 'visible';
  state.activeFile = data.meta.files[0] ?? null;
  state.selected = null;
  state.dirty = false;

  $('project-name').textContent = data.meta.packName || slug;
  $('project-character').textContent = data.meta.character || '—';
  $('btn-play').disabled = false;
  $('btn-export').disabled = false;
  $('btn-compile').disabled = false;
  $('btn-assets').disabled = false;

  // #empty-state lives *inside* #blocklist in index.html, and renderBlocks()
  // wipes that list on every render — so from the second openProject() onwards
  // the element is gone. Touching it unguarded threw a TypeError right here,
  // halfway through the load, which aborted renderTabs/renderBlocks and left
  // the previous project's blocks on screen. That is the whole "switching
  // projects does nothing" bug: the fetch succeeded, the render never ran.
  const emptyState = $('empty-state');
  if (emptyState) emptyState.hidden = true;


  renderTabs();
  renderBlocks();
  renderOutline();
  renderInspector();
  updateCounts();
}

// ── palette ─────────────────────────────────────────────────────────────────

const GROUP_ORDER = ['talk', 'stage', 'flow', 'state', 'audio'];

const GROUP_LABELS = {
  talk: 'Talk',
  stage: 'Stage',
  flow: 'Flow',
  state: 'State',
  audio: 'Audio',
};

const GROUP_COLOURS = {
  talk: 'var(--talk)',
  stage: 'var(--stage)',
  flow: 'var(--flow)',
  state: 'var(--state)',
  audio: 'var(--audio)',
};

const ICONS = {
  say: '💬', choice: '🔀', nightChoice: '🌙', idle: '🗣️',
  show: '🎭', hide: '👋', background: '🖼️', clearBackground: '⬛',
  label: '🏷️', jump: '➡️', if: '❓', next: '⏭️', end: '🏁', playLevel: '▶️', mapSwitch: '🗺️',
  setVar: '📝', unlock: '🔓', giveItem: '🎁', takeItem: '✋',
  music: '🎵', sound: '🔊', command: '⌨️',
};

const TITLES = {
  say: 'Say', choice: 'Choice', nightChoice: 'Night Choice', idle: 'Idle Chat',
  show: 'Show Character', hide: 'Hide Character', background: 'Background',
  clearBackground: 'Clear Background', label: 'Label', jump: 'Jump', if: 'If',
  next: 'Resume Point', end: 'End Scene', setVar: 'Set Variable', unlock: 'Unlock',
  giveItem: 'Give Item', takeItem: 'Take Item', music: 'Music', sound: 'Sound',
  command: 'Command', playLevel: 'Play Level (PvZ)', mapSwitch: 'Map Switch',
};

// Blocks the palette shows, in palette order. Not every engine action gets a
// block: conditional_global and modify_global are legacy aliases the compiler
// still reads, but authors use the scoped versions.
const PALETTE = [
  ['talk', ['say', 'choice', 'nightChoice', 'idle']],
  ['stage', ['show', 'hide', 'background', 'clearBackground']],
  ['flow', ['label', 'jump', 'if', 'next', 'end', 'playLevel', 'mapSwitch']],
  ['state', ['setVar', 'unlock', 'giveItem', 'takeItem']],
  ['audio', ['music', 'sound']],
];

function groupOf(kind) {
  for (const [group, kinds] of PALETTE) {
    if (kinds.includes(kind)) return group;
  }
  return 'flow';
}

function renderPalette() {
  const body = $('palette-body');
  body.innerHTML = '';

  for (const [group, kinds] of PALETTE) {
    const wrap = document.createElement('div');
    wrap.className = 'group';

    const head = document.createElement('div');
    head.className = 'group-head';
    head.innerHTML = `<span class="group-dot" style="background:${GROUP_COLOURS[group]}"></span>${GROUP_LABELS[group]}`;
    wrap.appendChild(head);

    for (const kind of kinds) {
      const item = document.createElement('button');
      item.className = 'palette-item';
      item.innerHTML = `<span class="palette-icon">${ICONS[kind] ?? '•'}</span>${TITLES[kind] ?? kind}`;
      item.onclick = () => addBlock(kind);
      wrap.appendChild(item);
    }
    body.appendChild(wrap);
  }
}

// ── tabs ────────────────────────────────────────────────────────────────────

function renderTabs() {
  const tabs = $('tabs');
  tabs.innerHTML = '';

  for (const file of state.project.meta.files) {
    const tab = document.createElement('button');
    tab.className = 'tab' + (file === state.activeFile ? ' active' : '');
    tab.textContent = file.replace(/\.story$/, '');

    if (file === state.activeFile && state.dirty) {
      const dot = document.createElement('span');
      dot.className = 'tab-dirty';
      dot.textContent = '•';
      tab.appendChild(dot);
    }

    tab.onclick = () => {
      state.activeFile = file;
      state.selected = null;
      renderTabs();
      renderBlocks();
      renderInspector();
    };
    tabs.appendChild(tab);
  }

  const add = document.createElement('button');
  add.className = 'tab';
  add.textContent = '+';
  add.title = 'New file';
  add.onclick = newFile;
  tabs.appendChild(add);
}

function newFile() {
  const name = prompt('File name (e.g. night.story or items/endrod.story)');
  if (!name) return;
  const clean = name.endsWith('.story') ? name : `${name}.story`;
  if (state.project.files[clean]) {
    alert('That file already exists.');
    return;
  }
  state.project.files[clean] = [];
  state.project.meta.files.push(clean);
  state.activeFile = clean;
  state.selected = null;
  markDirty();
  renderTabs();
  renderBlocks();
  renderInspector();
  updateCounts();
}

// ── block list ──────────────────────────────────────────────────────────────

function blocks() {
  return state.project.files[state.activeFile] ?? [];
}

function renderBlocks() {
  const list = $('blocklist');
  list.innerHTML = '';

  if (!state.activeFile) return;
  const items = blocks();

  if (items.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.innerHTML = '<p class="empty-title">Empty file</p><p class="empty-hint">Add a Label block to start.</p>';
    list.appendChild(empty);
    return;
  }

  items.forEach((block, index) => {
    const el = document.createElement('div');
    const group = groupOf(block.kind);
    el.className = 'block' + (state.selected?.file === state.activeFile && state.selected?.index === index ? ' selected' : '');
    el.dataset.group = group;
    if (block.kind === 'label') el.classList.add('block-label');

    el.innerHTML = `
      <span class="block-icon">${ICONS[block.kind] ?? '•'}</span>
      <span class="block-text">${summarise(block)}</span>
      <button class="block-del" title="Delete this block">✕</button>
    `;

    el.onclick = () => selectBlock(index);

    // Delete straight from the row. The inspector has the same button, but
    // needing to select a block before you can remove it is a pointless step —
    // and for the Show block, whose form is tall, the inspector button was
    // often scrolled out of sight, which read as "there is no delete here".
    const del = el.querySelector('.block-del');
    del.onclick = (event) => {
      event.stopPropagation();
      state.selected = { file: state.activeFile, index };
      deleteBlock();
    };

    list.appendChild(el);
  });
}

function summarise(block) {
  const d = block.data || {};
  const esc = (s) => String(s ?? '').replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
  const cut = (s, n = 60) => {
    const text = String(s ?? '');
    return text.length > n ? `${text.slice(0, n - 1)}…` : text;
  };

  switch (block.kind) {
    case 'say':
      return `<b>${esc(d.label || 'narration')}</b> <span class="block-sub">"${esc(cut(d.content))}"</span>`;
    case 'choice':
    case 'nightChoice':
      return `<span class="block-sub">${(d.choices || []).length} option(s):</span> ${esc((d.choices || []).map((c) => c.display).join(' / '))}`;
    case 'idle':
      return '<span class="block-sub">random unlocked line</span>';
    case 'show': {
      if (d.mode === 'box') {
        const lay = d.layout || {};
        const size = `${lay.wFrameRatio ?? 10}×${lay.hFrameRatio ?? 6} cells`;
        return `<span class="block-sub">image box</span> <b>${esc(d.folder || 'asset')}/${esc(d.image || '?')}</b> <span class="block-sub">${size}</span>`;
      }
      const lay = d.layout || {};
      const pos = lay.preset || 'CENTER';
      return `<b>${esc(d.sprite || '?')}</b> <span class="block-sub">${esc(d.outfit || 'default')}/${esc(d.expression || 'normal')} · ${esc(String(pos).toLowerCase())}</span>`;
    }
    case 'hide':
      if (d.mode === 'box') {
        return `<span class="block-sub">image box</span> <b>${esc(d.folder || 'asset')}/${esc(d.image || '?')}</b>`;
      }
      return `<b>${esc(d.sprite || '?')}</b>`;
    case 'background':
      return `<span class="block-sub">${esc(d.background || 'none')}</span>`;
    case 'clearBackground':
      return '<span class="block-sub">back to the world</span>';
    case 'label':
      return `${esc(d.name || 'unnamed')}`;
    case 'jump':
      return `<span class="block-sub">→</span> <b>${esc(d.target || '?')}</b>`;
    case 'if': {
      const spec = state.meta?.conditions?.[d.condition] || { label: d.condition, needs_var: true, needs_value: true };
      const target = `<b>${esc(d._target || '?')}</b>`;

      // Day and night have no variable to name, so reading them out as
      // "scene·isNight" would invent a concept the engine does not have.
      if (spec.needs_var === false) {
        return `<span class="block-sub">${esc(spec.label)} — otherwise →</span> ${target}`;
      }

      const value = spec.needs_value ? ` ${esc(d.value)}` : '';
      return `<span class="block-sub">${esc(d.scope || 'scene')}·${esc(d.var || '?')} ${esc(spec.label)}${value} — otherwise →</span> ${target}`;
    }
    case 'next':
      return `<span class="block-sub">resume here next time →</span> <b>${esc(d.target || '?')}</b>`;
    case 'mapSwitch':
      // Game cartridges: the engine swaps the current map. Names resolve
      // against world/maps.json in the shipping game; free text in a story.
      all.push(text('map', 'Map id', 'home', 'maps.json id to load'));
      all.push({ key: 'x', label: 'X', render: () => numberInput(d, 'x', 0) });
      all.push({ key: 'y', label: 'Y', render: () => numberInput(d, 'y', 0) });
      all.push(selectEl(d, 'facing', [
        { value: 'up', label: 'up' },
        { value: 'down', label: 'down' },
        { value: 'left', label: 'left' },
        { value: 'right', label: 'right' },
      ], 'Facing'));
      break;

    case 'playLevel':
      return `<span class="block-sub">play →</span> <b>${esc(d.level || '?')}</b>`;
    case 'end':
      return '<span class="block-sub">close the screen</span>';
    case 'mapSwitch':
      return `<span class="block-sub">map →</span> <b>${esc(d.map || '?')}</b> <span class="block-sub">(${esc(d.x ?? 0)}, ${esc(d.y ?? 0)})${d.facing ? ` · ${esc(d.facing)}` : ''}</span>`;
    case 'setVar': {
      const op = { set: '=', increment_var: '+=', subtract_var: '-=' }[d.operation] || '=';
      return `<span class="block-sub">${esc(d.scope || 'scene')}·${esc(d.var || '?')} ${op} ${esc(d.value)}</span>`;
    }
    case 'unlock':
      return `<span class="block-sub">+${(d.labels || []).length} idle line(s)</span>`;
    case 'giveItem':
    case 'takeItem':
      return `<b>${esc(d.amount || 1)}x</b> <span class="block-sub">${esc(d.item || '?')}</span>`;
    case 'music':
      return d.music ? `♪ ${esc(d.music)}` : '<span class="block-sub">stop music</span>';
    case 'sound':
      return `<span class="block-sub">${esc(d.sound || 'none')}</span>`;
    default:
      return `<span class="block-sub">${esc(block.kind)}</span>`;
  }
}

function selectBlock(index) {
  state.selected = { file: state.activeFile, index };
  renderBlocks();
  renderInspector();
  if (isMobileLayout()) showMobilePane('inspector');
}

function addBlock(kind) {
  const items = blocks();
  const insertAt = state.selected ? state.selected.index + 1 : items.length;
  items.splice(insertAt, 0, { kind, data: defaultData(kind) });
  state.selected = { file: state.activeFile, index: insertAt };
  markDirty();
  renderBlocks();
  renderInspector();
  renderOutline();
  updateCounts();
}

// The "+ Say" button: one press creates a Say block right after the current
// selection and drops the cursor in its text field — the travelling speed of
// an author writing dialogue, particularly thumb-sized on mobile.
function addSayBlock() {
  addBlock('say');
  if (isMobileLayout()) showMobilePane('inspector');
  const areas = $('inspector-body').querySelectorAll('textarea');
  const target = areas.length > 1 ? areas[1] : areas[0];
  target?.focus();
}

function defaultData(kind) {
  switch (kind) {
    case 'label':
      return { name: '' };
    case 'say':
      return { label: '', content: '' };
    case 'choice':
    case 'nightChoice':
      return { choices: [{ label: '', display: '' }] };
    case 'show':
      return { sprite: '', expression: 'normal', position: 'CENTER' };
    case 'hide':
      return { mode: 'character' };
    case 'if':
      return { scope: '', var: '', condition: 'equal', value: '', _target: '' };
    case 'setVar':
      return { scope: '', var: '', operation: 'set', value: '' };
    case 'giveItem':
    case 'takeItem':
      return { item: '', amount: 1 };
    case 'playLevel':
      return { level: '', on_complete: '', on_fail: '' };
    case 'unlock':
      return { labels: [] };
    case 'mapSwitch':
      return { map: '', x: 0, y: 0, facing: 'down' };
    default:
      return {};
  }
}

// ── inspector ───────────────────────────────────────────────────────────────

function renderInspector() {
  const body = $('inspector-body');
  body.innerHTML = '';

  if (!state.selected) {
    body.innerHTML = '<div class="empty-state small"><p class="empty-hint">Select a block to edit it.</p></div>';
    return;
  }

  const { index } = state.selected;
  const block = blocks()[index];
  if (!block) {
    body.innerHTML = '<div class="empty-state small"><p class="empty-hint">Select a block to edit it.</p></div>';
    return;
  }

  // A two-block "you are here" glimpse of what sits directly above the block
  // being edited — mobile only, where the editor is hidden behind a pane and
  // the peek is the only at-a-glance orientation. On desktop the whole
  // block list is visible anyway, so the peek would be pure noise.
  if (isMobileLayout()) {
    const peek = contextPeek(index);
    if (peek) body.appendChild(peek);
  }

  const title = document.createElement('div');
  title.className = 'inspector-title';
  title.innerHTML = `<span>${ICONS[block.kind] ?? '•'}</span>${TITLES[block.kind] ?? block.kind}`;

  block.data ??= {};

  // The Duplicate/Delete row goes at the TOP of the panel, not the bottom.
  //
  // It used to be appended last, after every field. For a Show block that means
  // after the mode switch, the character picker, the outfit and expression
  // pickers and the whole placement grid — a screen and a half of scrolling
  // below where you clicked, which reads as "this block has no delete button".
  // Pinning it under the title (sticky, so it stays put while the form scrolls)
  // means the block actions are always exactly where you look first.
  const head = document.createElement('div');
  head.className = 'inspector-head';
  head.appendChild(title);
  head.appendChild(blockActions());
  body.appendChild(head);

  for (const field of fieldsFor(block)) {
    body.appendChild(renderField(block, field));
  }

  // When the line you are writing is a Say, repeating the button at the FOOT
  // of the form saves the scroll-back to the header: thumb finishes the
  // sentence, thumb taps, next line.
  if (block.kind === 'say') {
    const again = document.createElement('button');
    again.className = 'btn ghost say-add-bottom';
    again.textContent = '+ Say';
    again.title = 'Add another Say block right after this one';
    again.onclick = addSayBlock;
    body.appendChild(again);
  }
}

/** Up to two blocks above `index`, as a compact read-only strip. */
function contextPeek(index) {
  if (index <= 0) return null;
  const items = blocks();
  const peek = document.createElement('div');
  peek.className = 'context-peek';

  const label = document.createElement('div');
  label.className = 'context-peek-label';
  label.textContent = 'Above';
  peek.appendChild(label);

  for (let i = Math.max(0, index - 2); i < index; i++) {
    const b = items[i];
    const row = document.createElement('button');
    row.className = 'context-peek-row';
    row.title = `Jump to block ${i + 1}`;
    row.innerHTML = `<span class="block-icon">${ICONS[b.kind] ?? '•'}</span><span class="context-text">${summarise(b)}</span>`;
    row.onclick = () => selectBlock(i);
    peek.appendChild(row);
  }
  return peek;
}

/** Duplicate / Delete, for whichever block is selected. */
function blockActions() {
  const actions = document.createElement('div');
  actions.className = 'inspector-actions';

  const dup = document.createElement('button');
  dup.className = 'btn tiny';
  dup.textContent = 'Duplicate';
  dup.onclick = () => duplicateBlock();

  const del = document.createElement('button');
  del.className = 'btn tiny';
  del.textContent = '🗑 Delete block';
  del.style.color = 'var(--error)';
  del.onclick = () => deleteBlock();

  actions.append(dup, del);
  return actions;
}

/**
 * A plain text field descriptor.
 *
 * Lives at module scope because the field renderers that fall back to raw text
 * (a picker with no matching files, for instance) call it from outside
 * fieldsFor. When it was a const inside fieldsFor, those callers threw
 * "text is not defined" and the inspector showed the error instead of a field.
 */
function textField(key, label, placeholder = '', hint = '') {
  return { key, label, render: () => input(null, key, label, placeholder, hint) };
}

function fieldsFor(block) {
  const d = block.data;
  const all = [];

  const text = textField;
  const area = (key, label, rows = 3) =>
    ({ key, label, render: () => textarea(key, label, rows) });

  switch (block.kind) {
    case 'say':
      all.push(text('label', 'Speaker', 'Cupa — leave empty for narration'));
      all.push(area('content', 'Text', 4));
      break;

    case 'choice':
    case 'nightChoice':
      all.push({ key: 'choices', label: 'Options', render: () => choiceEditor(d) });
      break;

    case 'show': {
      // Two shapes of the same action, exactly as the SDK splits them:
      //
      //   character  show_custom(cupa, "happy", ...)
      //              characters/<id>/<outfit>/<emotion>.png
      //
      //   box        show_custom("asset", "old-dsl", ...)
      //              <folder>/<file>.png
      //
      // The SDK decides by the argument type. Here it is an explicit switch,
      // because an author should not have to know that trick.
      const isBox = d.mode === 'box';

      all.push({ key: 'mode', label: 'Showing', render: () => modeSwitch(d) });

      if (isBox) {
        all.push({ key: 'folder', label: 'Folder', render: () => folderPicker(d) });
        all.push({ key: 'image', label: 'Image', render: () => boxImagePicker(d) });
      } else {
        all.push({ key: 'sprite', label: 'Character', render: () => spritePicker(d) });

        const char = d.sprite || Object.keys(state.project.assets?.characters ?? {})[0];
        const outfits = Object.keys(state.project.assets?.characters?.[char] ?? {});
        all.push({
          key: 'outfit',
          label: 'Outfit',
          render: () => (outfits.length
            ? selectEl(d, 'outfit', outfits.map((o) => ({ value: o, label: o })))
            : text(null, 'outfit', 'Outfit', 'default', 'No outfits found for this character.')),
        });

        const outfit = d.outfit || outfits[0] || 'default';
        const emotions = state.project.assets?.characters?.[char]?.[outfit] ?? [];
        all.push({
          key: 'expression',
          label: 'Expression',
          render: () => (emotions.length
            ? selectEl(d, 'expression', emotions.map((e) => ({ value: e, label: e })))
            : text(null, 'expression', 'Expression', 'normal', 'No images found in that outfit folder.')),
        });
      }

      // The grid: this is show_custom. Every show has these six numbers; the
      // named positions are just presets for them.
      all.push({ key: 'layout', label: 'Placement', render: () => gridEditor(d) });
      break;
    }

    case 'hide': {
      // Show can put two kinds of thing on the stage, so Hide has to be able to
      // take two kinds off it. Same switch, same picks, but without the
      // placement grid: you are removing something, not positioning it.
      const isBox = d.mode === 'box';
      all.push({ key: 'mode', label: 'Hiding', render: () => hideModeSwitch(d) });

      if (isBox) {
        all.push({ key: 'folder', label: 'Folder', render: () => folderPicker(d) });
        all.push({ key: 'image', label: 'Image', render: () => boxImagePicker(d) });
      } else {
        all.push({ key: 'sprite', label: 'Character', render: () => characterSelect(d, 'sprite') });
      }
      break;
    }

    case 'background':
      all.push({ key: 'background', label: 'Image', render: () => backgroundPicker(d) });
      break;

    case 'label':
      all.push(text('name', 'Label name', 'start', 'Jumps target this name. Must be unique across all files.'));
      break;

    case 'jump':
      all.push({ key: 'target', label: 'Go to', render: () => labelPicker(d, 'target') });
      break;

    case 'if': {
      // The Test dropdown comes first because it decides what the rest of the
      // form even is. Day and night take no variable and no value, exactly as
      // in the SDK's condDay/condNight, so those fields disappear rather than
      // sitting there inviting an answer the engine never reads.
      all.push({ key: 'condition', label: 'Test', render: () => conditionPicker(d) });

      const spec = state.meta.conditions[d.condition] || { needs_var: true, needs_value: true };

      if (spec.needs_var !== false) {
        all.push({ key: 'scope', label: 'Save as', render: () => selectEl(d, 'scope', state.meta.scopes) });
        all.push(text('var', 'Variable', 'affection', 'Anything you or the engine sets: affection, seen.night_01, health, advancement.minecraft:nether'));
      }
      if (spec.needs_value !== false) {
        all.push(text('value', 'Value', 'true / 192 / Cupa', 'Numbers and true/false become real values.'));
      }

      // The engine continues when the test PASSES and jumps when it FAILS, so
      // this field is the "otherwise" branch. Labelling it "if true" inverts
      // every writer's first guess.
      all.push({ key: '_target', label: 'Otherwise, jump to', render: () => labelPicker(d, '_target') });
      break;
    }

    case 'next':
      all.push({ key: 'target', label: 'Next beat', render: () => labelPicker(d, 'target') });
      all.push({
        key: '_hint',
        label: '',
        render: () => {
          // This is the progression clock, so explain the two rules that make
          // it work. A writer who puts `next` on a refusal path, or forgets it
          // on a success path, gets a story that stalls or repeats forever.
          const el = document.createElement('div');
          el.className = 'field-hint';
          el.style.cssText = 'margin:-4px 0 12px;line-height:1.5';
          el.innerHTML =
            'Moves the story\'s <b>cursor</b> to this label and saves it with the maid. ' +
            'The next time she is talked to, the scene resumes there.<br><br>' +
            '<b>Put this only on paths that succeeded.</b> A refusal path (wrong time of day, ' +
            'not enough affection) must end without touching the cursor, so it can wait ' +
            'patiently and try again later.';
          return el;
        },
      });
      break;

    case 'setVar':
      all.push({ key: 'scope', label: 'Save as', render: () => selectEl(d, 'scope', state.meta.scopes) });
      all.push(text('var', 'Variable', 'affection.cupa'));
      all.push({
        key: 'operation', label: 'Change',
        render: () => selectEl(d, 'operation', [
          { value: 'set', label: 'set to' },
          { value: 'increment_var', label: 'add' },
          { value: 'subtract_var', label: 'subtract' },
        ]),
      });
      all.push(text('value', 'Value', '10'));
      break;

    case 'unlock':
      all.push({ key: 'labels', label: 'Labels to unlock', render: () => labelListEditor(d) });
      break;

    case 'giveItem':
    case 'takeItem':
      all.push(text('item', 'Item id', 'minecraft:end_rod'));
      all.push({ key: 'amount', label: 'Count', render: () => numberInput(d, 'amount', 1) });
      break;

    case 'playLevel':
      // PvZ Fusion extension: level is a name the PvZ runtime resolves to
      // Fusion's levelNumber. Resume labels are regular global labels.
      all.push(text('level', 'Level name', 'boss_fight_1', 'Custom level name to play, then resume the VN.'));
      all.push({ key: 'on_complete', label: 'On complete, go to', render: () => labelPicker(d, 'on_complete') });
      all.push({ key: 'on_fail', label: 'On fail, go to', render: () => labelPicker(d, 'on_fail') });
      break;

    case 'music':
      all.push({ key: 'music', label: 'Track', render: () => audioPicker(d, 'music', 'music/', '— stop music —') });
      break;

    case 'sound':
      all.push({ key: 'sound', label: 'Sound', render: () => audioPicker(d, 'sound', 'sound/', '— none —') });
      break;

    case 'idle':
    case 'end':
    case 'clearBackground':
      // These carry no data. An empty inspector is correct; a text box would
      // invite the writer to type something the compiler silently drops.
      break;

    default:
      break;
  }

  return all;
}

// ── field renderers ─────────────────────────────────────────────────────────

// A field descriptor is { key, label, render }. The render function returns an
// already-wrapped element; this is the single place the inspector calls it, so
// a field that throws is caught and shown instead of killing the whole panel.
function renderField(_block, field) {
  try {
    return field.render();
  } catch (err) {
    const el = document.createElement('div');
    el.className = 'field';
    el.innerHTML = `<div class="field-label">${field.label}</div>
      <div class="field-hint" style="color:var(--error)">Could not render this field: ${String(err.message ?? err)}</div>`;
    return el;
  }
}


function wrapField(label, node, hint) {
  const wrap = document.createElement('div');
  wrap.className = 'field';

  const lab = document.createElement('label');
  lab.className = 'field-label';
  lab.textContent = label;
  wrap.appendChild(lab);
  wrap.appendChild(node);

  if (hint) {
    const h = document.createElement('div');
    h.className = 'field-hint';
    h.textContent = hint;
    wrap.appendChild(h);
  }
  return wrap;
}

function commit() {
  markDirty();
  renderBlocks();
  renderOutline();
  updateCounts();
}

function input(_kind, key, label, placeholder, hint) {
  const el = document.createElement('input');
  el.value = current().data[key] ?? '';
  el.placeholder = placeholder || '';
  el.oninput = () => {
    current().data[key] = el.value;
    commit();
  };
  return wrapField(label, el, hint);
}

function textarea(key, label, rows) {
  const el = document.createElement('textarea');
  el.rows = rows;
  el.value = current().data[key] ?? '';
  el.oninput = () => {
    current().data[key] = el.value;
    commit();
  };
  return wrapField(label, el);
}

function numberInput(data, key, min = 1) {
  const el = document.createElement('input');
  el.type = 'number';
  el.min = min;
  el.value = data[key] ?? min;
  el.oninput = () => {
    data[key] = Number(el.value) || min;
    commit();
  };
  return wrapField('Count', el);
}

function selectEl(data, key, options, label = key) {
  const el = document.createElement('select');
  for (const opt of options) {
    const option = document.createElement('option');
    option.value = opt.value;
    option.textContent = opt.label;
    el.appendChild(option);
  }
  el.value = data[key] ?? '';
  el.onchange = () => {
    data[key] = el.value;
    commit();
    renderInspector();
  };
  return wrapField(label, el);
}

function conditionPicker(data) {
  const el = document.createElement('select');
  for (const [value, def] of Object.entries(state.meta.conditions)) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = def.label;
    el.appendChild(option);
  }
  el.value = data.condition ?? 'equal';
  el.onchange = () => {
    data.condition = el.value;
    commit();
    renderInspector();
  };
  return wrapField('Test', el);
}

/**
 * Optional variable that chooses the outfit at runtime.
 *
 * The SDK writes a second path for this:
 *   characters/<id>/<outfit_var>/<emotion>.png
 * so a script can dress a character differently without branching its own
 * Show blocks. Leave empty to use the fixed outfit above.
 */
function outfitVarField(d) {
  const el = document.createElement('input');
  el.value = d.outfit_var ?? '';
  el.placeholder = 'e.g. cupa_outfit';
  el.oninput = () => {
    const v = el.value.trim();
    if (v) d.outfit_var = v;
    else delete d.outfit_var;
    commit();
  };
  return wrapField(
    'Outfit from variable (optional)',
    el,
    'When set, the engine builds characters/<id>/<variable>/<emotion>.png and uses it if the variable is defined.'
  );
}

/**
 * Backgrounds live in images/asset/ and are referenced with that prefix:
 * "asset/end.png". Offering the real files beats making the author remember
 * the folder name.
 */
function backgroundPicker(d) {
  const options = state.project.assets?.backgrounds ?? [];
  if (options.length === 0) {
    return textField(null, 'background', 'Image', 'asset/end.png', 'No backgrounds found in images/asset/. Free text for now.');
  }

  const el = document.createElement('select');
  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = '— keep the world —';
  el.appendChild(blank);

  for (const bg of options) {
    const option = document.createElement('option');
    option.value = bg;
    option.textContent = bg;
    el.appendChild(option);
  }
  el.value = d.background ?? '';
  el.onchange = () => {
    d.background = el.value;
    commit();
  };
  return wrapField('Image', el);
}

/**
 * Pick a track or sound effect from the project's sounds/ folder.
 *
 * The engine wants the bare name — "haggstrom" — not the path, because it
 * resolves against its own sound event table. Stripping the folder and the
 * extension here means the block summary reads the way a script does.
 */
function audioPicker(d, key, prefix, emptyLabel) {
  const source = key === 'music'
    ? (state.project.assets?.music ?? [])
    : (state.project.assets?.sounds ?? []);

  const names = source
    .filter((p) => p.startsWith(prefix))
    .map((p) => p.slice(prefix.length).replace(/\.(ogg|wav|mp3)$/i, ''));

  if (names.length === 0) {
    return textField(null, key, key === 'music' ? 'Track (empty = stop)' : 'Sound',
      key === 'music' ? 'haggstrom' : 'teleport',
      `No files found in sounds/${prefix}`);
  }

  const el = document.createElement('select');
  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = emptyLabel;
  el.appendChild(blank);

  for (const name of names) {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    el.appendChild(option);
  }
  el.value = d[key] ?? '';
  el.onchange = () => {
    if (el.value) d[key] = el.value;
    else delete d[key];
    commit();
  };
  return wrapField(key === 'music' ? 'Track' : 'Sound', el);
}

/**
 * Visual editor for the grid placement system.
 *
 * The original renderer, from ForegroundComponent, is a grid:
 *
 *     int wBlocks = (int) (width / wRatio);              // cell width
 *     int hBlocks = (int) (height / hRatio);             // cell height
 *     int wThing  = (int) (wBlocks * frameWRatio);       // sprite width
 *     int hThing  = (int) (hBlocks * frameHRatio);       // sprite height
 *     int x = (int) (wBlocks * (startColumn - 1));       // 1-based!
 *     int y = (int) (hBlocks * (startRow - 1));
 *
 * So six numbers describe a rectangular patch of a wRatio-by-hRatio grid, and
 * the sprite is stretched to fill it. That is the whole layout engine.
 *
 * The editor shows the grid, lets you drag the frame, and reports the numbers
 * that the script would otherwise need to be computed by hand.
 */
const GRID_DEFAULTS = { wRatio: 16, hRatio: 9, wFrameRatio: 4, hFrameRatio: 8, column: 7, row: 1 };

const POSITION_PRESETS = {
  CENTER: { wFrameRatio: 4, hFrameRatio: 8, column: 7, row: 1 },
  LEFT:   { wFrameRatio: 4, hFrameRatio: 8, column: 1, row: 1 },
  RIGHT:  { wFrameRatio: 4, hFrameRatio: 8, column: 13, row: 1 },
};

function gridEditor(d) {
  const wrap = document.createElement('div');

  // A show with no explicit numbers uses the engine's defaults.
  d.layout ??= { ...GRID_DEFAULTS, preset: 'CENTER' };

  const layout = d.layout;

  // ── preset row ──
  const presets = document.createElement('div');
  presets.style.cssText = 'display:flex;gap:4px;margin-bottom:8px';

  for (const [name, values] of Object.entries(POSITION_PRESETS)) {
    const btn = document.createElement('button');
    btn.className = 'btn tiny';
    btn.textContent = name.toLowerCase();
    btn.style.flex = '1';
    btn.onclick = () => {
      Object.assign(layout, values);
      layout.preset = name;
      commit();
      renderInspector();
    };
    presets.appendChild(btn);
  }

  const customBtn = document.createElement('button');
  customBtn.className = 'btn tiny';
  customBtn.textContent = 'custom';
  customBtn.style.flex = '1';
  customBtn.onclick = () => {
    layout.preset = 'CUSTOM';
    commit();
    renderInspector();
  };
  presets.appendChild(customBtn);
  wrap.appendChild(presets);

  // ── the grid ──
  const canvas = document.createElement('div');
  canvas.style.cssText =
    'position:relative;width:100%;aspect-ratio:16/9;background:#0d0f12;' +
    'border:1px solid var(--line);border-radius:4px;overflow:hidden;cursor:crosshair';

  // grid lines
  const cols = Math.max(1, Number(layout.wRatio) || 16);
  const rows = Math.max(1, Number(layout.hRatio) || 9);
  canvas.style.backgroundImage =
    `linear-gradient(to right, #1e232a 1px, transparent 1px),` +
    `linear-gradient(to bottom, #1e232a 1px, transparent 1px)`;
  canvas.style.backgroundSize = `${100 / cols}% ${100 / rows}%`;

  // the frame
  const frame = document.createElement('div');
  frame.style.cssText =
    'position:absolute;border:2px solid var(--accent);background:rgba(111,168,220,.18);' +
    'box-sizing:border-box;pointer-events:none';

  const applyFrame = () => {
    const col = Math.max(1, Math.min(cols, Number(layout.column) || 1));
    const row = Math.max(1, Math.min(rows, Number(layout.row) || 1));
    const w = Math.max(1, Number(layout.wFrameRatio) || 4);
    const h = Math.max(1, Number(layout.hFrameRatio) || 8);

    frame.style.left = `${((col - 1) / cols) * 100}%`;
    frame.style.top = `${((row - 1) / rows) * 100}%`;
    frame.style.width = `${(w / cols) * 100}%`;
    frame.style.height = `${(h / rows) * 100}%`;

    // A frame hanging off the edge is the single most common layout mistake:
    // it renders partially or not at all, with no error.
    const overflowX = col - 1 + w > cols;
    const overflowY = row - 1 + h > rows;
    frame.style.borderColor = overflowX || overflowY ? 'var(--error)' : 'var(--accent)';
    frame.style.background = overflowX || overflowY
      ? 'rgba(217,92,92,.18)'
      : 'rgba(111,168,220,.18)';
  };

  applyFrame();
  canvas.appendChild(frame);

  // click to move the frame
  canvas.onclick = (event) => {
    const rect = canvas.getBoundingClientRect();
    const fx = (event.clientX - rect.left) / rect.width;
    const fy = (event.clientY - rect.top) / rect.height;
    layout.column = Math.max(1, Math.min(cols, Math.floor(fx * cols) + 1));
    layout.row = Math.max(1, Math.min(rows, Math.floor(fy * rows) + 1));
    layout.preset = 'CUSTOM';
    commit();
    renderInspector();
  };

  wrap.appendChild(canvas);

  // ── the six numbers ──
  const grid = document.createElement('div');
  grid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px';

  const numeric = (key, label, min, max) => {
    const cell = document.createElement('div');
    const lab = document.createElement('div');
    lab.className = 'field-label';
    lab.textContent = label;
    const el = document.createElement('input');
    el.type = 'number';
    el.min = min;
    el.max = max ?? '';
    el.value = layout[key] ?? GRID_DEFAULTS[key];
    el.style.cssText = 'width:100%;padding:4px 6px;background:var(--bg);color:var(--text);' +
      'border:1px solid var(--line);border-radius:4px;font:inherit;font-size:12px';
    el.oninput = () => {
      layout[key] = Number(el.value);
      layout.preset = 'CUSTOM';
      applyFrame();
      commit();
    };
    cell.append(lab, el);
    return cell;
  };

  grid.append(
    numeric('wRatio', 'Screen columns', 1),
    numeric('hRatio', 'Screen rows', 1),
    numeric('wFrameRatio', 'Sprite cells wide', 1),
    numeric('hFrameRatio', 'Sprite cells tall', 1),
    numeric('column', 'Start column (1 = left)', 1),
    numeric('row', 'Start row (1 = top)', 1),
  );
  wrap.appendChild(grid);

  // ── readout ──
  const readout = document.createElement('div');
  readout.className = 'field-hint';
  readout.style.marginTop = '6px';

  const col = Number(layout.column) || 1;
  const row = Number(layout.row) || 1;
  const w = Number(layout.wFrameRatio) || 4;
  const h = Number(layout.hFrameRatio) || 8;
  const offX = col - 1 + w > cols;
  const offY = row - 1 + h > rows;

  const spansX = ((w / cols) * 100).toFixed(0);
  const spansY = ((h / rows) * 100).toFixed(0);

  readout.innerHTML = `Occupies ${spansX}% × ${spansY}% of the screen, ` +
    `from cell ${col},${row}` +
    (offX || offY ? ' — <b style="color:var(--error)">hangs off the edge</b>' : '');
  wrap.appendChild(readout);

  return wrapField('Placement', wrap);
}

/**
 * Character sprite or plain image box.
 *
 * Same action, same grid, different path. The SDK distinguishes them by
 * whether the first argument is a Character or a string; making it a visible
 * switch is kinder than expecting the author to know that.
 */
function modeSwitch(d) {
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;gap:4px';

  for (const [value, label] of [['character', 'Character'], ['box', 'Image box']]) {
    const btn = document.createElement('button');
    btn.className = 'btn tiny';
    btn.textContent = label;
    btn.style.flex = '1';
    const active = (d.mode || 'character') === value;
    if (active) {
      btn.style.borderColor = 'var(--accent)';
      btn.style.color = 'var(--accent)';
    }
    btn.onclick = () => {
      d.mode = value;
      if (value === 'box') {
        d.folder ??= 'asset';
        d.image ??= '';
        // A wide box suits a screenshot or a diagram, not a character.
        d.layout ??= {};
        d.layout.wRatio ??= 16;
        d.layout.hRatio ??= 9;
        d.layout.wFrameRatio ??= 10;
        d.layout.hFrameRatio ??= 6;
        d.layout.column ??= 6;
        d.layout.row ??= 1;
        d.layout.preset ??= 'CUSTOM';
      }
      commit();
      renderInspector();
    };
    wrap.appendChild(btn);
  }
  return wrapField('Showing', wrap);
}

/**
 * Folders under images/ that hold plain images.
 *
 * A box is show_custom(<folder>, <image>, ...), so the folder name is whatever
 * the author created — "asset" is only the one the original demo used. This
 * lists all of them, so dropping images/ui/ into the project makes "ui"
 * selectable without touching code.
 */
function folderPicker(d) {
  const folders = Object.keys(state.project.assets?.folders ?? {}).sort();

  if (folders.length === 0) {
    return textField(null, 'folder', 'Folder', 'asset',
      'No image folders yet. Create images/<name>/ and drop images in it.');
  }

  return selectEl(d, 'folder', folders.map((f) => ({ value: f, label: f })), 'Folder');
}

/** Images inside the chosen folder. */
function boxImagePicker(d) {
  const folder = d.folder || 'asset';
  const images = state.project.assets?.folders?.[folder] ?? [];

  if (images.length === 0) {
    return textField(null, 'image', 'Image', 'old-dsl', `No images found in images/${folder}/`);
  }

  const el = document.createElement('select');
  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = '— pick an image —';
  el.appendChild(blank);

  for (const name of images) {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    el.appendChild(option);
  }
  el.value = d.image ?? '';
  el.onchange = () => {
    d.image = el.value;
    commit();
  };
  return wrapField('Image', el);
}

/**
 * Character or image box — the Hide block's half of the Show switch.
 *
 * Deliberately separate from modeSwitch(): that one carries the six-number
 * placement defaults a Show needs when it flips to a box, and a Hide has no
 * placement. Sharing it would write layout data onto a block that removes
 * things.
 */
function hideModeSwitch(d) {
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;gap:4px';

  for (const [value, label] of [['character', 'Character'], ['box', 'Image box']]) {
    const btn = document.createElement('button');
    btn.className = 'btn tiny';
    btn.textContent = label;
    btn.style.flex = '1';
    if ((d.mode || 'character') === value) {
      btn.style.borderColor = 'var(--accent)';
      btn.style.color = 'var(--accent)';
    }
    btn.onclick = () => {
      d.mode = value;
      if (value === 'box') {
        d.folder ??= 'asset';
        d.image ??= '';
      }
      commit();
      renderInspector();
    };
    wrap.appendChild(btn);
  }
  return wrapField('Hiding', wrap);
}

/**
 * A dropdown of the characters that actually have sprites on disk.
 *
 * Used by Hide (and by Show, which wraps it to add its delete button). A
 * free-text field here was a trap: a typo in a character id hides nothing and
 * reports nothing, because the engine just looks up a sprite that does not
 * exist. Falls back to text only when the project has no sprites at all, so a
 * project mid-setup is still authorable.
 */
function characterSelect(data, key) {
  const chars = Object.keys(state.project.assets?.characters ?? {});

  if (chars.length === 0) {
    return input(null, key, 'Character', 'cupa', 'No sprites found in assets/. Free text for now.');
  }

  const el = document.createElement('select');
  for (const name of chars) {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    el.appendChild(option);
  }

  // No value yet: show an explicit empty choice rather than preselecting the
  // first character. A dropdown that displays "andr" while the block stores
  // nothing is a lie the compile then turns into "hide the default sprite".
  if (!data[key]) {
    const blank = document.createElement('option');
    blank.value = '';
    blank.textContent = '— pick a character —';
    el.insertBefore(blank, el.firstChild);
  }

  // A value that is not on disk (a hand-typed id, or sprites deleted since) is
  // kept as a selected option rather than silently snapping to the first
  // character — otherwise opening the block would rewrite what it says.
  if (data[key] && !chars.includes(data[key])) {
    const stale = document.createElement('option');
    stale.value = data[key];
    stale.textContent = `${data[key]} (not on disk)`;
    el.appendChild(stale);
  }

  el.value = data[key] ?? '';
  el.onchange = () => {
    if (el.value) data[key] = el.value;
    else delete data[key];
    commit();
  };
  return wrapField('Character', el);
}

function spritePicker(data) {
  const chars = Object.keys(state.project.assets?.characters ?? {});
  if (chars.length === 0) {
    return input(null, 'sprite', 'Character', 'cupa', 'No sprites found in assets/. Free text for now.');
  }

  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;gap:4px;align-items:center';

  const select = document.createElement('select');
  for (const name of chars) {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  }
  select.value = data.sprite ?? chars[0] ?? '';
  select.style.flex = '1 1 auto';
  select.style.minWidth = '0';
  select.onchange = () => {
    data.sprite = select.value;
    // The outfit and expression lists belong to the character that was just
    // picked, so the rest of the form has to be rebuilt around it.
    commit();
    renderInspector();
  };

  // Deleting the character's whole sprite folder from here: it is the one place
  // the mistake is visible ("this character has no images"), so the fix belongs
  // next to it rather than four clicks away in the asset window.
  const del = document.createElement('button');
  del.className = 'btn tiny';
  del.textContent = '🗑';
  del.title = 'Delete this character\'s sprite folder';
  del.style.color = 'var(--error)';
  del.onclick = async () => {
    const character = data.sprite || select.value;
    if (!character) return;
    const path = `images/characters/${character}`;
    if (!confirm(`Delete every sprite for "${character}"?\n\n${path}\n\nThis removes the folder from disk and cannot be undone.`)) return;
    try {
      await deleteAssetPath(path);
    } catch (err) {
      alert(String(err.message ?? err));
    }
  };

  wrap.append(select, del);
  return wrapField('Character', wrap, 'The 🗑 deletes this character\'s images from the project.');
}

function labelPicker(data, key) {
  const labels = collectLabels();
  const el = document.createElement('select');

  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = '— pick a label —';
  el.appendChild(blank);

  for (const [file, names] of labels) {
    const group = document.createElement('optgroup');
    group.label = file.replace(/\.story$/, '');
    for (const name of names) {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      group.appendChild(option);
    }
    el.appendChild(group);
  }

  el.value = data[key] ?? '';
  el.onchange = () => {
    data[key] = el.value;
    commit();
  };
  return wrapField(key === '_target' ? 'Jump target' : 'Go to', el);
}

function labelListEditor(data) {
  const wrap = document.createElement('div');
  const labels = collectLabels();

  data.labels ??= [];

  const chosen = document.createElement('div');
  chosen.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px';

  for (const name of data.labels) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.textContent = name;
    chip.style.cursor = 'pointer';
    chip.title = 'Remove';
    chip.onclick = () => {
      data.labels = data.labels.filter((n) => n !== name);
      commit();
      renderInspector();
    };
    chosen.appendChild(chip);
  }

  const add = document.createElement('select');
  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = '— add a label —';
  add.appendChild(blank);
  for (const [file, names] of labels) {
    for (const name of names) {
      if (data.labels.includes(name)) continue;
      const option = document.createElement('option');
      option.value = name;
      option.textContent = `${file.replace(/\.story$/, '')} · ${name}`;
      add.appendChild(option);
    }
  }
  add.onchange = () => {
    if (!add.value) return;
    data.labels.push(add.value);
    commit();
    renderInspector();
  };

  wrap.append(chosen, add);
  return wrapField('Labels to unlock', wrap, 'These become eligible for Idle Chat.');
}

function choiceEditor(data) {
  const wrap = document.createElement('div');
  data.choices ??= [];

  data.choices.forEach((choice, i) => {
    const row = document.createElement('div');
    row.style.cssText = 'display:grid;grid-template-columns:1fr 1fr 22px;gap:4px;margin-bottom:4px;align-items:center';

    const display = document.createElement('input');
    display.placeholder = 'Shown text';
    display.value = choice.display ?? '';
    display.oninput = () => {
      choice.display = display.value;
      commit();
    };

    const label = document.createElement('select');
    const blank = document.createElement('option');
    blank.value = '';
    blank.textContent = 'jump to…';
    label.appendChild(blank);
    for (const [file, names] of collectLabels()) {
      const group = document.createElement('optgroup');
      group.label = file.replace(/\.story$/, '');
      for (const name of names) {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        group.appendChild(option);
      }
      label.appendChild(group);
    }
    label.value = choice.label ?? '';
    label.onchange = () => {
      choice.label = label.value;
      commit();
    };

    const del = document.createElement('button');
    del.className = 'btn tiny ghost';
    del.textContent = '✕';
    del.onclick = () => {
      data.choices.splice(i, 1);
      commit();
      renderInspector();
    };

    row.append(display, label, del);
    wrap.appendChild(row);
  });

  const add = document.createElement('button');
  add.className = 'btn tiny';
  add.textContent = '+ option';
  add.onclick = () => {
    data.choices.push({ label: '', display: '' });
    commit();
    renderInspector();
  };
  wrap.appendChild(add);

  return wrapField('Options', wrap);
}

function current() {
  return blocks()[state.selected.index];
}

// ── outline ─────────────────────────────────────────────────────────────────

function collectLabels() {
  const byFile = new Map();
  for (const file of state.project?.meta?.files ?? []) {
    const names = [];
    for (const block of state.project.files[file] ?? []) {
      if (block.kind === 'label' && block.data?.name) names.push(block.data.name);
    }
    if (names.length) byFile.set(file, names);
  }
  return byFile;
}

function renderOutline() {
  const body = $('outline-body');
  body.innerHTML = '';

  const labels = collectLabels();
  if (labels.size === 0) {
    body.innerHTML = '<div class="empty-state small"><p class="empty-hint">Labels appear here.</p></div>';
    return;
  }

  for (const [file, names] of labels) {
    const wrap = document.createElement('div');
    wrap.className = 'outline-file';

    const head = document.createElement('div');
    head.className = 'outline-file-name';
    head.textContent = file.replace(/\.story$/, '');
    wrap.appendChild(head);

    for (const name of names) {
      const btn = document.createElement('button');
      btn.className = 'outline-label';
      btn.textContent = name;
      btn.onclick = () => {
        state.activeFile = file;
        const index = state.project.files[file].findIndex((b) => b.kind === 'label' && b.data?.name === name);
        state.selected = { file, index };
        renderTabs();
        renderBlocks();
        renderInspector();
        document.querySelector('.block.selected')?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      };
      wrap.appendChild(btn);
    }
    body.appendChild(wrap);
  }
}

// ── block ops ───────────────────────────────────────────────────────────────

function duplicateBlock() {
  const items = blocks();
  const copy = structuredClone(items[state.selected.index]);
  items.splice(state.selected.index + 1, 0, copy);
  state.selected.index += 1;
  markDirty();
  renderBlocks();
  renderInspector();
  updateCounts();
}

function deleteBlock() {
  const items = blocks();
  items.splice(state.selected.index, 1);
  state.selected = null;
  markDirty();
  renderBlocks();
  renderInspector();
  renderOutline();
  updateCounts();
}

function markDirty() {
  state.dirty = true;
  $('project-name').classList.add('dirty');
  renderTabs();
  scheduleAutosave();
}

/** Start (or restart) the idle timer that writes the project to disk. */
function scheduleAutosave(delay = AUTOSAVE_DELAY) {
  if (!state.project) return;
  clearTimeout(autosave.timer);
  autosave.timer = setTimeout(() => {
    autosave.timer = null;
    save({ silent: true });
  }, delay);
}

/** Write now if anything is pending. Used before switching or previewing. */
async function flushAutosave() {
  if (autosave.timer) {
    clearTimeout(autosave.timer);
    autosave.timer = null;
  }
  if (state.dirty || autosave.inFlight) await save({ silent: true });
}

function updateCounts() {
  let total = 0;
  for (const file of state.project?.meta?.files ?? []) {
    total += (state.project.files[file] ?? []).length;
  }
  const labels = [...collectLabels().values()].reduce((n, arr) => n + arr.length, 0);
  $('status-blocks').textContent = `${total} block${total === 1 ? '' : 's'}`;
  $('status-labels').textContent = `${labels} label${labels === 1 ? '' : 's'}`;
}

function setStatus(which, text, level = '') {
  const el = $(`status-${which}`);
  if (!el) return;
  el.textContent = text;
  el.className = 'status-item' + (level ? ` ${level}` : '');
}

// ── chrome ──────────────────────────────────────────────────────────────────

function wireChrome() {
  $('btn-new').onclick = newProject;
  $('btn-assets').onclick = () => openAssets();
  $('btn-compile').onclick = validate;
  $('btn-export').onclick = exportPack;
  $('btn-play').onclick = play;
  $('btn-save').onclick = () => save();
  $('btn-duplicate').onclick = duplicateProject;
  $('btn-rename').onclick = renameProject;
  $('btn-delete').onclick = deleteProject;
  $('btn-import').onclick = () => $('file-import').click();
  $('btn-add-say').onclick = addSayBlock;
  document.getElementById('project-select').onchange = (e) => { if (e.target.value) openProject(e.target.value); };
  document.getElementById('file-import').onchange = importProjectFile;

  // Last line of defence: the tab is closing mid-edit, before the debounce
  // fired. `keepalive` lets the request outlive the page. Browsers cap such
  // bodies at 64 KB, so a big project simply loses the race — the debounce
  // covers all but the last ~second of typing anyway.
  window.addEventListener('beforeunload', () => {
    if (!state.project || !state.dirty || autosave.inFlight) return;
    const blob = new Blob([JSON.stringify(saveBody())], { type: 'application/json' });
    if (blob.size > 60000) return;
    fetch(`/api/projects/${state.project.slug}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: blob,
      keepalive: true,
    }).catch(() => {});
  });

  // Ctrl+S saves, Ctrl+Enter validates.
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      save();
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      validate();
    }
    if (e.key === 'Delete' && state.selected && document.activeElement?.tagName === 'BODY') {
      deleteBlock();
    }
  });
}

async function newProject() {
  const slug = prompt('Project name (lowercase, no spaces)');
  if (!slug) return;
  const packName = prompt('Story title', slug) || slug;

  const res = await fetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug, meta: { packName, character: slug } }),
  });

  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || 'Could not create the project.');
    return;
  }
  await openProject(slug);
}

/** The exact payload the server expects, built from live state. */
function saveBody(project = state.project) {
  const body = { meta: project.meta, files: {} };
  for (const file of project.meta.files) {
    body.files[file] = project.files[file] ?? [];
  }
  return body;
}

/**
 * Write the project to disk.
 *
 * `silent` is the autosave path: a failure shows in the status bar and retries
 * instead of throwing a modal in your face mid-sentence. A manual save (button,
 * Ctrl+S) still complains loudly, because you asked for it.
 */
async function save({ silent = false } = {}) {
  if (!state.project) return false;

  if (autosave.timer) {
    clearTimeout(autosave.timer);
    autosave.timer = null;
  }

  // One write at a time. Queue and let the in-flight save re-schedule, so two
  // PUTs cannot race on the same files and undo each other.
  if (autosave.inFlight) {
    autosave.queued = true;
    return autosave.inFlight;
  }

  const project = state.project;
  const body = saveBody(project);

  autosave.inFlight = (async () => {
    try {
      const res = await fetch(`/api/projects/${project.slug}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Save failed (${res.status})`);
      }

      // Only clear the flag if the project on screen is still the one written —
      // a save finishing after a switch must not mark the new project clean.
      if (state.project === project) {
        state.dirty = false;
        $('project-name').classList.remove('dirty');
        renderTabs();
        setStatus('compile', silent ? 'autosaved' : 'saved', 'ok');
        if (state.lastCompile) {
          setTimeout(() => {
            if (!state.dirty) setStatus('compile', state.lastCompile);
          }, 2500);
        }
      }
      return true;
    } catch (err) {
      const message = String(err.message ?? err);
      if (state.project === project) {
        setStatus('compile', `save failed — ${message}`, 'error');
        if (silent) {
          clearTimeout(autosave.retry);
          autosave.retry = setTimeout(() => scheduleAutosave(0), 4000);
        } else {
          alert(message);
        }
      }
      return false;
    } finally {
      autosave.inFlight = null;
      if (autosave.queued) {
        autosave.queued = false;
        scheduleAutosave(0);
      }
    }
  })();

  return autosave.inFlight;
}

async function validate() {
  if (!state.project) return;
  // Validate compiles the files on disk, so anything still in the debounce
  // window would be reported one edit out of date.
  await flushAutosave();
  setStatus('compile', 'compiling…');

  const res = await fetch(`/api/projects/${state.project.slug}/compile`);
  const result = await res.json();
  state.lastCompile = result;

  const problemCount = result.errors.length + result.warnings.length;
  if (result.errors.length) {
    setStatus('compile', `${result.errors.length} error${result.errors.length === 1 ? '' : 's'}`, 'error');
  } else if (result.warnings.length) {
    setStatus('compile', `${result.warnings.length} warning${result.warnings.length === 1 ? '' : 's'}`, 'warn');
  } else {
    setStatus('compile', `clean · ${result.actionCount} actions`, 'ok');
  }

  if (problemCount) {
    const lines = [
      ...result.errors.map((e) => `ERROR: ${e}`),
      ...result.warnings.map((w) => `warn:  ${w}`),
    ];
    console.log(lines.join('\n'));
    alert(lines.join('\n'));
  }
}

async function exportPack() {
  if (!state.project) return;
  if (state.dirty) { await save(); }
  const fmt = document.getElementById('export-format')?.value || 'pack';
  window.location = `/api/projects/${state.project.slug}/export?format=${encodeURIComponent(fmt)}`;
}

async function duplicateProject() {
  if (!state.project) return;
  const new_slug = prompt('New project name (lowercase, no spaces)', state.project.slug + '-copy');
  if (!new_slug) return;
  const res = await fetch(`/api/projects/${state.project.slug}/duplicate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_slug }),
  });
  if (!res.ok) { alert((await res.json()).detail || 'Duplicate failed'); return; }
  await refreshProjectList();
  await openProject(new_slug);
}

async function renameProject() {
  if (!state.project) return;
  const new_slug = prompt('New project name (lowercase, no spaces)', state.project.slug);
  if (!new_slug || new_slug === state.project.slug) return;
  const res = await fetch(`/api/projects/${state.project.slug}/rename`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_slug }),
  });
  if (!res.ok) { alert((await res.json()).detail || 'Rename failed'); return; }
  await refreshProjectList();
  await openProject(new_slug);
}

async function deleteProject() {
  if (!state.project) return;
  if (!confirm(`Delete project "${state.project.slug}"? This removes its folder and all .story files.`)) return;
  const slug = state.project.slug;
  const res = await fetch(`/api/projects/${slug}`, { method: 'DELETE' });
  if (!res.ok) { alert((await res.json()).detail || 'Delete failed'); return; }
  state.project = null;
  await refreshProjectList();
}

async function importProjectFile(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  const slug = prompt('Project name to import as (lowercase, no spaces)', file.name.replace(/\.hikarin?\.zip$/i, '').replace(/[^a-z0-9_-]/gi, '-').toLowerCase()) || 'imported';
  const buf = await file.arrayBuffer();
  const res = await fetch(`/api/projects/import-zip?slug=${encodeURIComponent(slug)}`, {
    method: 'POST', headers: { 'Content-Type': 'application/zip' }, body: buf,
  });
  e.target.value = '';
  if (!res.ok) { alert((await res.json()).detail || 'Import failed'); return; }
  await refreshProjectList();
  await openProject(slug);
}

// The preview compiles the files on disk, so anything pending is flushed first.
async function play() {
  if (!state.project) return;
  if (state.dirty) {
    setStatus('compile', 'saving before preview…');
    await flushAutosave();
  }
  window.open(`play.html?project=${encodeURIComponent(state.project.slug)}`, '_blank');
}

boot();

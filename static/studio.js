/* Hikarin Studio — editor logic.
 *
 * State lives in `state.projects[slug]`. The server owns the files; this module
 * only needs to render blocks and POST changes back.
 *
 * The editor never assigns action ids — the compiler does. Blocks are
 * {kind, data} and every reference is a label name, so a writer can reorder
 * tabs and blocks freely without breaking anything.
 */

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

// ── boot ────────────────────────────────────────────────────────────────────

async function boot() {
  state.meta = await fetch('/api/meta').then((r) => r.json());
  renderPalette();
  await refreshProjectList();
  wireChrome();
}

async function refreshProjectList() {
  const projects = await fetch('/api/projects').then((r) => r.json());
  if (projects.length === 0) {
    setStatus('compile', 'no projects yet — press New', 'warn');
    return;
  }
  // Auto-open the most recently modified project so a reload resumes work.
  const slug = state.project?.slug ?? projects[projects.length - 1].slug;
  await openProject(slug);
}

async function openProject(slug) {
  const data = await fetch(`/api/projects/${slug}`).then((r) => r.json());
  state.project = data;
  state.activeFile = data.meta.files[0] ?? null;
  state.selected = null;
  state.dirty = false;

  $('project-name').textContent = data.meta.packName || slug;
  $('project-character').textContent = data.meta.character || '—';
  $('btn-play').disabled = false;
  $('btn-export').disabled = false;
  $('btn-compile').disabled = false;
  $('empty-state').hidden = true;
  $('add-block').hidden = false;

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
  label: '🏷️', jump: '➡️', if: '❓', next: '⏭️', end: '🏁',
  setVar: '📝', unlock: '🔓', giveItem: '🎁', takeItem: '✋',
  music: '🎵', sound: '🔊', command: '⌨️',
};

const TITLES = {
  say: 'Say', choice: 'Choice', nightChoice: 'Night Choice', idle: 'Idle Chat',
  show: 'Show Character', hide: 'Hide Character', background: 'Background',
  clearBackground: 'Clear Background', label: 'Label', jump: 'Jump', if: 'If',
  next: 'Resume Point', end: 'End Scene', setVar: 'Set Variable', unlock: 'Unlock',
  giveItem: 'Give Item', takeItem: 'Take Item', music: 'Music', sound: 'Sound',
  command: 'Command',
};

// Blocks the palette shows, in palette order. Not every engine action gets a
// block: conditional_global and modify_global are legacy aliases the compiler
// still reads, but authors use the scoped versions.
const PALETTE = [
  ['talk', ['say', 'choice', 'nightChoice', 'idle']],
  ['stage', ['show', 'hide', 'background', 'clearBackground']],
  ['flow', ['label', 'jump', 'if', 'next', 'end']],
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
    `;

    el.onclick = () => selectBlock(index);
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
    case 'end':
      return '<span class="block-sub">close the screen</span>';
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
    case 'if':
      return { scope: '', var: '', condition: 'equal', value: '', _target: '' };
    case 'setVar':
      return { scope: '', var: '', operation: 'set', value: '' };
    case 'giveItem':
    case 'takeItem':
      return { item: '', amount: 1 };
    case 'unlock':
      return { labels: [] };
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

  const title = document.createElement('div');
  title.className = 'inspector-title';
  title.innerHTML = `<span>${ICONS[block.kind] ?? '•'}</span>${TITLES[block.kind] ?? block.kind}`;
  body.appendChild(title);

  block.data ??= {};

  for (const field of fieldsFor(block)) {
    body.appendChild(renderField(block, field));
  }

  const actions = document.createElement('div');
  actions.style.cssText = 'display:flex;gap:6px;margin-top:16px;padding-top:10px;border-top:1px solid var(--line)';

  const dup = document.createElement('button');
  dup.className = 'btn tiny';
  dup.textContent = 'Duplicate';
  dup.onclick = () => duplicateBlock();

  const del = document.createElement('button');
  del.className = 'btn tiny';
  del.textContent = 'Delete';
  del.style.color = 'var(--error)';
  del.onclick = () => deleteBlock();

  actions.append(dup, del);
  body.appendChild(actions);
}

function fieldsFor(block) {
  const d = block.data;
  const all = [];

  const text = (key, label, placeholder = '', hint = '') =>
    ({ key, label, render: () => input(text, key, label, placeholder, hint) });
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

    case 'hide':
      all.push(text('sprite', 'Character', 'cupa'));
      break;

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

function selectEl(data, key, options) {
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
  return wrapField(key, el);
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
    return text(null, 'background', 'Image', 'asset/end.png', 'No backgrounds found in images/asset/. Free text for now.');
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
    return text(null, key, key === 'music' ? 'Track (empty = stop)' : 'Sound',
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

/** Folders under images/ that hold plain images, e.g. "asset". */
function folderPicker(d) {
  const folders = new Set(Object.keys(state.project.assets?.folders ?? {}));
  // asset/ always exists in a fresh project, so offer it even when empty.
  folders.add('asset');

  return selectEl(d, 'folder', [...folders].sort().map((f) => ({ value: f, label: f })));
}

/** Images inside the chosen folder. */
function boxImagePicker(d) {
  const folder = d.folder || 'asset';
  const images = state.project.assets?.folders?.[folder] ?? [];

  if (images.length === 0) {
    return text(null, 'image', 'Image', 'old-dsl', `No images found in images/${folder}/`);
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

function spritePicker(data) {
  const chars = Object.keys(state.project.assets?.characters ?? {});
  if (chars.length === 0) {
    return input(null, 'sprite', 'Character', 'cupa', 'No sprites found in assets/. Free text for now.');
  }
  return selectEl(data, 'sprite', chars.map((c) => ({ value: c, label: c })));
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
  $('btn-compile').onclick = validate;
  $('btn-export').onclick = exportPack;
  $('btn-play').onclick = play;
  $('btn-save').onclick = save;

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

async function save() {
  if (!state.project) return;

  const body = {
    meta: state.project.meta,
    files: {},
  };
  for (const file of state.project.meta.files) {
    body.files[file] = state.project.files[file] ?? [];
  }

  const res = await fetch(`/api/projects/${state.project.slug}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || 'Save failed.');
    return;
  }

  state.dirty = false;
  $('project-name').classList.remove('dirty');
  renderTabs();
  setStatus('compile', 'saved', 'ok');
  setTimeout(() => state.lastCompile && setStatus('compile', state.lastCompile), 2000);
}

async function validate() {
  if (!state.project) return;
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
  window.location = `/api/projects/${state.project.slug}/export`;
}

// The preview saves first: testing unsaved edits would be a lie, and the
// compiler reads the files on disk.
async function play() {
  if (!state.project) return;
  if (state.dirty) {
    setStatus('compile', 'saving before preview…');
    await save();
  }
  window.open(`play.html?project=${encodeURIComponent(state.project.slug)}`, '_blank');
}

boot();

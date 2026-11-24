/* Hikarin Studio — project manager logic.

Two levels, and this page only ever deals with the first two:

    project  →  a pack: name, format, and a list of stories
    story    →  one story: a character name and some .story files

It never touches blocks. Opening a story hands off to `index.html`, which is the
editor and the only place block data lives.

Everything the manager shows comes from the server. It keeps no copy of a story
list to drift out of sync with disk — after every mutation it re-reads, because
a stale list here is how you end up opening a story that was just deleted.
*/

import { initAssets, openAssets } from './assets.js';

const $ = (id) => document.getElementById(id);

const state = {
  projects: [],       // from /api/projects
  activeSlug: null,
  detail: null,       // from /api/projects/{slug}
  variables: [],      // the selected project's declared globals
  exportFormats: [],  // from /api/meta — the export registry, drawn not hardcoded
  detailTab: 'stories',
  assets: null,       // the selected project's media inventory
  busy: false,
};

// ── boot ────────────────────────────────────────────────────────────────────

async function boot() {
  // Assets belong to the project, so they are managed from here. The same module
  // the editor mounts, keyed by the selected project instead of a story.
  initAssets({
    projectSlug: () => state.activeSlug ?? '',
    assets: () => state.assets,
    setAssets: (assets) => { state.assets = assets; },
    title: () => state.detail?.meta?.packName || state.activeSlug || '',
  });
  wireChrome();
  await loadMeta();
  await refresh();
}

/** The export registry comes from the server, so formats can be added there. */
async function loadMeta() {
  try {
    const meta = await fetch('/api/meta').then((r) => r.json());
    state.exportFormats = meta.exportFormats ?? [];
  } catch {
    state.exportFormats = [];
  }
}

// ── data ────────────────────────────────────────────────────────────────────

async function refresh() {
  state.projects = await fetch('/api/projects').then((r) => r.json());
  renderList();

  if (state.projects.length === 0) {
    state.activeSlug = null;
    state.detail = null;
    renderDetail();
    return;
  }

  // Keep the current selection if it survived; otherwise take the first.
  if (!state.projects.some((p) => p.slug === state.activeSlug)) {
    state.activeSlug = state.projects[0].slug;
  }
  await openProject(state.activeSlug);
}

async function openProject(slug) {
  state.activeSlug = slug;
  renderList();
  const [detail, vars] = await Promise.all([
    fetch(`/api/projects/${slug}`).then((r) => r.json()),
    fetch(`/api/projects/${slug}/variables`).then((r) => r.json()),
  ]);
  state.detail = detail;
  state.variables = vars.variables ?? [];
  renderDetail();
}

// ── left: project list ──────────────────────────────────────────────────────

function renderList() {
  const list = $('project-list');
  list.innerHTML = '';

  if (state.projects.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'manager-empty-note';
    empty.textContent = 'No projects yet. Press "New project" to start one.';
    list.appendChild(empty);
    $('project-total').textContent = '0 projects';
    return;
  }

  for (const p of state.projects) {
    const row = document.createElement('button');
    row.className = 'project-row' + (p.slug === state.activeSlug ? ' active' : '');
    row.onclick = () => openProject(p.slug);

    const name = document.createElement('span');
    name.className = 'project-row-name';
    name.textContent = p.packName || p.slug;

    const meta = document.createElement('span');
    meta.className = 'project-row-meta';
    const n = p.scriptCount ?? 0;
    const c = p.characterCount ?? 0;
    meta.textContent = `${p.slug} · ${c} ${c === 1 ? 'character' : 'characters'} · ${n} ${n === 1 ? 'script' : 'scripts'}`;

    row.appendChild(name);
    row.appendChild(meta);
    list.appendChild(row);
  }

  $('project-total').textContent =
    `${state.projects.length} ${state.projects.length === 1 ? 'project' : 'projects'}`;
}

// ── right: detail ───────────────────────────────────────────────────────────

function renderDetail() {
  const root = $('manager-detail');
  root.innerHTML = '';

  if (!state.detail) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.innerHTML =
      '<p class="empty-title">No project selected</p>' +
      '<p class="empty-hint">Pick a project on the left, or press <b>New project</b>.</p>';
    root.appendChild(empty);
    return;
  }

  const { slug, meta, characters } = state.detail;

  // header
  const head = document.createElement('div');
  head.className = 'detail-head';

  const headLeft = document.createElement('div');
  const title = document.createElement('h1');
  title.className = 'detail-title';
  title.textContent = meta.packName || slug;
  const slugLine = document.createElement('div');
  slugLine.className = 'detail-slug';
  slugLine.textContent = `projects/${slug}/`;
  headLeft.appendChild(title);
  headLeft.appendChild(slugLine);

  const actions = document.createElement('div');
  actions.className = 'detail-actions';
  actions.appendChild(button('🎨 Assets', 'btn', () => openAssets()));
  actions.appendChild(
    button('🧩 Resource Management', 'btn', () => {
      window.location.href = `/rm-editor?project=${encodeURIComponent(slug)}`;
    })
  );
  actions.appendChild(button('Rename', 'btn', () => renameProjectDialog()));
  actions.appendChild(button('Duplicate', 'btn', () => duplicateProject()));
  // Export opens a dialog, because the format and its options are choices, and
  // a one-click export picks them silently. The version number in particular
  // belongs to the pack format, not in the header of every project.
  actions.appendChild(button('📦 Export', 'btn', () => exportDialog()));
  actions.appendChild(button('Delete', 'btn danger', () => deleteProject()));

  head.appendChild(headLeft);
  head.appendChild(actions);
  root.appendChild(head);

  if (meta.description) {
    const desc = document.createElement('p');
    desc.className = 'detail-desc';
    desc.textContent = meta.description;
    root.appendChild(desc);
  }

  // tabs: Stories / Variables. Both are project-level, so both live here.
  const tabs = document.createElement('div');
  tabs.className = 'detail-tabs';
  for (const [key, label] of [['stories', 'Stories'], ['variables', 'Variables']]) {
    const btn = button(label, 'detail-tab' + (state.detailTab === key ? ' active' : ''), () => {
      state.detailTab = key;
      renderDetail();
    });
    btn.dataset.tab = key;
    tabs.appendChild(btn);
  }
  root.appendChild(tabs);

  if (state.detailTab === 'variables') {
    renderVariables(root, slug, meta);
    return;
  }

  renderStories(root, slug, characters);

  // closing note, because the difference is the whole point of this page
  const note = document.createElement('div');
  note.className = 'manager-empty-note';
  note.innerHTML =
    '<b>Project</b> = the pack the runtime installs. <b>Character</b> = one in-game person; ' +
    '<b>Script</b> = one of their conversations, built from its <code>.story</code> tabs. ' +
    'Art in <code>images/</code> and <code>sounds/</code> is shared by every script. ' +
    'Labels are scoped to a script: a Jump can cross <code>.story</code> files, never scripts.';
  root.appendChild(note);
}

function renderStories(root, slug, characters) {
  const sectionHead = document.createElement('div');
  sectionHead.className = 'section-head';
  const sectionTitle = document.createElement('span');
  sectionTitle.className = 'section-title';
  sectionTitle.textContent = 'Characters & scripts';
  sectionHead.appendChild(sectionTitle);
  sectionHead.appendChild(button('+ New character', 'btn tiny', () => createCharacterDialog()));
  root.appendChild(sectionHead);

  const list = document.createElement('div');
  list.className = 'story-list';

  if (characters.length === 0) {
    const note = document.createElement('div');
    note.className = 'manager-empty-note';
    note.innerHTML =
      'This project has nothing yet. Add a <b>character</b> — one in-game person — then give them scripts.';
    list.appendChild(note);
  } else {
    for (const group of characters) {
      list.appendChild(characterGroup(group));
    }
  }

  root.appendChild(list);
}

// One character: a collapsible header naming the person, and their scripts
// inside. The server sends the grouping (character -> scripts), so this is a
// straight render of the tree.
function characterGroup(group) {
  const character = group.character;
  const scripts = group.scripts || [];

  const wrapper = document.createElement('div');
  wrapper.className = 'story-group';

  const head = document.createElement('div');
  head.className = 'story-group-head';
  head.tabIndex = 0;
  head.role = 'button';
  head.setAttribute('aria-expanded', 'false');

  const toggle = document.createElement('span');
  toggle.className = 'story-group-toggle';
  toggle.textContent = '▶';
  toggle.setAttribute('aria-hidden', 'true');
  head.appendChild(toggle);

  const label = document.createElement('span');
  label.className = 'story-group-label';
  label.textContent = character;
  head.appendChild(label);

  const count = document.createElement('span');
  count.className = 'story-group-count';
  count.textContent = `${scripts.length} ${scripts.length === 1 ? 'script' : 'scripts'}`;
  head.appendChild(count);

  // Per-character actions: add a script, delete the whole character.
  const headActions = document.createElement('span');
  headActions.className = 'story-group-actions';
  headActions.appendChild(
    button('+ Script', 'btn tiny', (e) => {
      e.stopPropagation();
      createScriptDialog(character);
    })
  );
  headActions.appendChild(
    button('Delete', 'btn tiny danger', (e) => {
      e.stopPropagation();
      deleteCharacter(character);
    })
  );
  head.appendChild(headActions);

  const scriptList = document.createElement('div');
  scriptList.className = 'story-group-list';
  scriptList.style.display = 'none';
  for (const s of scripts) {
    scriptList.appendChild(storyCard(character, s));
  }

  let expanded = false;
  const toggleGroup = () => {
    expanded = !expanded;
    scriptList.style.display = expanded ? 'flex' : 'none';
    head.setAttribute('aria-expanded', expanded);
    toggle.textContent = expanded ? '▼' : '▶';
  };
  head.onclick = (e) => {
    if (e.target.closest('button')) return;
    toggleGroup();
  };
  head.onkeydown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleGroup();
    }
  };

  wrapper.appendChild(head);
  wrapper.appendChild(scriptList);
  return wrapper;
}

function storyCard(character, s) {
  const card = document.createElement('div');
  card.className = 'story-card';
  card.tabIndex = 0;
  card.onclick = (e) => {
    if (e.target.closest('.story-card-actions')) return;
    openScript(character, s.script);
  };
  card.onkeydown = (e) => {
    if (e.key === 'Enter') openScript(character, s.script);
  };

  const main = document.createElement('div');
  main.className = 'story-card-main';

  const nameRow = document.createElement('div');
  nameRow.className = 'story-card-name';
  nameRow.textContent = s.script;

  const sub = document.createElement('div');
  sub.className = 'story-card-sub';
  const files = s.files || [];
  const filePart = files.length
    ? files.map((f) => f.replace(/\.story$/, '')).join(', ')
    : 'no files';
  sub.textContent = `${filePart} · ${s.blockCount || 0} blocks`;

  main.appendChild(nameRow);
  main.appendChild(sub);

  const cardActions = document.createElement('div');
  cardActions.className = 'story-card-actions';
  cardActions.appendChild(
    button('Rename', 'btn tiny', (e) => {
      e.stopPropagation();
      renameScriptDialog(character, s.script);
    })
  );
  cardActions.appendChild(
    button('Duplicate', 'btn tiny', (e) => {
      e.stopPropagation();
      duplicateScript(character, s.script);
    })
  );
  cardActions.appendChild(
    button('Delete', 'btn tiny danger', (e) => {
      e.stopPropagation();
      deleteScript(character, s.script);
    })
  );

  card.appendChild(main);
  card.appendChild(cardActions);
  return card;
}

function button(text, cls, onclick, title) {
  const b = document.createElement('button');
  b.className = cls;
  b.textContent = text;
  if (title) b.title = title;
  if (onclick) b.onclick = onclick;
  return b;
}

// ── opening a script ────────────────────────────────────────────────────────

function openScript(character, script) {
  // The editor reads ?project=, ?character= and ?script= so a reload returns to
  // the same place, and so a script can be linked to.
  const params = new URLSearchParams({
    project: state.activeSlug,
    character,
    script,
  });
  window.location.href = `/editor?${params.toString()}`;
}

// ── variables ───────────────────────────────────────────────────────────────
//
// The shared variable registry. An author declares a name once and every
// variable field in the editor picks from it — no more typing `affection` three
// ways across one project.
//
// Edits are optimistic-ish: each one sends the whole list and re-renders from
// what the server validated. Same shape as the asset window, for the same
// reason — a local copy is a copy that drifts.

function renderVariables(root, slug, meta) {
  const vars = state.variables ?? [];

  const head = document.createElement('div');
  head.className = 'section-head';
  const title = document.createElement('span');
  title.className = 'section-title';
  title.textContent = `Global variables · ${vars.length}`;
  head.appendChild(title);
  head.appendChild(button('+ New global', 'btn tiny', () => addVariable()));
  root.appendChild(head);

  const intro = document.createElement('div');
  intro.className = 'manager-empty-note';
  intro.innerHTML =
    'A <b>global</b> is shared by every story in this pack, so it is declared once ' +
    'here and picked from a list in the editor. A <b>local</b> belongs to one story ' +
    'and is typed straight into the block — nothing to declare.';
  root.appendChild(intro);

  if (vars.length === 0) {
    const note = document.createElement('div');
    note.className = 'manager-empty-note';
    note.innerHTML =
      'No globals declared yet. Add the names your stories share — ' +
      '<code>affection</code>, <code>story_complete</code> — and the editor will ' +
      'offer them instead of asking you to type them in every block.';
    root.appendChild(note);
    return;
  }

  const list = document.createElement('div');
  list.className = 'var-list';

  for (const v of vars) {
    const row = document.createElement('div');
    row.className = 'var-row';

    const main = document.createElement('div');
    main.className = 'var-main';

    const nameEl = document.createElement('code');
    nameEl.className = 'var-name';
    nameEl.textContent = v.name;

    const typeEl = document.createElement('span');
    typeEl.className = 'var-type';
    typeEl.textContent = v.type || 'number';

    const descEl = document.createElement('div');
    descEl.className = 'var-desc';
    descEl.textContent = v.description || 'no description';

    main.appendChild(nameEl);
    main.appendChild(typeEl);
    main.appendChild(descEl);

    const actions = document.createElement('div');
    actions.className = 'var-actions';
    actions.appendChild(button('Edit', 'btn tiny', () => editVariable(v)));
    actions.appendChild(button('Delete', 'btn tiny danger', () => deleteVariable(v)));

    row.appendChild(main);
    row.appendChild(actions);
    list.appendChild(row);
  }

  root.appendChild(list);

  const note = document.createElement('div');
  note.className = 'manager-empty-note';
  note.innerHTML =
    'Declaring a global does not create it in the engine — it is a name the stories ' +
    'share, not state that exists yet. Removing one never touches the blocks that ' +
    'already use it.';
  root.appendChild(note);
}

/** PUT the whole list; the server validates and returns the saved copy. */
async function writeVariables(entries) {
  const res = await fetch(`/api/projects/${encodeURIComponent(state.activeSlug)}/variables`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ variables: entries }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Could not save the variables.');
  state.variables = data.variables;
  renderDetail();
}

async function addVariable() {
  const name = prompt('Global variable name (letters, numbers, _ and . — e.g. affection)');
  if (!name) return;
  const description = prompt('What is it for?', '') ?? '';
  try {
    await writeVariables([
      ...(state.variables ?? []),
      { name: name.trim(), type: 'number', description },
    ]);
  } catch (e) {
    alert(String(e.message ?? e));
  }
}

async function editVariable(v) {
  const name = prompt('Variable name', v.name);
  if (!name || name.trim() === v.name) return;

  const description = prompt('Description', v.description || '') ?? '';

  const entries = (state.variables ?? []).map((x) =>
    x.name === v.name
      ? { name: name.trim(), type: x.type || 'number', description }
      : x
  );
  try {
    await writeVariables(entries);
  } catch (e) {
    alert(String(e.message ?? e));
  }
}

async function deleteVariable(v) {
  const ok = await confirmDialog(
    'Remove this variable?',
    `"${v.name}" is removed from the declared globals. Stories that already reference it keep ` +
      `working — the engine never needed the declaration — but the editor will not offer it as a pick any more.`,
    'Remove'
  );
  if (!ok) return;
  try {
    await writeVariables((state.variables ?? []).filter((x) => x.name !== v.name));
  } catch (e) {
    alert(String(e.message ?? e));
  }
}

// ── project actions ─────────────────────────────────────────────────────────

async function createProject(meta) {
  const res = await fetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(meta),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Could not create the project.');
  }
  const created = await res.json();
  state.activeSlug = created.slug;
  await refresh();
}

async function renameProject(newSlug) {
  const res = await fetch(
    `/api/projects/${encodeURIComponent(state.activeSlug)}/rename`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_slug: newSlug }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Could not rename.');
  }
  state.activeSlug = newSlug;
  await refresh();
}

async function duplicateProject() {
  const suggested = `${state.activeSlug}_copy`;
  const newSlug = prompt('Duplicate to which project name?', suggested);
  if (!newSlug) return;
  const res = await fetch(
    `/api/projects/${encodeURIComponent(state.activeSlug)}/duplicate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_slug: newSlug }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || 'Could not duplicate.');
    return;
  }
  state.activeSlug = newSlug;
  await refresh();
}

async function deleteProject() {
  const p = state.projects.find((x) => x.slug === state.activeSlug);
  const count = state.detail?.scripts?.length ?? 0;
  const ok = await confirmDialog(
    'Delete project?',
    `This removes projects/${state.activeSlug}/ — ${count} ${
      count === 1 ? 'script' : 'scripts'
    }, every .story file and all of its images and sounds. This cannot be undone.`,
    'Delete project'
  );
  if (!ok) return;

  const res = await fetch(`/api/projects/${encodeURIComponent(state.activeSlug)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    alert('Could not delete.');
    return;
  }
  state.activeSlug = null;
  state.detail = null;
  await refresh();
}

// ── export ──────────────────────────────────────────────────────────────────
//
// Two clicks, deliberately. The format and its options are choices, and a
// one-click export makes them silently — which is how a resource pack gets
// exported and then imported as a project bundle.
//
// The list is drawn from the server's export registry, so adding a format means
// adding one entry to hikarin/export_formats.py. This file never names a format:
// no dropdown to keep in sync, no `if (format === 'pack')` to update.

function exportDialog() {
  const formats = (state.exportFormats ?? []).filter((f) => f.scope === 'project');
  if (!formats.length) return;

  return new Promise((resolve) => {
    const backdrop = $('export-dialog');
    const titleEl = $('export-dialog-title');
    const body = $('export-body');
    const hint = $('export-hint');
    const go = $('export-ok');
    const errEl = $('export-error');

    titleEl.textContent = `Export ${state.detail?.meta?.packName || state.activeSlug}`;
    errEl.hidden = true;
    errEl.textContent = '';

    const selected = { id: formats[0].id };

    body.innerHTML = '';

    // Format list: one row per entry, radio-drawn so it reads as a choice
    // rather than a filter.
    for (const f of formats) {
      const row = document.createElement('label');
      row.className = 'export-option' + (f.id === selected.id ? ' active' : '');

      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'export-format';
      radio.value = f.id;
      radio.checked = f.id === selected.id;
      radio.onchange = () => {
        selected.id = f.id;
        for (const other of body.querySelectorAll('.export-option')) {
          other.classList.toggle('active', other.querySelector('input').checked);
        }
        paint();
      };

      const text = document.createElement('span');
      text.className = 'export-option-text';
      const name = document.createElement('span');
      name.className = 'export-option-name';
      name.textContent = f.label;
      const ext = document.createElement('span');
      ext.className = 'export-option-ext';
      ext.textContent = f.extension;
      text.appendChild(name);
      text.appendChild(ext);

      row.appendChild(radio);
      row.appendChild(text);
      body.appendChild(row);
    }

    // Parameters, drawn from whatever the chosen format declares. A format that
    // needs a version number or a name renders its own inputs.
    const params = document.createElement('div');
    params.className = 'export-params-box';
    params.id = 'export-params';
    body.appendChild(params);

    function paint() {
      const entry = formats.find((f) => f.id === selected.id);
      hint.textContent = entry?.hint || '';
      params.innerHTML = '';

      for (const p of entry?.params ?? []) {
        const label = document.createElement('label');
        label.className = 'export-param';

        const span = document.createElement('span');
        span.className = 'export-param-label';
        span.textContent = p.label || p.key;

        let control;
        if (p.type === 'select' && Array.isArray(p.options)) {
          control = document.createElement('select');
          control.className = 'select';
          for (const o of p.options) {
            const opt = document.createElement('option');
            opt.value = o.value;
            opt.textContent = o.label ?? o.value;
            control.appendChild(opt);
          }
          control.value = p.default ?? p.options[0]?.value ?? '';
        } else {
          control = document.createElement('input');
          control.className = 'input';
          control.type = p.type === 'number' ? 'number' : 'text';
          control.value = p.default ?? '';
        }
        control.dataset.key = p.key;
        control.className += ' export-param-input';
        if (p.hint) {
          control.title = p.hint;
          const ph = document.createElement('span');
          ph.className = 'export-param-hint';
          ph.textContent = p.hint;
          label.appendChild(span);
          label.appendChild(control);
          label.appendChild(ph);
          params.appendChild(label);
          continue;
        }
        label.appendChild(span);
        label.appendChild(control);
        params.appendChild(label);
      }

      go.textContent = `Export ${entry?.extension || ''}`.trim();
    }

    const done = (value) => {
      backdrop.hidden = true;
      cleanup();
      resolve(value);
    };

    const submit = () => {
      const search = new URLSearchParams({ format: selected.id });
      for (const input of params.querySelectorAll('[data-key]')) {
        if (input.value !== '') search.set(input.dataset.key, input.value);
      }
      window.location.href =
        `/api/projects/${encodeURIComponent(state.activeSlug)}/export?${search}`;
      done(selected.id);
    };

    const onKey = (e) => {
      if (e.key === 'Escape') done(null);
    };
    const onClick = (e) => { if (e.target === backdrop) done(null); };
    const cleanup = () => {
      document.removeEventListener('keydown', onKey);
      backdrop.removeEventListener('click', onClick);
      go.onclick = null;
      $('export-cancel').onclick = null;
      $('export-close').onclick = null;
    };

    backdrop.hidden = false;
    paint();
    go.onclick = submit;
    $('export-cancel').onclick = () => done(null);
    $('export-close').onclick = () => done(null);
    document.addEventListener('keydown', onKey);
    backdrop.addEventListener('click', onClick);
  });
}

// ── script actions ──────────────────────────────────────────────────────────

async function createScript(character, script, meta = {}) {
  const res = await fetch(
    `/api/projects/${encodeURIComponent(state.activeSlug)}/scripts`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character, script, meta }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Could not create the script.');
  }
  await openProject(state.activeSlug);
}

async function renameScript(character, script, newSlug, newCharacter) {
  const res = await fetch(
    `/api/projects/${encodeURIComponent(state.activeSlug)}/scripts/${encodeURIComponent(
      character
    )}/${encodeURIComponent(script)}/rename`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_slug: newSlug, character: newCharacter ?? null }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || 'Could not rename the script.');
    return;
  }
  await openProject(state.activeSlug);
}

async function duplicateScript(character, script) {
  const newSlug = prompt('Duplicate script to which name?', `${script}_copy`);
  if (!newSlug) return;
  const res = await fetch(
    `/api/projects/${encodeURIComponent(state.activeSlug)}/scripts/${encodeURIComponent(
      character
    )}/${encodeURIComponent(script)}/duplicate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_slug: newSlug }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || 'Could not duplicate the script.');
    return;
  }
  await openProject(state.activeSlug);
}

async function deleteScript(character, script) {
  const ok = await confirmDialog(
    'Delete script?',
    `This removes the script "${character}/${script}" — its .story files and every block in them. ` +
      `Shared images and sounds stay. This cannot be undone.`,
    'Delete script'
  );
  if (!ok) return;

  const res = await fetch(
    `/api/projects/${encodeURIComponent(state.activeSlug)}/scripts/${encodeURIComponent(
      character
    )}/${encodeURIComponent(script)}`,
    { method: 'DELETE' }
  );
  if (!res.ok) {
    alert('Could not delete the script.');
    return;
  }
  await openProject(state.activeSlug);
}

async function deleteCharacter(character) {
  const ok = await confirmDialog(
    'Delete character?',
    `This removes "${character}" and every script under it — all their .story files and blocks. ` +
      `Shared images and sounds stay. This cannot be undone.`,
    'Delete character'
  );
  if (!ok) return;

  const res = await fetch(
    `/api/projects/${encodeURIComponent(state.activeSlug)}/characters/${encodeURIComponent(
      character
    )}`,
    { method: 'DELETE' }
  );
  if (!res.ok) {
    alert('Could not delete the character.');
    return;
  }
  await openProject(state.activeSlug);
}

// ── dialogs ─────────────────────────────────────────────────────────────────

// The project dialog doubles as create and rename: same fields, different verb.
// Two nearly identical dialogs is how the two drift apart.
/**
 * The project dialog: create or rename a pack.
 *
 * `creating` is what decides whether the slug field is shown and editable. This
 * used to be called `showStory` and also meant "a story field is present", which
 * is how the new-story dialog ended up rendering the project form: it passed
 * `showStory: true` and got pack title, description and a "first story" field
 * for something that needed only a character name.
 */
function projectDialog({ title, okLabel, slug, packName, description, creating, onOk }) {
  return new Promise((resolve) => {
    const backdrop = $('project-dialog');
    $('project-dialog-title').textContent = title;
    $('project-dialog-ok').textContent = okLabel;
    $('pf-slug').value = slug || '';
    $('pf-packname').value = packName || '';
    $('pf-desc').value = description || '';
    $('pf-story').value = '';
    $('pf-error').hidden = true;
    $('pf-error').textContent = '';
    $('pf-story-field').hidden = !creating;
    $('pf-slug').readOnly = !creating;    // a rename keeps the folder name
    backdrop.hidden = false;
    setTimeout(() => (creating ? $('pf-slug') : $('pf-packname')).focus(), 0);

    const done = (value) => {
      backdrop.hidden = true;
      cleanup();
      resolve(value);
    };

    const submit = async () => {
      const errEl = $('pf-error');
      const payload = {
        slug: $('pf-slug').value.trim(),
        packName: $('pf-packname').value.trim(),
        description: $('pf-desc').value.trim(),
      };
      if (creating) {
        payload.story = $('pf-story').value.trim() || payload.slug;
        if (!payload.slug) return showError('Give the project a name.');
      } else if (!payload.packName) {
        return showError('Give the pack a title.');
      }
      $('project-dialog-ok').disabled = true;
      try {
        await onOk(payload);
        done(payload);
      } catch (e) {
        showError(e.message);
      } finally {
        $('project-dialog-ok').disabled = false;
      }
    };

    const showError = (msg) => {
      errEl.textContent = msg;
      errEl.hidden = false;
    };

    const onKey = (e) => {
      if (e.key === 'Escape') done(null);
      if (e.key === 'Enter' && e.target.tagName === 'INPUT') {
        e.preventDefault();
        submit();
      }
    };

    const onClick = (e) => {
      if (e.target === backdrop) done(null);
    };

    const cleanup = () => {
      document.removeEventListener('keydown', onKey);
      backdrop.removeEventListener('click', onClick);
      $('project-dialog-ok').onclick = null;
      $('project-dialog-cancel').onclick = null;
      $('project-dialog-close').onclick = null;
    };

    $('project-dialog-ok').onclick = submit;
    $('project-dialog-cancel').onclick = () => done(null);
    $('project-dialog-close').onclick = () => done(null);
    document.addEventListener('keydown', onKey);
    backdrop.addEventListener('click', onClick);
  });
}

function newProjectDialog() {
  return projectDialog({
    title: 'New project',
    okLabel: 'Create',
    creating: true,
    onOk: async (p) => {
      await createProject({
        slug: p.slug,
        meta: { packName: p.packName, description: p.description },
      });
      if (p.story) {
        // A project starts with one character, so the first character's name is
        // the project's own slug, and it gets one starter script named "main".
        await createScript(p.slug, 'main', { character: p.slug });
      }
    },
  });
}

function renameProjectDialog() {
  const p = state.projects.find((x) => x.slug === state.activeSlug);
  return projectDialog({
    title: 'Rename project',
    okLabel: 'Rename',
    slug: state.activeSlug,
    packName: state.detail?.meta?.packName || '',
    description: state.detail?.meta?.description || '',
    creating: false,
    onOk: async (payload) => {
      await fetch(`/api/projects/${encodeURIComponent(state.activeSlug)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          packName: payload.packName,
          description: payload.description,
        }),
      });
      await openProject(state.activeSlug);
    },
  });
}

function createCharacterDialog() {
  // A character is just a named folder. Creating one makes the group; scripts
  // are added to it afterwards with "+ Script".
  return new Promise((resolve) => {
    const backdrop = $('story-dialog');
    const charEl = $('sf-character');
    const slugEl = $('sf-slug');
    const errEl = $('sf-error');

    $('story-dialog-title').textContent = 'New character';
    $('story-dialog-ok').textContent = 'Create';
    charEl.value = '';
    slugEl.value = '';
    // Hide the second field — a character has only a name.
    slugEl.closest('.field').hidden = true;
    errEl.hidden = true;
    errEl.textContent = '';
    backdrop.hidden = false;
    setTimeout(() => charEl.focus(), 0);

    const showError = (msg) => {
      errEl.textContent = msg;
      errEl.hidden = false;
    };
    const done = (value) => {
      backdrop.hidden = true;
      cleanup();
      resolve(value);
    };
    const submit = async () => {
      const character = charEl.value.trim().toLowerCase().replace(/\s+/g, '_');
      if (!character) return showError('Give the character a name.');
      if (!/^[a-z0-9_-]+$/.test(character)) {
        return showError('Lowercase letters, numbers, - and _ only — it becomes a folder name.');
      }
      $('story-dialog-ok').disabled = true;
      try {
        // A character with one starter script, so the group is never empty.
        await createScript(character, 'main', { character });
        done({ character });
      } catch (e) {
        showError(e.message);
      } finally {
        $('story-dialog-ok').disabled = false;
      }
    };
    const onKey = (e) => {
      if (e.key === 'Escape') done(null);
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
    };
    const onClick = (e) => { if (e.target === backdrop) done(null); };
    const cleanup = () => {
      document.removeEventListener('keydown', onKey);
      backdrop.removeEventListener('click', onClick);
      $('story-dialog-ok').onclick = null;
      $('story-dialog-cancel').onclick = null;
      $('story-dialog-close').onclick = null;
      $('story-dialog-ok').textContent = 'Create';
      slugEl.closest('.field').hidden = false;
      charEl.oninput = null;
    };

    $('story-dialog-ok').onclick = submit;
    $('story-dialog-cancel').onclick = () => done(null);
    $('story-dialog-close').onclick = () => done(null);
    document.addEventListener('keydown', onKey);
    backdrop.addEventListener('click', onClick);
  });
}

function createScriptDialog(character) {
  // Add a script under an existing character. Only the script name is asked —
  // the character is fixed by which group's "+ Script" was clicked.
  return new Promise((resolve) => {
    const backdrop = $('story-dialog');
    const charEl = $('sf-character');
    const slugEl = $('sf-slug');
    const errEl = $('sf-error');

    $('story-dialog-title').textContent = `New script for ${character}`;
    $('story-dialog-ok').textContent = 'Create';
    charEl.value = character;
    slugEl.value = '';
    // The character is fixed here; only the script name is editable.
    charEl.closest('.field').hidden = true;
    slugEl.closest('.field').hidden = false;
    errEl.hidden = true;
    errEl.textContent = '';
    backdrop.hidden = false;
    setTimeout(() => slugEl.focus(), 0);

    const showError = (msg) => {
      errEl.textContent = msg;
      errEl.hidden = false;
    };
    const done = (value) => {
      backdrop.hidden = true;
      cleanup();
      resolve(value);
    };
    const submit = async () => {
      const script = slugEl.value.trim().toLowerCase().replace(/\s+/g, '_');
      if (!script) return showError('Give the script a name.');
      if (!/^[a-z0-9_-]+$/.test(script)) {
        return showError('Lowercase letters, numbers, - and _ only — it becomes a folder name.');
      }
      $('story-dialog-ok').disabled = true;
      try {
        await createScript(character, script, { character });
        done({ character, script });
      } catch (e) {
        showError(e.message);
      } finally {
        $('story-dialog-ok').disabled = false;
      }
    };
    const onKey = (e) => {
      if (e.key === 'Escape') done(null);
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
    };
    const onClick = (e) => { if (e.target === backdrop) done(null); };
    const cleanup = () => {
      document.removeEventListener('keydown', onKey);
      backdrop.removeEventListener('click', onClick);
      $('story-dialog-ok').onclick = null;
      $('story-dialog-cancel').onclick = null;
      $('story-dialog-close').onclick = null;
      $('story-dialog-ok').textContent = 'Create';
      charEl.closest('.field').hidden = false;
      slugEl.closest('.field').hidden = false;
      slugEl.oninput = null;
    };

    $('story-dialog-ok').onclick = submit;
    $('story-dialog-cancel').onclick = () => done(null);
    $('story-dialog-close').onclick = () => done(null);
    document.addEventListener('keydown', onKey);
    backdrop.addEventListener('click', onClick);
  });
}

function renameScriptDialog(character, script) {
  // Rename a script and/or move it under a different character. Both fields are
  // editable: the script name, and the character (which moves the folder).
  return new Promise((resolve) => {
    const backdrop = $('story-dialog');
    const charEl = $('sf-character');
    const slugEl = $('sf-slug');
    const errEl = $('sf-error');

    const existing = { character, script };

    $('story-dialog-title').textContent = 'Rename script';
    $('story-dialog-ok').textContent = 'Rename';
    charEl.value = character;
    slugEl.value = script;
    charEl.closest('.field').hidden = false;
    slugEl.closest('.field').hidden = false;
    // The character field's label reads "Character"; the script field "Script".
    charEl.closest('.field').querySelector('.field-label').textContent = 'Character';
    slugEl.closest('.field').querySelector('.field-label').textContent = 'Script';
    errEl.hidden = true;
    errEl.textContent = '';
    backdrop.hidden = false;
    setTimeout(() => slugEl.focus(), 0);

    const done = (value) => {
      backdrop.hidden = true;
      cleanup();
      resolve(value);
    };
    const submit = async () => {
      const newCharacter = charEl.value.trim().toLowerCase().replace(/\s+/g, '_');
      const newScript = slugEl.value.trim().toLowerCase().replace(/\s+/g, '_');
      if (!newCharacter) { errEl.textContent = 'Give the character a name.'; errEl.hidden = false; return; }
      if (!newScript) { errEl.textContent = 'Give the script a name.'; errEl.hidden = false; return; }
      if (!/^[a-z0-9_-]+$/.test(newCharacter) || !/^[a-z0-9_-]+$/.test(newScript)) {
        errEl.textContent = 'Lowercase letters, numbers, - and _ only.';
        errEl.hidden = false;
        return;
      }
      if (newCharacter === existing.character && newScript === existing.script) {
        return done(null);
      }
      $('story-dialog-ok').disabled = true;
      try {
        await renameScript(existing.character, existing.script, newScript, newCharacter);
        done({ character: newCharacter, script: newScript });
      } catch (e) {
        errEl.textContent = String(e.message ?? e);
        errEl.hidden = false;
      } finally {
        $('story-dialog-ok').disabled = false;
      }
    };
    const onKey = (e) => {
      if (e.key === 'Escape') done(null);
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
    };
    const onClick = (e) => { if (e.target === backdrop) done(null); };
    const cleanup = () => {
      document.removeEventListener('keydown', onKey);
      backdrop.removeEventListener('click', onClick);
      $('story-dialog-ok').onclick = null;
      $('story-dialog-cancel').onclick = null;
      $('story-dialog-close').onclick = null;
      $('story-dialog-ok').textContent = 'Create';
      // Restore the field labels the create dialogs may have hidden.
      charEl.closest('.field').querySelector('.field-label').textContent = 'Character';
      slugEl.closest('.field').querySelector('.field-label').textContent = 'Story name';
      charEl.closest('.field').hidden = false;
      slugEl.closest('.field').hidden = false;
      charEl.oninput = null;
      slugEl.oninput = null;
      slugEl.onfocus = null;
    };

    $('story-dialog-ok').onclick = submit;
    $('story-dialog-cancel').onclick = () => done(null);
    $('story-dialog-close').onclick = () => done(null);
    document.addEventListener('keydown', onKey);
    backdrop.addEventListener('click', onClick);
  });
}

/** Promise-based confirm, because `confirm()` cannot be styled or tested. */
function confirmDialog(title, text, okLabel) {
  return new Promise((resolve) => {
    const backdrop = $('confirm-dialog');
    $('confirm-title').textContent = title;
    $('confirm-text').textContent = text;
    $('confirm-ok').textContent = okLabel || 'Delete';
    backdrop.hidden = false;
    $('confirm-ok').focus();

    const done = (value) => {
      backdrop.hidden = true;
      cleanup();
      resolve(value);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') done(false);
      if (e.key === 'Enter') done(true);
    };
    const onClick = (e) => {
      if (e.target === backdrop) done(false);
    };
    const cleanup = () => {
      document.removeEventListener('keydown', onKey);
      backdrop.removeEventListener('click', onClick);
      $('confirm-ok').onclick = null;
      $('confirm-cancel').onclick = null;
    };

    $('confirm-ok').onclick = () => done(true);
    $('confirm-cancel').onclick = () => done(false);
    document.addEventListener('keydown', onKey);
    backdrop.addEventListener('click', onClick);
  });
}

// ── wiring ──────────────────────────────────────────────────────────────────

function wireChrome() {
  $('btn-new').onclick = () => newProjectDialog();
  $('btn-import').onclick = () => $('file-import').click();
  $('file-import').onchange = importProjectFile;
}

async function importProjectFile(e) {
  const file = e.target.files?.[0];
  e.target.value = '';
  if (!file) return;

  const slug = prompt('Import as which project name?', file.name.replace(/\.hikarin\.zip$|\.zip$/i, ''));
  if (!slug) return;

  const buf = await file.arrayBuffer();
  const res = await fetch(`/api/projects/import-zip?slug=${encodeURIComponent(slug)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/zip' },
    body: buf,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || 'Could not import.');
    return;
  }
  state.activeSlug = slug;
  await refresh();
}

boot();
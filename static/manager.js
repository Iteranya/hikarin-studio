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
  variables: [],      // the selected project's shared variable registry
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
  await refresh();
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
    empty.textContent = 'No projects yet. Press “New project” to start one.';
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
    const n = p.storyCount ?? (p.stories || []).length;
    meta.textContent = `${p.slug} · ${n} ${n === 1 ? 'story' : 'stories'}`;

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

  const { slug, meta, stories } = state.detail;
  const totalBlocks = stories.reduce((sum, s) => sum + (s.blockCount || 0), 0);

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
  actions.appendChild(button('Rename', 'btn', () => renameProjectDialog()));
  actions.appendChild(button('Duplicate', 'btn', () => duplicateProject()));
  // Pack format is an export choice, so it lives next to the export button
  // rather than in the project fields.
  const fmtWrap = document.createElement('span');
  fmtWrap.className = 'export-fmt';
  const fmtInput = document.createElement('input');
  fmtInput.type = 'number';
  fmtInput.min = '1';
  fmtInput.max = '999';
  fmtInput.value = '15';
  fmtInput.className = 'input export-fmt-input';
  fmtInput.title = 'Resource pack format version (15 = 1.20.1)';
  fmtWrap.appendChild(fmtInput);
  actions.appendChild(fmtWrap);
  actions.appendChild(button('Export pack', 'btn', () => exportPack(Number(fmtInput.value) || undefined)));
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

  // facts
  const facts = document.createElement('div');
  facts.className = 'detail-facts';
  facts.appendChild(fact(String(stories.length), stories.length === 1 ? 'story' : 'stories'));
  facts.appendChild(fact(String(totalBlocks), 'blocks'));
  root.appendChild(facts);

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

  renderStories(root, slug, stories);

  // closing note, because the difference is the whole point of this page
  const note = document.createElement('div');
  note.className = 'manager-empty-note';
  note.innerHTML =
    '<b>Project</b> = the pack the runtime installs. <b>Story</b> = one story’s script inside it. ' +
    'Art in <code>images/</code> and <code>sounds/</code> is shared by every story. ' +
    'Labels are scoped to a story: a Jump can cross <code>.story</code> files, never stories.';
  root.appendChild(note);
}

function renderStories(root, slug, stories) {
  const totalBlocks = stories.reduce((sum, s) => sum + (s.blockCount || 0), 0);

  const facts = document.createElement('div');
  facts.className = 'detail-facts';
  facts.appendChild(fact(String(stories.length), stories.length === 1 ? 'story' : 'stories'));
  facts.appendChild(fact(String(totalBlocks), 'blocks'));
  root.appendChild(facts);

  const sectionHead = document.createElement('div');
  sectionHead.className = 'section-head';
  const sectionTitle = document.createElement('span');
  sectionTitle.className = 'section-title';
  sectionTitle.textContent = 'Stories';
  sectionHead.appendChild(sectionTitle);
  sectionHead.appendChild(button('+ New story', 'btn tiny', () => createStoryDialog()));
  root.appendChild(sectionHead);

  const list = document.createElement('div');
  list.className = 'story-list';

  if (stories.length === 0) {
    const note = document.createElement('div');
    note.className = 'manager-empty-note';
    note.innerHTML =
      'This project has no stories yet. A story is one story’s script — add one to start writing.';
    list.appendChild(note);
  }

  for (const s of stories) {
    list.appendChild(storyCard(s));
  }

  root.appendChild(list);
}

function storyCard(s) {
  const card = document.createElement('div');
  card.className = 'story-card';
  card.tabIndex = 0;
  card.onclick = (e) => {
    if (e.target.closest('.story-card-actions')) return;
    openStory(s.slug);
  };
  card.onkeydown = (e) => {
    if (e.key === 'Enter') openStory(s.slug);
  };

  const main = document.createElement('div');
  main.className = 'story-card-main';

  const nameRow = document.createElement('div');
  nameRow.className = 'story-card-name';
  nameRow.textContent = s.character || s.slug;

  // The slug is the folder; the character is the trigger the engine reads. They
  // are usually the same, and showing both when they differ is the only way to
  // notice that a story will export under a different name than its folder.
  if (s.character && s.character !== s.slug) {
    const badge = document.createElement('span');
    badge.className = 'story-badge';
    badge.textContent = s.slug;
    nameRow.appendChild(badge);
  }

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
      renameStoryDialog(s.slug);
    })
  );
  cardActions.appendChild(
    button('Duplicate', 'btn tiny', (e) => {
      e.stopPropagation();
      duplicateStory(s.slug);
    })
  );
  cardActions.appendChild(
    button('Delete', 'btn tiny danger', (e) => {
      e.stopPropagation();
      deleteStory(s.slug);
    })
  );

  card.appendChild(main);
  card.appendChild(cardActions);
  return card;
}

function fact(value, label) {
  const wrap = document.createElement('div');
  wrap.className = 'fact';
  const v = document.createElement('span');
  v.className = 'fact-value';
  v.textContent = value;
  const l = document.createElement('span');
  l.className = 'fact-label';
  l.textContent = label;
  wrap.appendChild(v);
  wrap.appendChild(l);
  return wrap;
}

function button(text, cls, onclick) {
  const b = document.createElement('button');
  b.className = cls;
  b.textContent = text;
  if (onclick) b.onclick = onclick;
  return b;
}

// ── opening a story ─────────────────────────────────────────────────────────

function openStory(storySlug) {
  // The editor reads ?project= and ?story= so a reload returns to the same
  // place, and so a story can be linked to.
  window.location.href = `/editor?project=${encodeURIComponent(state.activeSlug)}&story=${encodeURIComponent(storySlug)}`;
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
  const count = state.detail?.stories?.length ?? 0;
  const ok = await confirmDialog(
    'Delete project?',
    `This removes projects/${state.activeSlug}/ — ${count} ${
      count === 1 ? 'story' : 'stories'
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

function exportPack(packFormat) {
  const params = new URLSearchParams({ format: 'pack' });
  if (packFormat) params.set('pack_format', String(packFormat));
  window.location.href = `/api/projects/${encodeURIComponent(state.activeSlug)}/export?${params}`;
}

// ── story actions ───────────────────────────────────────────────────────────

async function createStory(storySlug, character) {
  const res = await fetch(
    `/api/projects/${encodeURIComponent(state.activeSlug)}/stories`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        slug: storySlug,
        // The character is the engine's trigger and defaults to the folder name.
        // Sending it explicitly keeps the two independent when an author wants
        // a differently-named script for the same story.
        meta: { character: character || storySlug },
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Could not create the story.');
  }
  await openProject(state.activeSlug);
}

async function renameStory(storySlug, newSlug) {
  const res = await fetch(
    `/api/projects/${encodeURIComponent(state.activeSlug)}/stories/${encodeURIComponent(
      storySlug
    )}/rename`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_slug: newSlug }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || 'Could not rename the story.');
    return;
  }
  await openProject(state.activeSlug);
}

async function duplicateStory(storySlug) {
  const newSlug = prompt('Duplicate story to which name?', `${storySlug}_copy`);
  if (!newSlug) return;
  const res = await fetch(
    `/api/projects/${encodeURIComponent(state.activeSlug)}/stories/${encodeURIComponent(
      storySlug
    )}/duplicate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_slug: newSlug }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || 'Could not duplicate the story.');
    return;
  }
  await openProject(state.activeSlug);
}

async function deleteStory(storySlug) {
  const ok = await confirmDialog(
    'Delete story?',
    `This removes the story “${storySlug}” — its .story files and every block in them. ` +
      `Shared images and sounds stay. This cannot be undone.`,
    'Delete story'
  );
  if (!ok) return;

  const res = await fetch(
    `/api/projects/${encodeURIComponent(state.activeSlug)}/stories/${encodeURIComponent(
      storySlug
    )}`,
    { method: 'DELETE' }
  );
  if (!res.ok) {
    alert('Could not delete the story.');
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
        // The first story is part of creating a project, because a project with
        // no stories is a folder that does nothing yet. A project starts with one
        // story, so the story's character is the project's own slug.
        await createStory(p.story, p.slug);
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

function createStoryDialog() {
  return new Promise((resolve) => {
    const backdrop = $('story-dialog');
    const charEl = $('sf-character');
    const slugEl = $('sf-slug');
    const errEl = $('sf-error');

    charEl.value = '';
    slugEl.value = '';
    slugEl.readOnly = true;          // follows the character until edited
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
      const character = charEl.value.trim();
      if (!character) return showError('Who is this story about?');
      if (!/^[a-z0-9_-]+$/.test(character)) {
        return showError('Lowercase letters, numbers, - and _ only — it becomes a file name.');
      }
      const slug = slugEl.value.trim() || character;
      $('story-dialog-ok').disabled = true;
      try {
        await createStory(slug, character);
        done({ slug, character });
      } catch (e) {
        showError(e.message);
      } finally {
        $('story-dialog-ok').disabled = false;
      }
    };

    const onKey = (e) => {
      if (e.key === 'Escape') done(null);
      if (e.key === 'Enter') {
        e.preventDefault();
        submit();
      }
    };
    const onClick = (e) => { if (e.target === backdrop) done(null); };
    const cleanup = () => {
      document.removeEventListener('keydown', onKey);
      backdrop.removeEventListener('click', onClick);
      $('story-dialog-ok').onclick = null;
      $('story-dialog-cancel').onclick = null;
      $('story-dialog-close').onclick = null;
      charEl.oninput = null;
    };

    // The story name mirrors the character until the author takes it over —
    // the common case is one folder per story, and making them type it twice is
    // a pointless chore.
    charEl.oninput = () => {
      if (!slugEl.readOnly) return;
      slugEl.value = charEl.value.trim().toLowerCase().replace(/\s+/g, '_');
    };
    slugEl.oninput = () => { slugEl.readOnly = true; };
    slugEl.onfocus = () => { slugEl.readOnly = false; };

    $('story-dialog-ok').onclick = submit;
    $('story-dialog-cancel').onclick = () => done(null);
    $('story-dialog-close').onclick = () => done(null);
    document.addEventListener('keydown', onKey);
    backdrop.addEventListener('click', onClick);
  });
}

function renameStoryDialog(storySlug) {
  return new Promise((resolve) => {
    const backdrop = $('story-dialog');
    const charEl = $('sf-character');
    const slugEl = $('sf-slug');
    const errEl = $('sf-error');

    const existing = state.detail?.stories?.find((x) => x.slug === storySlug);

    $('story-dialog-title').textContent = 'Rename story';
    $('story-dialog-ok').textContent = 'Rename';
    charEl.value = existing?.character || storySlug;
    slugEl.value = storySlug;
    slugEl.readOnly = true;
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
      const character = charEl.value.trim();
      const newSlug = slugEl.value.trim();
      if (!character) return;
      if (!newSlug) {
        errEl.textContent = 'Give the story a name.';
        errEl.hidden = false;
        return;
      }
      if (newSlug === storySlug && character === (existing?.character || storySlug)) {
        return done(null);
      }
      $('story-dialog-ok').disabled = true;
      try {
        // Renaming moves the folder, so it can only do one of the two at a time.
        // Renaming the folder carries the character with it when the character
        // was just the folder name; a deliberate character name is left alone.
        if (newSlug !== storySlug || character !== (existing?.character || storySlug)) {
          const res = await fetch(
            `/api/projects/${encodeURIComponent(state.activeSlug)}/stories/${encodeURIComponent(storySlug)}/rename`,
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ new_slug: newSlug, character }),
            }
          );
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Could not rename the story.');
          }
        }
        await openProject(state.activeSlug);
        done({ slug: newSlug, character });
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
    };

    slugEl.onfocus = () => { slugEl.readOnly = false; };
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
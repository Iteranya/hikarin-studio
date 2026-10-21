/* Preview harness for a Hikarin story.
 *
 * Loads the compiled actions from /api/projects/{slug}/play — the same
 * compiler that builds the exported resource pack, so what you test here is
 * what ships.
 *
 * The transport controls mirror what a script author actually needs:
 *
 *   Play   resume at the checkpoint — byte-for-byte what right-clicking the
 *          maid does in game, so the preview cannot lie about behaviour
 *   Stop   halt, keep everything (examine the frozen state)
 *   Reset  clear every variable and the checkpoint, then start over
 *
 * There is deliberately no "restart from the top" button. The only way a story
 * goes back to its opening is Reset, because that is the only thing the game
 * itself offers: the cursor advances and never rewinds.
 *
 * URL: play.html?project=cupa
 */

const $ = (id) => document.getElementById(id);

const params = new URLSearchParams(location.search);
const slug = params.get('project');

const state = {
  payload: null,
  viewer: null,
  runtime: null,
  variables: {},   // injected by the writer; cleared by Reset
  isNight: false,
  status: 'idle',  // idle | playing | stopped | ended
};

// ── boot ────────────────────────────────────────────────────────────────────

async function boot() {
  if (!slug) {
    showErrors(['No project given. Open this from the studio.']);
    return;
  }

  const res = await fetch(`/api/projects/${slug}/play`);
  const payload = await res.json();
  state.payload = payload;

  $('play-title').textContent = `${payload.character ?? slug} — preview`;

  if (!payload.ok) {
    showErrors(payload.errors, payload.warnings);
    return;
  }

  renderQuickFacts();
  renderVarList();
  wireControls();

  // Build once; the transport buttons drive the same runtime instead of
  // rebuilding it, so Stop genuinely freezes state and Restart keeps it.
  mountViewer();
  play();
}

// ── viewer lifecycle ────────────────────────────────────────────────────────

function mountViewer() {
  const container = $('vn-container');
  container.innerHTML = '';

  if (typeof window.HikarinVN !== 'function') {
    showErrors(['The viewer library did not load. Check static/vendor/hikarin-vn-viewer.umd.js']);
    return;
  }

  try {
    state.viewer = new window.HikarinVN('vn-container', state.payload.actions, {
      assetsPath: state.payload.assetsPath,
      debug: $('env-debug').checked,
    });
    state.runtime = state.viewer.runtime;

    // Track when the story ends so Play can offer a replay.
    state.runtime.events.onFinish = () => {
      state.status = 'ended';
      renderTransport();
      renderVarList();
    };
  } catch (err) {
    showErrors([`Viewer failed to start: ${err.message}`]);
  }
}

/** Start from the top, or resume where the autosave checkpoint left off. */
function play() {
  if (!state.runtime) return;

  applyEnvironment();
  for (const [name, value] of Object.entries(state.variables)) {
    try {
      state.runtime.setVariable(name, value);
    } catch (err) {
      console.warn('setVariable failed', name, err);
    }
  }

  state.runtime.start();
  state.status = 'playing';
  renderTransport();
}

/** A fresh playthrough: no variables, no checkpoint, no sprites. */
function reset() {
  // A fresh runtime has no variables and no checkpoint, so the cursor is back
  // at the start label with nothing carried over. This is the only way back to
  // the opening, mirroring the game.
  state.variables = {};
  state.isNight = false;
  $('env-night').checked = false;
  $('state-night').checked = false;

  mountViewer();
  applyEnvironment();
  state.runtime.start();

  state.status = 'playing';
  renderTransport();
  renderVarList();
  renderQuickFacts();
}

/** Halt without discarding anything, so the state panel stays meaningful. */
function stop() {
  if (!state.runtime || typeof state.runtime.stop !== 'function') return;
  state.runtime.stop();
  state.status = 'stopped';
  renderTransport();
  renderVarList();
}

// ── transport ───────────────────────────────────────────────────────────────

function renderTransport() {
  const playBtn = $('btn-play');
  const stopBtn = $('btn-stop');
  const statusEl = $('play-status');

  playBtn.textContent = {
    idle: '▶ Play',
    playing: '▶ Play',
    stopped: '▶ Resume',
    ended: '↻ Replay',
  }[state.status] || '▶ Play';

  playBtn.disabled = state.status === 'playing';
  stopBtn.disabled = state.status !== 'playing';

  statusEl.textContent = {
    idle: 'ready',
    playing: 'running',
    stopped: 'stopped',
    ended: 'finished',
  }[state.status] || 'ready';

  statusEl.className = `play-status ${state.status}`;
}

// ── environment ─────────────────────────────────────────────────────────────

function applyEnvironment() {
  if (!state.runtime) return;
  // setEnvironment takes (key, value) and only accepts keys it knows:
  // isNight and isDay. The engine checks environment before locals and
  // globals, so a script reads these like any other conditional.
  try {
    state.runtime.setEnvironment('isNight', state.isNight);
    state.runtime.setEnvironment('isDay', !state.isNight);
  } catch (err) {
    console.warn('setEnvironment failed', err);
  }
}

// ── controls ────────────────────────────────────────────────────────────────

function wireControls() {
  $('btn-play').onclick = play;
  $('btn-reset').onclick = () => {
    if (confirm('Reset clears every variable and starts over. Continue?')) reset();
  };
  $('btn-stop').onclick = stop;

  $('btn-vars').onclick = () => {
    const panel = $('state-panel');
    panel.hidden = !panel.hidden;
  };

  $('state-close').onclick = () => {
    $('state-panel').hidden = true;
  };

  const syncNight = (night) => {
    state.isNight = night;
    $('env-night').checked = night;
    $('state-night').checked = night;
    applyEnvironment();
    renderVarList();
  };

  $('env-night').onchange = (e) => syncNight(e.target.checked);
  $('state-night').onchange = (e) => syncNight(e.target.checked);

  $('env-debug').onchange = () => {
    // Debug is a construction-time flag. Rebuild but carry the checkpoint so
    // toggling it mid-read does not throw away the story position.
    const checkpoint = state.runtime?.getVariable('_autosave');
    mountViewer();
    if (checkpoint) state.runtime.setVariable('_autosave', checkpoint);
    play();
  };

  $('var-add-btn').onclick = addVariable;
  $('var-name').onkeydown = (e) => { if (e.key === 'Enter') addVariable(); };
  $('var-value').onkeydown = (e) => { if (e.key === 'Enter') addVariable(); };
}

function addVariable() {
  const name = $('var-name').value.trim();
  if (!name) return;
  setVar(name, coerce($('var-value').value.trim()));
  $('var-name').value = '';
  $('var-value').value = '';
}

function setVar(name, value) {
  state.variables[name] = value;
  if (state.runtime) {
    try {
      state.runtime.setVariable(name, value);
    } catch (err) {
      console.warn('setVariable failed', name, err);
    }
  }
  renderVarList();
}

function removeVariable(name) {
  delete state.variables[name];
  if (state.runtime?.deleteVariable) {
    try { state.runtime.deleteVariable(name); } catch { /* not fatal */ }
  }
  renderVarList();
}

// "true"/"false"/numbers become real values; the engine compares against JSON
// types, so a string "true" would never equal a boolean true.
function coerce(raw) {
  if (typeof raw === 'boolean' || typeof raw === 'number') return raw;
  if (raw === 'true') return true;
  if (raw === 'false') return false;
  if (raw !== null && raw !== undefined && raw !== '' && !isNaN(Number(raw))) return Number(raw);
  return raw;
}

// ── state panel ─────────────────────────────────────────────────────────────

function renderVarList() {
  const list = $('var-list');
  list.innerHTML = '';

  const injected = Object.entries(state.variables);

  // Also surface what the story itself has set, so a run is inspectable
  // rather than a black box.
  const live = state.runtime?.variables ?? {};
  const storyVars = Object.entries(live).filter(
    ([k]) => !k.startsWith('_') && !(k in state.variables)
  );

  if (injected.length === 0 && storyVars.length === 0 && !live._autosave) {
    list.innerHTML = '<div class="var-empty">none set</div>';
    return;
  }

  for (const [name, value] of injected) {
    list.appendChild(varRow(name, value, () => removeVariable(name)));
  }

  for (const [name, value] of storyVars) {
    const row = varRow(name, value, null);
    row.title = 'Set by the story';
    list.appendChild(row);
  }

  // The checkpoint is the single most useful thing to see while testing a
  // spine: it is the cursor `next` wrote.
  if (live._autosave) {
    const row = varRow('_autosave', live._autosave, null);
    row.title = 'Where the story will resume';
    row.style.borderLeft = '2px solid var(--accent)';
    list.appendChild(row);
  }
}

function varRow(name, value, onDelete) {
  const row = document.createElement('div');
  row.className = 'var-row';

  const n = document.createElement('span');
  n.className = 'var-name';
  n.textContent = name;
  n.title = name;

  const v = document.createElement('span');
  v.className = 'var-value';
  v.textContent = JSON.stringify(value);

  row.append(n, v);

  if (onDelete) {
    const del = document.createElement('button');
    del.className = 'var-del';
    del.textContent = '✕';
    del.title = 'Remove';
    del.onclick = onDelete;
    row.appendChild(del);
  } else {
    row.appendChild(document.createElement('span'));
  }

  return row;
}

function renderQuickFacts() {
  const wrap = $('quick-facts');
  wrap.innerHTML = '';

  // Variables only. Day and night are NOT variables — they are condition types
  // that read no variable at all, so they belong to the world toggle above.
  const vars = state.payload.suggestedVars ?? [];

  if (vars.length === 0) {
    wrap.innerHTML = '<span class="var-empty">this story reads no variables</span>';
    return;
  }

  for (const v of vars) {
    const btn = document.createElement('button');
    btn.className = 'fact';

    const tested = coerce(v.value);
    const flip = oppositeOf(tested, v.condition);

    const label = v.scope ? `${v.scope}·${v.name}` : v.name;
    btn.textContent = `${label} = ${JSON.stringify(flip)}`;
    btn.title =
      `Story tests: ${v.name} ${v.condition} ${JSON.stringify(v.value)}` +
      `  →  set to ${JSON.stringify(flip)} to take the other branch.`;

    btn.onclick = () => setVar(v.name, flip);

    wrap.appendChild(btn);
  }
}

/**
 * A value that makes the tested condition FAIL, keeping the same JSON type so
 * the engine's strict comparisons behave.
 *
 * The condition matters: for equality the opposite is "anything else", but for
 * `less_than` the opposite is "greater than or equal", not "different".
 */
function oppositeOf(tested, condition = 'equal') {
  if (typeof tested === 'boolean') return !tested;

  if (typeof tested === 'number') {
    switch (condition) {
      case 'less_than':
      case 'less_or_equal':
        return tested + 1;
      case 'greater_than':
      case 'greater_or_equal':
        return Math.max(0, tested - 1);
      default:
        return tested === 0 ? 1 : 0;
    }
  }

  if (typeof tested === 'string') {
    return tested === '' ? 'set' : `${tested}_other`;
  }

  return 'set';
}

// ── errors ──────────────────────────────────────────────────────────────────

function showErrors(errors, warnings = []) {
  $('compile-error').hidden = false;
  $('vn-container').innerHTML = '';

  const lines = [
    ...errors.map((e) => `ERROR  ${e}`),
    ...warnings.map((w) => `warn   ${w}`),
  ];
  $('compile-error-body').textContent = lines.join('\n');
}

boot();

// Expose state for debugging in the browser console. The module scope hides
// everything, which makes a stuck preview impossible to diagnose from outside.
window.__hikarin = {
  get state() { return state; },
  get viewer() { return state.viewer; },
  get runtime() { return state.runtime; },
  get env() { return state.runtime?.environment; },
};

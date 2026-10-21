/* Preview harness for a Hikarin story.
 *
 * Loads the compiled actions from /api/projects/{slug}/play — the same
 * compiler that builds the exported resource pack, so what you test here is
 * what ships.
 *
 * The state panel is the point: the story routes on flags, so being able to
 * set `seen.night_01 = true` and watch it take a different branch is the
 * difference between guessing and knowing.
 *
 * URL: play.html?project=cupa
 */

const $ = (id) => document.getElementById(id);

const params = new URLSearchParams(location.search);
const slug = params.get('project');

const state = {
  payload: null,
  viewer: null,
  variables: {},   // name -> value, applied to the viewer
  isNight: false,
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
  startViewer();
  wireControls();
}

// ── viewer ──────────────────────────────────────────────────────────────────

function startViewer() {
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

    // Apply whatever the writer has set before the first line runs, so the
    // very first conditional sees the simulated state.
    applyEnvironment();
    for (const [name, value] of Object.entries(state.variables)) {
      try {
        state.viewer.setVariable(name, value);
      } catch (err) {
        console.warn('setVariable failed', name, err);
      }
    }

    state.viewer.start();
  } catch (err) {
    showErrors([`Viewer failed to start: ${err.message}`]);
  }
}

function applyEnvironment() {
  if (!state.viewer) return;
  // setEnvironment takes (key, value), and the engine only accepts keys it
  // already knows — isNight and isDay. Environment is checked before locals and
  // globals, so these read like any other conditional in a script.
  try {
    state.viewer.setEnvironment('isNight', state.isNight);
    state.viewer.setEnvironment('isDay', !state.isNight);
  } catch (err) {
    console.warn('setEnvironment failed', err);
  }
}

// ── controls ────────────────────────────────────────────────────────────────

function wireControls() {
  $('btn-restart').onclick = () => startViewer();

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
  };

  $('env-night').onchange = (e) => syncNight(e.target.checked);
  $('state-night').onchange = (e) => syncNight(e.target.checked);

  $('env-debug').onchange = () => {
    // Debug mode is set at construction, so rebuild.
    startViewer();
  };

  $('var-add-btn').onclick = addVariable;
  $('var-name').onkeydown = (e) => { if (e.key === 'Enter') addVariable(); };
  $('var-value').onkeydown = (e) => { if (e.key === 'Enter') addVariable(); };
}

function addVariable() {
  const name = $('var-name').value.trim();
  if (!name) return;
  const raw = $('var-value').value.trim();
  const value = coerce(raw);

  state.variables[name] = value;
  $('var-name').value = '';
  $('var-value').value = '';

  if (state.viewer) {
    try {
      state.viewer.setVariable(name, value);
    } catch (err) {
      console.warn('setVariable failed', name, err);
    }
  }
  renderVarList();
}

function removeVariable(name) {
  delete state.variables[name];
  if (state.viewer?.deleteVariable) {
    try { state.viewer.deleteVariable(name); } catch { /* not fatal */ }
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

  const entries = Object.entries(state.variables);
  if (entries.length === 0) {
    list.innerHTML = '<div class="var-empty">none set</div>';
    return;
  }

  for (const [name, value] of entries) {
    const row = document.createElement('div');
    row.className = 'var-row';

    const n = document.createElement('span');
    n.className = 'var-name';
    n.textContent = name;
    n.title = name;

    const v = document.createElement('span');
    v.className = 'var-value';
    v.textContent = JSON.stringify(value);

    const del = document.createElement('button');
    del.className = 'var-del';
    del.textContent = '✕';
    del.title = 'Remove';
    del.onclick = () => removeVariable(name);

    row.append(n, v, del);
    list.appendChild(row);
  }
}

function renderQuickFacts() {
  const wrap = $('quick-facts');
  wrap.innerHTML = '';

  // Environment keys are offered as ordinary facts. In the engine they are
  // checked before locals and globals, so `isNight` in a script is not a
  // special construct — it is a conditional that happens to be set by the
  // world instead of by the player.
  //
  // A script that already reads isNight gets only the env entry, not both.
  const scriptVars = state.payload.suggestedVars ?? [];
  const readsEnv = new Set(scriptVars.map((v) => v.name));

  const env = [
    { name: 'isNight', current: state.isNight, scope: 'env' },
    { name: 'isDay', current: !state.isNight, scope: 'env' },
  ].filter((e) => !readsEnv.has(e.name));

  const vars = [...env, ...scriptVars];

  for (const v of vars) {
    const btn = document.createElement('button');
    btn.className = 'fact';

    // Environment facts: the value shown is the state you would switch TO.
    // There is no "script tests this" here — the script may or may not read it.
    if (v.scope === 'env') {
      const target = !v.current;
      btn.textContent = `${v.name} = ${JSON.stringify(target)}`;
      btn.title = `Set ${v.name} to ${JSON.stringify(target)} (world state).`;
      btn.onclick = () => {
        const night = v.name === 'isNight' ? target : !target;
        state.isNight = night;
        $('env-night').checked = night;
        $('state-night').checked = night;
        applyEnvironment();
        renderQuickFacts();
      };
      wrap.appendChild(btn);
      continue;
    }

    // Script variables: the viewer compares with strict equality against the
    // raw `value` in the action, so injected state must match its TYPE exactly.
    // The interesting state is the one that makes the test FAIL — that is the
    // branch you cannot reach by playing normally.
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

  if (vars.length === 0) {
    wrap.innerHTML = '<span class="var-empty">this story reads no variables yet</span>';
  }
}

/**
 * A value that makes the tested condition FAIL, keeping the same JSON type so
 * the engine's strict comparisons behave.
 *
 * The condition matters: for equality the opposite is "anything else", but for
 * `less_than` the opposite is "greater than or equal", not "different". Getting
 * this wrong produces a fact button that sets a value the story still accepts.
 */
function oppositeOf(tested, condition = 'equal') {
  if (typeof tested === 'boolean') {
    // true/false flip cleanly under equal and not_equal alike.
    return !tested;
  }

  if (typeof tested === 'number') {
    switch (condition) {
      case 'less_than':
      case 'less_or_equal':
        return tested + 1;          // step above the ceiling
      case 'greater_than':
      case 'greater_or_equal':
        return Math.max(0, tested - 1); // step below the floor
      default:
        return tested === 0 ? 1 : 0;   // equal / not_equal
    }
  }

  if (typeof tested === 'string') {
    return tested === '' ? 'set' : `${tested}_other`;
  }

  return 'set';
}

function setVar(name, value) {
  state.variables[name] = value;
  if (state.viewer) {
    try {
      state.viewer.setVariable(name, value);
    } catch (err) {
      console.warn('setVariable failed', name, err);
    }
  }
  renderVarList();
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

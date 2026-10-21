// Compiler: many .story files -> one flat JSON the Minecraft engine reads.
//
// Design constraints (see FORMAT.md / NOTES.md):
//   * ids are sequential from 0 and unique
//   * the file containing project.startLabel is emitted first
//   * conditionals store an "end" id, but authors type a label, so targets are
//     resolved in a second pass after ids exist
//   * the studio keeps a "_target" hint on conditionals; it is stripped here

import { BLOCKS, blockKindForAction } from './blocks.js';

/**
 * Compile a project into { json, warnings, errors, labelIndex }.
 *
 * @param {object} project  { character, packName, packFormat, displayName, startLabel }
 * @param {Record<string, Array>} files  { 'main.story': [block, ...], ... }
 * @param {string[]} order  file order from project.files
 */
export function compile(project, files, order) {
  const warnings = [];
  const errors = [];

  // --- 1. Order the files: the one holding startLabel goes first -------------
  const startLabel = project.startLabel || 'start';
  const ordered = orderFiles(order, files, startLabel, warnings);

  // --- 2. Collect labels up front so jumps can be validated ------------------
  const labelFile = new Map(); // label -> file
  for (const fileName of ordered) {
    for (const block of files[fileName] || []) {
      if (block.kind === 'label' && block.data.name) {
        if (labelFile.has(block.data.name)) {
          errors.push(`Duplicate label "${block.data.name}" in ${fileName} (already in ${labelFile.get(block.data.name)})`);
        } else {
          labelFile.set(block.data.name, fileName);
        }
      }
    }
  }
  if (!labelFile.has(startLabel)) {
    errors.push(`Start label "${startLabel}" does not exist. Add a Label block named "${startLabel}".`);
  }

  // --- 3. Emit actions with sequential ids ----------------------------------
  const actions = [];
  const conditionals = []; // { index, block, file }
  let id = 0;

  for (const fileName of ordered) {
    for (const block of files[fileName] || []) {
      const def = BLOCKS[block.kind];
      if (!def) {
        errors.push(`Unknown block kind "${block.kind}" in ${fileName}`);
        continue;
      }
      // Two meta actions the engine expects at the very top; the studio inserts
      // them itself so authors never think about them.
      if (actions.length === 0) {
        actions.push({ type: 'meta', action: 'start', id: id++ });
      } else if (actions.length === 1 && block.kind !== 'label') {
        // okay: a file may open with dialogue; no meta needed mid-story
      }

      const action = def.toAction(block.data || {});
      action.id = id++;

      if (action.type === 'conditional' || action.type === 'conditional_global') {
        conditionals.push({ index: actions.length, block, file: fileName, action });
      }
      actions.push(action);
    }
  }

  // --- 4. Resolve conditional targets to ids --------------------------------
  for (const c of conditionals) {
    const target = c.block.data?._target || c.block.data?.target;
    if (!target) {
      warnings.push(`${c.file}: an If block has no jump target; it will fall through.`);
      c.action.end = c.action.id + 1;
      continue;
    }
    if (!labelFile.has(target)) {
      const suggestion = suggest(target, [...labelFile.keys()]);
      errors.push(
        `${c.file}: If block jumps to "${target}" which does not exist.` +
        (suggestion ? ` Did you mean "${suggestion}"?` : '')
      );
      c.action.end = c.action.id + 1;
      continue;
    }
    // The target id is the label's id + 1? No: a conditional that fails jumps
    // to "end", which the engine treats as the action AFTER the nested block.
    // In the studio's flat model there is no nesting, so "end" is simply the
    // label's own id and the label advances past itself.
    c.action.end = findLabelId(actions, target);
  }

  // --- 5. Validate every label reference ------------------------------------
  for (const action of actions) {
    if (action.type === 'transition' && action.action === 'jump') {
      if (!action.label) {
        errors.push(`A Jump block has no target.`);
      } else if (!labelFile.has(action.label)) {
        const suggestion = suggest(action.label, [...labelFile.keys()]);
        errors.push(`Jump to "${action.label}" which does not exist.` + (suggestion ? ` Did you mean "${suggestion}"?` : ''));
      }
    }
    if (action.type === 'unlock_dialogues') {
      for (const ev of action.events || []) {
        if (!labelFile.has(ev)) {
          errors.push(`Unlock references "${ev}" which is not a label.`);
        }
      }
    }
    if ((action.type === 'choice' || action.type === 'night_choice')) {
      for (const c of action.choice || []) {
        if (!labelFile.has(c.label)) {
          errors.push(`Choice "${c.display}" points at "${c.label}" which is not a label.`);
        }
      }
    }
    if (action.type === 'next' && action.label && !labelFile.has(action.label)) {
      warnings.push(`Checkpoint "${action.label}" is not a label; it will be remembered but never jumped to automatically.`);
    }
  }

  // --- 6. Duplicate ids are impossible by construction, but assert anyway ---
  const seen = new Set();
  for (const a of actions) {
    if (seen.has(a.id)) errors.push(`Internal error: duplicate id ${a.id}`);
    seen.add(a.id);
  }

  const json = actions.map(stripStudioFields);

  return {
    json,
    warnings,
    errors,
    labelIndex: Object.fromEntries([...labelFile.entries()]),
    actionCount: actions.length,
  };
}

function orderFiles(order, files, startLabel, warnings) {
  const names = (order && order.length ? order : Object.keys(files)).filter((n) => files[n]);
  const holder = names.find((n) =>
    (files[n] || []).some((b) => b.kind === 'label' && b.data?.name === startLabel)
  );
  if (!holder) {
    warnings.push(`No file defines the start label "${startLabel}"; using file order as-is.`);
    return names;
  }
  return [holder, ...names.filter((n) => n !== holder)];
}

function findLabelId(actions, label) {
  for (const a of actions) {
    if (a.type === 'label' && a.label === label) return a.id;
  }
  return 0;
}

// The engine stores ids; the studio stores "_target". Strip hints so shipped
// JSON is clean, and drop fields the engine ignores.
function stripStudioFields(action) {
  const out = {};
  for (const [k, v] of Object.entries(action)) {
    if (k.startsWith('_')) continue;
    out[k] = v;
  }
  return out;
}

/**
 * "Did you mean" for label typos.
 *
 * Plain edit distance is the wrong measure: transposing a word ("nihgt" vs
 * "night") costs a full block swap, so a real typo can score 5 edits against an
 * 8-char name and get rejected. Instead we score by *similarity ratio*
 * (1 - distance / longer length) and accept anything above 0.4, which catches
 * transpositions, dropped letters and wrong suffixes while still rejecting
 * unrelated names.
 */
export function suggest(input, candidates) {
  if (!input || !candidates || candidates.length === 0) return null;
  const a = input.toLowerCase();
  let best = null;
  let bestRatio = 0;

  for (const c of candidates) {
    const b = c.toLowerCase();
    const longer = Math.max(a.length, b.length);
    if (longer === 0) continue;
    const ratio = 1 - editDistance(a, b) / longer;
    // Prefix matches are strong signals even when the tail differs.
    const bonus = b.startsWith(a.slice(0, Math.max(3, Math.floor(a.length / 2)))) ? 0.15 : 0;
    const score = ratio + bonus;
    if (score > bestRatio) {
      bestRatio = score;
      best = c;
    }
  }
  return bestRatio >= 0.4 ? best : null;
}

function editDistance(a, b) {
  const m = a.length;
  const n = b.length;
  if (!m) return n;
  if (!n) return m;
  let prev = Array.from({ length: n + 1 }, (_, i) => i);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) {
      cur[j] = Math.min(
        prev[j] + 1,
        cur[j - 1] + 1,
        prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)
      );
    }
    prev = cur;
  }
  return prev[n];
}

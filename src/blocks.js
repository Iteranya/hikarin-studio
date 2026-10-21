// Block definitions — the studio's palette.
//
// Every block maps to exactly one engine action type. Nothing here invents
// vocabulary; FORMAT.md is the source of truth.
//
// A field descriptor is:
//   { key, label, type, ...options }
// type: text | textarea | number | bool | select | label-ref | var | choices
//       | scope | sprite | item

export const GROUPS = [
  { id: 'talk', label: 'Talk', colour: '#4a7c59' },
  { id: 'stage', label: 'Stage', colour: '#6b5b95' },
  { id: 'flow', label: 'Flow', colour: '#8a6d3b' },
  { id: 'state', label: 'State', colour: '#7c4a4a' },
  { id: 'audio', label: 'Audio', colour: '#3f6b7c' },
];

export const CONDITIONS = [
  { value: 'equal', label: 'is', needsValue: true },
  { value: 'not_equal', label: 'is not', needsValue: true },
  { value: 'greater_than', label: 'is more than', needsValue: true },
  { value: 'less_than', label: 'is less than', needsValue: true },
  { value: 'greater_or_equal', label: 'is at least', needsValue: true },
  { value: 'less_or_equal', label: 'is at most', needsValue: true },
  { value: 'exists', label: 'exists', needsValue: false },
  { value: 'not_exists', label: 'does not exist', needsValue: false },
  { value: 'night', label: 'it is night', needsValue: false },
  { value: 'day', label: 'it is day', needsValue: false },
];

const POSITIONS = [
  { value: 'CENTER', label: 'Centre' },
  { value: 'LEFT', label: 'Left' },
  { value: 'RIGHT', label: 'Right' },
  { value: 'CUSTOM', label: 'Custom grid' },
];

// Default sprite geometry: 16x9 screen, 4x8 frame, column 7 row 1 (centre).
// Matches the engine's documented defaults so a plain "show" needs no maths.
const SPRITE_DEFAULTS = { wRatio: 16, hRatio: 9, wFrameRatio: 4, hFrameRatio: 8, column: 7, row: 1 };

export const BLOCKS = {
  say: {
    group: 'talk', icon: '💬', title: 'Say',
    summary: (b) => `${b.label || '?'} — "${truncate(b.content)}"`,
    fields: [
      { key: 'label', label: 'Speaker', type: 'text', placeholder: 'Cupa, or leave empty for narration' },
      { key: 'content', label: 'Text', type: 'textarea', rows: 3 },
    ],
    toAction: (b) => ({ type: 'dialogue', action: 'say', label: b.label || '', content: b.content || '' }),
    fromAction: (a) => ({ label: a.label, content: a.content }),
  },

  choice: {
    group: 'talk', icon: '🔀', title: 'Choice',
    summary: (b) => `${(b.choices || []).length} choice(s)`,
    fields: [{ key: 'choices', label: 'Options', type: 'choices' }],
    toAction: (b) => ({
      type: 'choice', action: 'choice',
      choice: (b.choices || []).map((c) => ({ label: c.label, display: c.display })),
    }),
    fromAction: (a) => ({ choices: a.choice || [] }),
  },

  nightChoice: {
    group: 'talk', icon: '🌙', title: 'Night Choice',
    summary: (b) => `only at night — ${(b.choices || []).length} option(s)`,
    fields: [{ key: 'choices', label: 'Options (shown at night only)', type: 'choices' }],
    toAction: (b) => ({
      type: 'night_choice', action: 'choice',
      choice: (b.choices || []).map((c) => ({ label: c.label, display: c.display })),
    }),
    fromAction: (a) => ({ choices: a.choice || [] }),
  },

  idle: {
    group: 'talk', icon: '🗣️', title: 'Idle Chat',
    summary: () => 'random line from the unlocked pool',
    fields: [],
    toAction: () => ({ type: 'idle_chat', action: 'idle_chat' }),
    fromAction: () => ({}),
  },

  show: {
    group: 'stage', icon: '🎭', title: 'Show Character',
    summary: (b) => `${b.sprite || '?'} / ${b.expression || 'normal'} (${(b.position || 'CENTER').toLowerCase()})`,
    fields: [
      { key: 'sprite', label: 'Character', type: 'sprite' },
      { key: 'expression', label: 'Expression', type: 'sprite' },
      { key: 'position', label: 'Position', type: 'select', options: POSITIONS },
      { key: 'custom', label: 'Custom grid', type: 'grid', when: (b) => b.position === 'CUSTOM' },
    ],
    toAction: (b) => {
      const grid = b.position === 'CUSTOM' && b.custom ? b.custom : SPRITE_DEFAULTS;
      const expr = b.expression || 'normal';
      return {
        type: 'show_sprite', action: 'show',
        sprite: b.sprite || 'character',
        location: `${b.sprite || 'character'}/${expr}.png`,
        position: b.position || 'CENTER',
        ...grid,
      };
    },
    fromAction: (a) => ({
      sprite: a.sprite,
      expression: (a.location || '').split('/').pop().replace(/\.png$/, ''),
      position: a.position || 'CENTER',
      custom: { wRatio: a.wRatio, hRatio: a.hRatio, wFrameRatio: a.wFrameRatio, hFrameRatio: a.hFrameRatio, column: a.column, row: a.row },
    }),
  },

  hide: {
    group: 'stage', icon: '👋', title: 'Hide Character',
    summary: (b) => b.sprite || 'character',
    fields: [{ key: 'sprite', label: 'Character', type: 'sprite' }],
    toAction: (b) => ({ type: 'remove_sprite', action: 'remove', sprite: b.sprite || 'character' }),
    fromAction: (a) => ({ sprite: a.sprite }),
  },

  background: {
    group: 'stage', icon: '🖼️', title: 'Background',
    summary: (b) => b.background || 'none',
    fields: [{ key: 'background', label: 'Image', type: 'text', placeholder: 'asset/room.png' }],
    toAction: (b) => ({ type: 'modify_background', action: 'set', background: b.background || '' }),
    fromAction: (a) => ({ background: a.background }),
  },

  clearBackground: {
    group: 'stage', icon: '⬛', title: 'Clear Background',
    summary: () => 'back to the world',
    fields: [],
    toAction: () => ({ type: 'clear_background', action: 'clear' }),
    fromAction: () => ({}),
  },

  label: {
    group: 'flow', icon: '🏷️', title: 'Label',
    summary: (b) => b.name || 'unnamed',
    fields: [{ key: 'name', label: 'Label name', type: 'text', placeholder: 'start' }],
    toAction: (b) => ({ type: 'label', action: 'label', label: b.name || 'label' }),
    fromAction: (a) => ({ name: a.label }),
  },

  jump: {
    group: 'flow', icon: '➡️', title: 'Jump',
    summary: (b) => `→ ${b.target || '?'}`,
    fields: [{ key: 'target', label: 'Go to', type: 'label-ref' }],
    toAction: (b) => ({ type: 'transition', action: 'jump', label: b.target || '' }),
    fromAction: (a) => ({ target: a.label }),
  },

  if: {
    group: 'flow', icon: '❓', title: 'If',
    summary: (b) => {
      const c = CONDITIONS.find((x) => x.value === b.condition) || CONDITIONS[0];
      const val = c.needsValue ? ` ${b.value}` : '';
      return `${b.scope || 'SCENE'}·${b.var || '?'} ${c.label}${val} → ${b.target || '?'}`;
    },
    fields: [
      { key: 'scope', label: 'Save as', type: 'scope' },
      { key: 'var', label: 'Variable', type: 'var' },
      { key: 'condition', label: 'Test', type: 'select', options: CONDITIONS },
      { key: 'value', label: 'Value', type: 'text', when: (b) => (CONDITIONS.find((c) => c.value === b.condition) || {}).needsValue },
      { key: 'target', label: 'If true, jump to', type: 'label-ref' },
    ],
    toAction: (b) => {
      const action = { type: 'conditional', action: 'conditional', condition: b.condition || 'equal', var: b.var || '', end: 0 };
      if (b.scope) action.scope = b.scope;
      const c = CONDITIONS.find((x) => x.value === b.condition);
      if (c && c.needsValue) action.value = parseLiteral(b.value);
      return action;
    },
    fromAction: (a) => ({ scope: a.scope, var: a.var, condition: a.condition, value: a.value, end: a.end }),
  },

  next: {
    group: 'flow', icon: '⏭️', title: 'Next / Checkpoint',
    summary: (b) => `remember → ${b.target || '?'}`,
    fields: [{ key: 'target', label: 'Checkpoint label', type: 'label-ref' }],
    toAction: (b) => ({ type: 'next', action: 'next', label: b.target || '' }),
    fromAction: (a) => ({ target: a.label }),
  },

  end: {
    group: 'flow', icon: '🏁', title: 'End Scene',
    summary: () => 'close the screen',
    fields: [],
    toAction: () => ({ type: 'finish_dialogue', action: 'finish_dialogue' }),
    fromAction: () => ({}),
  },

  setVar: {
    group: 'state', icon: '📝', title: 'Set Variable',
    summary: (b) => {
      if (b.operation === 'increment_var') return `${b.scope || 'SCENE'}·${b.var || '?'} += ${b.value}`;
      if (b.operation === 'subtract_var') return `${b.scope || 'SCENE'}·${b.var || '?'} -= ${b.value}`;
      return `${b.scope || 'SCENE'}·${b.var || '?'} = ${b.value}`;
    },
    fields: [
      { key: 'scope', label: 'Save as', type: 'scope' },
      { key: 'var', label: 'Variable', type: 'var' },
      {
        key: 'operation', label: 'Change', type: 'select',
        options: [
          { value: 'set', label: 'set to' },
          { value: 'increment_var', label: 'add' },
          { value: 'subtract_var', label: 'subtract' },
        ],
      },
      { key: 'value', label: 'Value', type: 'text' },
    ],
    toAction: (b) => {
      const action = { type: 'modify_variable', action: b.operation || 'set', var: b.var || '', value: parseLiteral(b.value) };
      if (b.scope) action.scope = b.scope;
      return action;
    },
    fromAction: (a) => ({ scope: a.scope, var: a.var, operation: a.action, value: a.value }),
  },

  unlock: {
    group: 'state', icon: '🔓', title: 'Unlock Dialogues',
    summary: (b) => `+${(b.labels || []).length} idle line(s)`,
    fields: [{ key: 'labels', label: 'Labels to unlock', type: 'label-list' }],
    toAction: (b) => ({ type: 'unlock_dialogues', action: 'unlock_dialogues', events: b.labels || [] }),
    fromAction: (a) => ({ labels: a.events || [] }),
  },

  giveItem: {
    group: 'state', icon: '🎁', title: 'Give Item',
    summary: (b) => `${b.amount || 1}x ${b.item || '?'}`,
    fields: [
      { key: 'item', label: 'Item id', type: 'item' },
      { key: 'amount', label: 'Count', type: 'number', min: 1 },
    ],
    toAction: (b) => ({ type: 'give_item', action: 'give', item: b.item || '', amount: Number(b.amount) || 1 }),
    fromAction: (a) => ({ item: a.item, amount: a.amount }),
  },

  takeItem: {
    group: 'state', icon: '✋', title: 'Take Item',
    summary: (b) => `she keeps ${b.amount || 1}x ${b.item || '?'}`,
    fields: [
      { key: 'item', label: 'Item id', type: 'item' },
      { key: 'amount', label: 'Count', type: 'number', min: 1 },
    ],
    toAction: (b) => ({ type: 'take_item', action: 'take', item: b.item || '', amount: Number(b.amount) || 1 }),
    fromAction: (a) => ({ item: a.item, amount: a.amount }),
  },

  music: {
    group: 'audio', icon: '🎵', title: 'Music',
    summary: (b) => (b.music ? `♪ ${b.music}` : 'stop music'),
    fields: [{ key: 'music', label: 'Track (empty = stop)', type: 'text', placeholder: 'haggstrom' }],
    toAction: (b) => ({ type: 'play_music', action: 'play_music', music: b.music || null }),
    fromAction: (a) => ({ music: a.music }),
  },

  sound: {
    group: 'audio', icon: '🔊', title: 'Sound',
    summary: (b) => b.sound || 'none',
    fields: [{ key: 'sound', label: 'Sound', type: 'text', placeholder: 'teleport' }],
    toAction: (b) => ({ type: 'play_sound', action: 'play_sound', sound: b.sound || '' }),
    fromAction: (a) => ({ sound: a.sound }),
  },
};

export const BLOCK_BY_ACTION = {
  dialogue: 'say',
  choice: 'choice',
  night_choice: 'nightChoice',
  idle_chat: 'idle',
  show_sprite: 'show',
  remove_sprite: 'hide',
  modify_background: 'background',
  clear_background: 'clearBackground',
  label: 'label',
  next: 'next',
  finish_dialogue: 'end',
  unlock_dialogues: 'unlock',
  give_item: 'giveItem',
  take_item: 'takeItem',
  play_music: 'music',
  play_sound: 'sound',
  modify_variable: 'setVar',
  modify_global: 'setVar',
  conditional: 'if',
  conditional_global: 'if',
};

// transition is action-dependent: jump vs exit
export function blockKindForAction(action) {
  if (!action || !action.type) return null;
  if (action.type === 'transition') return action.action === 'jump' ? 'jump' : 'jump';
  return BLOCK_BY_ACTION[action.type] || null;
}

function truncate(text, n = 48) {
  if (!text) return '';
  return text.length > n ? text.slice(0, n - 1) + '…' : text;
}

// Strings stay strings; "true"/"false"/numbers become real values so conditions
// compare against the right JSON types.
export function parseLiteral(raw) {
  if (raw === undefined || raw === null) return '';
  const text = String(raw).trim();
  if (text === '') return '';
  if (text === 'true') return true;
  if (text === 'false') return false;
  if (/^-?\d+$/.test(text)) return Number(text);
  if (/^-?\d*\.\d+$/.test(text)) return Number(text);
  return text;
}

// Run: node --test test/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compile, suggest } from '../src/compiler.js';

const project = { character: 'cupa', startLabel: 'start', packName: 'Test', packFormat: 15 };

function block(kind, data) {
  return { kind, data };
}

test('emits meta start then labels with sequential ids', () => {
  const files = {
    'main.story': [
      block('label', { name: 'start' }),
      block('say', { label: 'Cupa', content: 'Hello.' }),
      block('end', {}),
    ],
  };
  const r = compile(project, files, ['main.story']);
  assert.deepEqual(r.errors, []);
  assert.equal(r.json[0].type, 'meta');
  assert.equal(r.json[0].action, 'start');
  assert.equal(r.json[0].id, 0);
  assert.equal(r.json[1].type, 'label');
  assert.equal(r.json[1].label, 'start');
  assert.equal(r.json[2].type, 'dialogue');
  assert.equal(r.json[3].type, 'finish_dialogue');
  assert.deepEqual(r.json.map((a) => a.id), [0, 1, 2, 3]);
});

test('puts the file containing startLabel first', () => {
  const files = {
    'a_idle.story': [block('idle', {})],
    'z_main.story': [block('label', { name: 'start' }), block('end', {})],
  };
  const r = compile(project, files, ['a_idle.story', 'z_main.story']);
  assert.equal(r.json[1].type, 'label');
  assert.equal(r.json[1].label, 'start');
});

test('resolves conditional target label to a real id', () => {
  const files = {
    'main.story': [
      block('label', { name: 'start' }),
      block('if', { scope: 'MAID', var: 'seen.night', condition: 'equal', value: 'true', _target: 'night' }),
      block('idle', {}),
      block('end', {}),
      block('label', { name: 'night' }),
      block('say', { label: 'Cupa', content: 'Night.' }),
      block('end', {}),
    ],
  };
  const r = compile(project, files, ['main.story']);
  assert.deepEqual(r.errors, []);
  const cond = r.json.find((a) => a.type === 'conditional');
  const nightLabel = r.json.find((a) => a.type === 'label' && a.label === 'night');
  assert.equal(cond.end, nightLabel.id);
  assert.equal(cond.var, 'seen.night');
  assert.equal(cond.scope, 'MAID');
  assert.equal(cond.value, true, 'value should be a real boolean, not a string');
});

test('reports missing jump target with a suggestion', () => {
  const files = {
    'main.story': [
      block('label', { name: 'start' }),
      block('jump', { target: 'go_nihgt' }),
      block('label', { name: 'go_to_night' }),
      block('end', {}),
    ],
  };
  const r = compile(project, files, ['main.story']);
  assert.equal(r.errors.length, 1);
  assert.match(r.errors[0], /go_nihgt/);
  assert.match(r.errors[0], /go_to_night/);
});

test('reports duplicate labels', () => {
  const files = {
    'a.story': [block('label', { name: 'start' })],
    'b.story': [block('label', { name: 'start' })],
  };
  const r = compile(project, files, ['a.story', 'b.story']);
  assert.ok(r.errors.some((e) => /Duplicate label/.test(e)));
});

test('reports missing start label', () => {
  const files = { 'main.story': [block('say', { content: 'hi' })] };
  const r = compile(project, files, ['main.story']);
  assert.ok(r.errors.some((e) => /Start label/.test(e)));
});

test('strips studio-only _target field from shipped json', () => {
  const files = {
    'main.story': [
      block('label', { name: 'start' }),
      block('if', { var: 'x', condition: 'equal', value: '1', _target: 'start' }),
      block('end', {}),
    ],
  };
  const r = compile(project, files, ['main.story']);
  for (const a of r.json) {
    assert.ok(!Object.keys(a).some((k) => k.startsWith('_')), 'no underscore keys in output');
  }
});

test('sprite block emits documented default geometry', () => {
  const files = {
    'main.story': [
      block('label', { name: 'start' }),
      block('show', { sprite: 'cupa', expression: 'happy', position: 'CENTER' }),
      block('end', {}),
    ],
  };
  const r = compile(project, files, ['main.story']);
  const s = r.json.find((a) => a.type === 'show_sprite');
  assert.equal(s.location, 'cupa/happy.png');
  assert.equal(s.wRatio, 16);
  assert.equal(s.hRatio, 9);
  assert.equal(s.wFrameRatio, 4);
  assert.equal(s.hFrameRatio, 8);
  assert.equal(s.column, 7);
  assert.equal(s.row, 1);
});

test('choice labels are validated as jump targets', () => {
  const files = {
    'main.story': [
      block('label', { name: 'start' }),
      block('choice', { choices: [{ label: 'nope', display: 'Try' }] }),
      block('end', {}),
    ],
  };
  const r = compile(project, files, ['main.story']);
  assert.ok(r.errors.some((e) => /Choice "Try" points at "nope"/.test(e)));
});

test('suggest finds the close match', () => {
  assert.equal(suggest('go_nihgt', ['go_to_night', 'idle', 'start']), 'go_to_night');
  assert.equal(suggest('zzzzzzzz', ['start', 'idle']), null);
});

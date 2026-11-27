const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../desktop-ui/src/anchorStatus.ts'), 'utf8');
const context = { exports: {}, require: name => {
  assert.equal(name, './components');
  return { anchorLiveUrl: anchor => anchor.live_url || '' };
} };
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
const { sortedAnchors, monitoredAnchors, isMonitoredAnchor } = context.exports;
const now = Math.floor(Date.now() / 1000);
const anchors = [
  { id: 'disabled-live', name: 'A', enabled_recording: false, last_live_status: 'live', last_resolved_at: now },
  { id: 'enabled-idle', name: 'B', enabled_recording: true, last_live_status: 'offline', last_resolved_at: now },
  { id: 'enabled-live', name: 'C', enabled_recording: true, last_live_status: 'live', last_resolved_at: now },
  { id: 'enabled-recording', name: 'D', enabled_recording: true },
  { id: 'default-enabled', name: 'E' },
];
const state = { anchors, status: { running: true, room_states: { 'enabled-recording': { state: 'recording' } } } };
assert.deepEqual(Array.from(sortedAnchors(state), a => a.id), ['enabled-recording', 'enabled-live', 'enabled-idle', 'default-enabled', 'disabled-live']);
assert.equal(monitoredAnchors(state).length, 4);
assert.equal(isMonitoredAnchor(anchors[4]), true);
assert.equal(monitoredAnchors({ ...state, anchors: [anchors[0]] }).length, 0);
assert.equal(sortedAnchors(state, 'a')[0].id, 'disabled-live');
assert.equal(anchors[0].id, 'disabled-live', 'Sorting must not mutate source order');
console.log('Anchor visibility and ordering: 6 assertions passed');

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { prepareStableLicense } = require('../electron/license-storage.cjs');

test('copies a legacy license into the stable app-id directory', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bolu-license-'));
  const appData = path.join(root, 'app-data');
  const engine = path.join(appData, '播录助手', 'engine');
  const legacy = path.join(engine, 'config', 'license.json');
  fs.mkdirSync(path.dirname(legacy), { recursive: true });
  fs.writeFileSync(legacy, JSON.stringify({ code: 'LR1-existing-license' }));

  const target = prepareStableLicense(appData, engine);

  assert.equal(target, path.join(appData, 'com.boluzhushou.desktop', 'license.json'));
  assert.deepEqual(JSON.parse(fs.readFileSync(target, 'utf8')), { code: 'LR1-existing-license' });
});

test('never overwrites an existing stable license', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bolu-license-'));
  const appData = path.join(root, 'app-data');
  const engine = path.join(appData, '播录助手', 'engine');
  const target = path.join(appData, 'com.boluzhushou.desktop', 'license.json');
  const legacy = path.join(engine, 'config', 'license.json');
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.mkdirSync(path.dirname(legacy), { recursive: true });
  fs.writeFileSync(target, JSON.stringify({ code: 'LR1-current' }));
  fs.writeFileSync(legacy, JSON.stringify({ code: 'LR1-legacy' }));

  prepareStableLicense(appData, engine);

  assert.deepEqual(JSON.parse(fs.readFileSync(target, 'utf8')), { code: 'LR1-current' });
});

test('uses the bundled owner license when no existing license is available', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bolu-license-'));
  const appData = path.join(root, 'app-data');
  const engine = path.join(appData, '播录助手', 'engine');
  const bundled = path.join(root, 'resources', 'defaults', 'owner-license.json');
  fs.mkdirSync(path.dirname(bundled), { recursive: true });
  fs.writeFileSync(bundled, JSON.stringify({ code: 'LR1-owner-device' }));

  const target = prepareStableLicense(appData, engine, bundled);

  assert.deepEqual(JSON.parse(fs.readFileSync(target, 'utf8')), { code: 'LR1-owner-device' });
});

const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
let commit = process.env.BOLU_BUILD_COMMIT || '';
if (!commit) {
  try {
    commit = execFileSync('git', ['rev-parse', '--short=12', 'HEAD'], {
      cwd: root,
      encoding: 'utf8'
    }).trim();
  } catch {
    commit = 'unknown';
  }
}

const target = path.join(root, 'build', 'generated', 'build-info.json');
fs.mkdirSync(path.dirname(target), { recursive: true });
fs.writeFileSync(target, `${JSON.stringify({ commit }, null, 2)}\n`, 'utf8');
console.log(`Build commit: ${commit}`);

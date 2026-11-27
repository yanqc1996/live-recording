const { execFileSync } = require('node:child_process');
const path = require('node:path');
if (process.platform === 'darwin') {
  const root = path.join(__dirname, '..', 'electron');
  execFileSync('/usr/bin/clang', ['-O2', '-framework', 'CoreAudio',
    path.join(root, 'audio-route-monitor.c'), '-o', path.join(root, 'audio-route-monitor')], { stdio: 'inherit' });
}

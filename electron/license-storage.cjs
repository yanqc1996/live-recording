const fs = require('node:fs');
const path = require('node:path');

const LICENSE_DATA_DIR = 'com.boluzhushou.desktop';

function looksLikeLicenseRecord(candidate) {
  try {
    const payload = JSON.parse(fs.readFileSync(candidate, 'utf8'));
    return Boolean(payload && typeof payload === 'object' && typeof payload.code === 'string' && payload.code);
  } catch {
    return false;
  }
}

function legacyLicenseCandidates(appDataPath, currentEngineRoot) {
  const names = ['播录助手', 'LiveRecorder', 'live-recorder-desktop', LICENSE_DATA_DIR];
  return [
    path.join(currentEngineRoot, 'config', 'license.json'),
    ...names.map((name) => path.join(appDataPath, name, 'engine', 'config', 'license.json')),
  ];
}

function prepareStableLicense(appDataPath, currentEngineRoot, bundledOwnerLicense = '') {
  const target = path.join(appDataPath, LICENSE_DATA_DIR, 'license.json');
  fs.mkdirSync(path.dirname(target), { recursive: true });
  if (fs.existsSync(target)) return target;

  const seen = new Set([path.resolve(target)]);
  const candidates = legacyLicenseCandidates(appDataPath, currentEngineRoot);
  if (bundledOwnerLicense) candidates.push(bundledOwnerLicense);
  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (seen.has(resolved)) continue;
    seen.add(resolved);
    if (!looksLikeLicenseRecord(candidate)) continue;
    try {
      fs.copyFileSync(candidate, target, fs.constants.COPYFILE_EXCL);
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
    }
    break;
  }
  return target;
}

module.exports = { LICENSE_DATA_DIR, legacyLicenseCandidates, prepareStableLicense };

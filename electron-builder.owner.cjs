const { build } = require('./package.json');

module.exports = {
  ...build,
  artifactName: '${productName}-${version}-owner-${arch}.${ext}',
  extraResources: [
    ...build.extraResources,
    {
      from: 'build/owner-license/license.json',
      to: 'defaults/owner-license.json',
    },
  ],
};

// Regenerate fonts_bundle.js from real font files on disk.
// Run after updating font files:  node scripts/build-fonts-bundle.js
//
// This embeds the Arabic fonts as base64 so PDF export works in every
// environment (Hugging Face / Docker / local) without depending on
// Git LFS-checked-out files, which are often just pointer stubs in CI.
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const fonts = [
  { name: 'TheSansArabic-Light', file: 'assets/fonts/TheSansArabic-Light.otf', format: 'opentype' },
  { name: 'TheSansArabic-Bold', file: 'assets/fonts/BahijTheSansArabic-Bold.ttf', format: 'truetype' },
];

let out = '// AUTO-GENERATED: Embedded Arabic font data (base64) so PDF export\n' +
          '// works in any environment (Hugging Face / Docker / local) without Git LFS.\n' +
          '// Regenerate with: node scripts/build-fonts-bundle.js\n\n';

fonts.forEach(f => {
  const fp = path.join(ROOT, f.file);
  if (!fs.existsSync(fp)) {
    console.error('ERROR: font file not found: ' + fp);
    console.error('Run "git lfs pull" first to fetch real font bytes.');
    process.exit(1);
  }
  const buf = fs.readFileSync(fp);
  const isPointer = buf.length < 500 || buf.toString('utf8', 0, Math.min(100, buf.length)).indexOf('git-lfs') !== -1;
  if (isPointer) {
    console.error('ERROR: ' + fp + ' is a Git-LFS pointer (' + buf.length + ' bytes), not real font data.');
    console.error('Run "git lfs pull" first to fetch real font bytes.');
    process.exit(1);
  }
  const b64 = buf.toString('base64');
  const varName = f.name.replace(/-/g, '_');
  out += '// ' + f.name + ' (' + buf.length + ' bytes, ' + f.format + ')\n';
  out += 'var ' + varName + ' = "' + b64 + '";\n\n';
});

out += 'module.exports = {\n';
out += fonts.map(f => {
  const varName = f.name.replace(/-/g, '_');
  return '  ' + varName + ': { family: "' + f.name + '", format: "' + f.format + '", data: ' + varName + ' }';
}).join(',\n');
out += '\n};\n';

const outPath = path.join(ROOT, 'fonts_bundle.js');
fs.writeFileSync(outPath, out);
console.log('✓ Wrote ' + outPath + ' (' + out.length + ' bytes)');
console.log('  Fonts: ' + fonts.map(f => f.name).join(', '));

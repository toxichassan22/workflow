const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const FONT_DIR = path.join(__dirname, 'assets', 'fonts');

function fontFaceCss() {
  const fonts = [
    { family: 'TheSansArabic-Light', file: 'THESANSARABIC-LIGHT.ttf' },
    { family: 'TheSansArabic-Bold', file: 'THESANSARABIC-BOLD.ttf' },
  ];
  return fonts.map(f => {
    const fp = path.join(FONT_DIR, f.file);
    if (!fs.existsSync(fp)) return '';
    const uri = path.resolve(fp).replace(/\\/g, '/');
    return `@font-face { font-family: '${f.family}'; src: url('file:///${uri}') format('truetype'); font-weight: normal; font-style: normal; }`;
  }).join('\n');
}

function baseCss() {
  return `
@page { size: 1280px 720px; margin: 0; }
* { margin: 0; padding: 0; box-sizing: border-box; }
${fontFaceCss()}
body { direction: rtl; font-family: 'TheSansArabic-Light', 'TheSansArabic-Bold', Tahoma, Arial, sans-serif; }
.slide { width: 1280px; height: 720px; direction: rtl; position: relative; overflow: hidden; page-break-after: always; page-break-inside: avoid; }
.slide:last-child { page-break-after: auto; }
img { max-width: 100%; max-height: 100%; object-fit: cover; }
`;
}

async function generatePdf(slidesHtml, outputPath) {
  const fullHtml = `<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <style>${baseCss()}</style>
</head>
<body>
${slidesHtml}
</body>
</html>`;

  const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'] });
  const page = await browser.newPage();
  await page.setContent(fullHtml, { waitUntil: 'load' });
  await page.waitForTimeout(500);

  await page.pdf({
    path: outputPath,
    width: '1280px',
    height: '720px',
    printBackground: true,
    margin: { top: '0', right: '0', bottom: '0', left: '0' },
  });

  await browser.close();
  return outputPath;
}

if (require.main === module) {
  const testHtml = `
<div class="slide" style="background:#FBFAF8;padding:0;">
  <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 30px;border-bottom:1px solid rgba(122,12,12,0.1)">
    <span style="font-size:13px;font-weight:700;color:#7A0C0C">شركة منافع الاقتصادية للعقار</span>
    <span style="font-size:11px;color:#888">دراسة جدوى</span>
  </div>
  <div style="padding:30px">
    <div style="font-size:20px;font-weight:700;color:#7A0C0C">المؤشرات المالية</div>
    <div style="display:flex;gap:16px;margin-top:20px">
      <div style="flex:1;background:#FFF;border-radius:14px;padding:20px;box-shadow:0 2px 16px rgba(0,0,0,0.06)">
        <div style="font-size:11px;color:#888">إجمالي التكلفة</div>
        <div style="font-size:28px;font-weight:700;color:#7A0C0C">146 مليون ريال</div>
      </div>
      <div style="flex:1;background:#FFF;border-radius:14px;padding:20px;box-shadow:0 2px 16px rgba(0,0,0,0.06)">
        <div style="font-size:11px;color:#888">العائد الاستثماري</div>
        <div style="font-size:28px;font-weight:700;color:#7A0C0C">24.2%</div>
      </div>
    </div>
  </div>
</div>`;

  generatePdf(testHtml, path.join(__dirname, 'test_node_output.pdf'))
    .then(() => console.log('Done: test_node_output.pdf'))
    .catch(e => console.error(e));
}

module.exports = { generatePdf };

/* Print the two documentation HTML files to client-ready PDFs.
   Runs with the repo's local playwright, driving the system Chrome. */
const { chromium } = require('playwright');
const path = require('path');

const CHROME =
  process.env.CHROME_PATH ||
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

const DOCS = [
  { html: 'file-tree.html', pdf: 'LandLoom-File-Tree.pdf' },
  { html: 'site-overview.html', pdf: 'LandLoom-Site-Overview.pdf' },
];

const FOOTER = [
  '<div style="width:100%;font-size:7.5px;color:#8a93a0;padding:0 13mm;',
  'display:flex;justify-content:space-between;font-family:Arial,sans-serif;">',
  '<span style="letter-spacing:2px;">LANDLOOM</span>',
  '<span>&#1589;&#1601;&#1581;&#1577; <span class="pageNumber"></span> / <span class="totalPages"></span></span>',
  '</div>',
].join('');

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  for (const d of DOCS) {
    const page = await browser.newPage();
    const fileUrl = 'file:///' + path.resolve(__dirname, d.html).split('\\').join('/');
    await page.goto(fileUrl, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    const out = path.resolve(__dirname, d.pdf);
    await page.pdf({
      path: out,
      format: 'A4',
      printBackground: true,
      displayHeaderFooter: true,
      headerTemplate: '<span></span>',
      footerTemplate: FOOTER,
      margin: { top: '14mm', bottom: '16mm', left: '13mm', right: '13mm' },
    });
    console.log('OK', out);
    await page.close();
  }
  await browser.close();
})().catch((err) => {
  console.error(err);
  process.exit(1);
});


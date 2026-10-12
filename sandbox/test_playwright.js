const { chromium } = require('playwright');
(async () => {
  try {
    console.log('Launching browser...');
    const browser = await chromium.launch({
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
    });
    console.log('Browser launched successfully!');
    await browser.close();
    console.log('Browser closed successfully!');
    process.exit(0);
  } catch (err) {
    console.error('Playwright error:', err);
    process.exit(1);
  }
})();

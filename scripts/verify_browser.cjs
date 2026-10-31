/* CI-only browser verification. The spectator website itself has no JavaScript. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const output = path.join(root, 'qa-output');
const mime = {'.html':'text/html', '.css':'text/css', '.png':'image/png', '.pdf':'application/pdf', '.svg':'image/svg+xml'};
const server = http.createServer((req, res) => {
  const requested = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  const filename = path.resolve(root, '.' + (requested === '/' ? '/index.html' : requested));
  if (!filename.startsWith(root + path.sep) || !fs.existsSync(filename) || !fs.statSync(filename).isFile()) {
    res.writeHead(404).end('Not found');
    return;
  }
  res.writeHead(200, {'Content-Type': mime[path.extname(filename)] || 'application/octet-stream'});
  fs.createReadStream(filename).pipe(res);
});

(async () => {
  fs.mkdirSync(output, {recursive:true});
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const browser = await chromium.launch();
  const results = [];
  try {
    for (const width of [360, 390, 768, 1440]) {
      const context = await browser.newContext({viewport:{width,height:900}, deviceScaleFactor:1});
      const page = await context.newPage();
      const errors = [];
      const external = [];
      const failed = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('request', request => {if (!request.url().startsWith(url) && !request.url().startsWith('data:')) external.push(request.url());});
      page.on('requestfailed', request => failed.push(request.url()));
      page.on('response', response => {if (response.status() >= 400) failed.push(`${response.status()} ${response.url()}`);});
      const response = await page.goto(url, {waitUntil:'networkidle'});
      assert.equal(response.status(), 200);
      await page.locator('img').evaluateAll(images => images.forEach(image => image.loading = 'eager'));
      await page.waitForFunction(() => [...document.images].every(image => image.complete && image.naturalWidth > 0));
      const metrics = await page.evaluate(() => ({
        viewport: innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        bodyWidth: document.body.scrollWidth,
        rows: document.querySelectorAll('tr[data-mile]').length,
        scripts: document.scripts.length,
        controls: document.querySelectorAll('input,button,select,textarea,form,iframe').length,
        images: [...document.images].map(image => {
          const box = image.getBoundingClientRect();
          const style = getComputedStyle(image);
          return {src:image.getAttribute('src'), width:box.width, height:box.height, naturalWidth:image.naturalWidth, naturalHeight:image.naturalHeight, visible:style.display !== 'none' && style.visibility !== 'hidden', alt:image.alt};
        }),
        overflowing: [...document.querySelectorAll('main *')].filter(element => {
          const box = element.getBoundingClientRect();
          return box.width > 0 && (box.right > innerWidth + 1 || box.left < -1) && getComputedStyle(element).position !== 'absolute';
        }).slice(0,10).map(element => element.tagName + '.' + element.className)
      }));
      await page.screenshot({path:path.join(output, `page-${width}.png`), fullPage:true});
      results.push({width, ...metrics, errors, external, failed});
      assert.ok(metrics.documentWidth <= width + 1 && metrics.bodyWidth <= width + 1, `${width}px: horizontal page overflow`);
      assert.deepEqual(metrics.overflowing, [], `${width}px: overflowing content`);
      assert.equal(metrics.rows,27);
      assert.equal(metrics.scripts,0);
      assert.equal(metrics.controls,0);
      assert.equal(metrics.images.length,3);
      for (const image of metrics.images) {
        assert.ok(image.visible && image.width >= 280 && image.height > 100 && image.alt, `${width}px: hidden or tiny map ${image.src}`);
      }
      assert.deepEqual(errors, [], `${width}px: JS errors`);
      assert.deepEqual(external, [], `${width}px: external runtime requests`);
      assert.deepEqual(failed, [], `${width}px: failed assets`);
      await context.close();
    }
    console.log('PASS: responsive layout at 360, 390, 768, 1440px; all assets loaded; zero runtime controls/scripts/external requests.');
  } finally {
    fs.writeFileSync(path.join(output,'browser-results.json'), JSON.stringify(results,null,2));
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {console.error(error); process.exitCode=1; server.close();});

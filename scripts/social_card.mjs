// Renders the link-preview image (og.jpg) and app icons from the running site.
// Needs Playwright: `npx playwright install chromium` once, then
//   python3 -m http.server 8000 &   (from the repo root)
//   node scripts/social_card.mjs http://localhost:8000/
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const site = process.argv[2] || 'http://localhost:8000/';
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM || undefined,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
  proxy: process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY, bypass: '127.0.0.1,localhost' } : undefined,
});

// Social card: the real app, Europe in 1815 with historical borders and the
// Battle of Waterloo (Q48314) open.
const ctx = await browser.newContext({
  viewport: { width: 1200, height: 630 }, deviceScaleFactor: 2, colorScheme: 'light',
  // Wikimedia rate-limits the headless browser's own user agent.
  userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
});
const page = await ctx.newPage();
await page.goto(`${site}#y=1815&w=5&m=49.2,10.5,4.15&a=48314`, { waitUntil: 'load' });
await page.waitForTimeout(6000);
// Historical borders are on by default in 1815. The attribution stays in the
// app; the card has no room for its button.
await page.addStyleTag({ content: '.maplibregl-ctrl-attrib { display: none !important; }' });
await page.mouse.move(5, 625); // no hover card
await page.waitForTimeout(9000);
await page.screenshot({ path: path.join(root, 'og.jpg'), type: 'jpeg', quality: 86 });
await ctx.close();

// Icons from icons/icon.svg.
const icon = await browser.newPage();
for (const [size, name] of [[180, 'apple-touch-icon.png'], [192, 'icon-192.png'], [512, 'icon-512.png']]) {
  await icon.setViewportSize({ width: size, height: size });
  await icon.goto(`${site}icons/icon.svg`);
  await icon.screenshot({ path: path.join(root, 'icons', name) });
}
await browser.close();
console.log('wrote og.jpg and icons/');

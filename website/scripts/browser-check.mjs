import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from '@playwright/test';

const root = new URL(process.env.PORTAL_TEST_URL || 'http://127.0.0.1:4321/');
if (!root.pathname.endsWith('/')) root.pathname += '/';
const pages = ['', 'examples/aimd/', 'examples/qram/', 'docs/'];
const artifactDir = `artifacts/${root.pathname === '/' ? 'root' : 'subpath'}`;
await mkdir(artifactDir, { recursive: true });
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const context = await browser.newContext({ reducedMotion: 'reduce' });
const page = await context.newPage();
const errors = [];
const external = new Set();
const links = new Set();
const checks = [];
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => {
  const url = new URL(request.url());
  if (url.protocol.startsWith('http') && url.origin !== root.origin) external.add(url.href);
});

try {
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const route of pages) {
      const response = await page.goto(new URL(route, root).href, { waitUntil: 'networkidle' });
      assert.equal(response?.status(), 200, `Page status: ${route}`);
      assert.equal(await page.locator('h1').count(), 1, `One h1: ${route}`);
      assert.equal(await page.locator('html').getAttribute('lang'), 'zh-CN');
      assert.ok(await page.locator('h1').isVisible());
      const footer = page.getByRole('contentinfo');
      assert.deepEqual(await footer.getByRole('heading').allTextContents(), ['用户指南', '了解系统']);
      assert.ok(await footer.getByRole('link', { name: '用户指南', exact: true }).isVisible());
      assert.ok(await footer.getByRole('link', { name: '系统介绍', exact: true }).isVisible());
      const footerColumns = await footer.getByRole('navigation').evaluateAll(nodes => nodes.map(node => {
        const { x, y, right } = node.getBoundingClientRect();
        return { x, y, right };
      }));
      assert.equal(footerColumns.length, 2);
      assert.ok(Math.abs(footerColumns[0].y - footerColumns[1].y) <= 1 && footerColumns[1].x >= footerColumns[0].right, `Footer has two non-overlapping columns at ${width}px: ${route}`);
      const dimensions = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: innerWidth }));
      assert.ok(dimensions.content <= dimensions.viewport + 1, `Overflow at ${width}px: ${route} (${dimensions.content})`);
      for (const href of await page.locator('a[href]').evaluateAll(nodes => nodes.map(node => node.href))) {
        const url = new URL(href);
        if (url.origin === root.origin) {
          assert.ok(url.pathname.startsWith(root.pathname), `Link escapes deployment base: ${url.href}`);
          assert.ok(!url.pathname.includes('undefined'), `Invalid link: ${url.href}`);
          url.hash = '';
          links.add(url.href);
        }
      }
      if ((width === 390 || width === 1440) && ['', 'examples/aimd/', 'docs/'].includes(route)) {
        const name = route === '' ? 'home' : route.startsWith('examples') ? 'aimd' : 'docs';
        await page.screenshot({ path: `${artifactDir}/${name}-${width}.png`, fullPage: true });
        if (route === '') await footer.screenshot({ path: `${artifactDir}/footer-${width}.png` });
      }
      checks.push(`${width}px: ${route || '/'}: no overflow`);
    }
  }
  for (const href of links) {
    const response = await context.request.get(href);
    assert.equal(response.status(), 200, `Internal link: ${href}`);
  }

  await page.goto(new URL('examples/aimd/', root).href, { waitUntil: 'networkidle' });
  assert.ok(await page.getByRole('heading', { level: 1, name: '水分子 AIMD 运行示例' }).isVisible());
  await page.getByRole('region', { name: /^逻辑电路图/ }).waitFor();
  await page.getByRole('region', { name: /^物理电路图/ }).waitFor();
  const results = page.locator('.analysis-results');
  assert.ok(await results.getByText(/(?:已有|已保存|预先).*(?:结果|轨迹)/).isVisible());
  const source = results.locator('.analysis-result-source');
  await source.locator('summary').click();
  assert.ok(await source.getByText(/本页使用已导入的示例轨迹/).isVisible());
  const sourceLink = source.getByRole('link', { name: '查看数据来源说明', exact: true });
  assert.ok(await sourceLink.isVisible());
  assert.equal((await context.request.get(new URL(await sourceLink.getAttribute('href'), root).href)).status(), 200);
  await source.locator('summary').click();
  const replay = results.getByRole('button', { name: '重新播放', exact: true });
  await replay.waitFor();
  await page.waitForFunction(() => !document.querySelector('[data-restart]')?.disabled);
  const workbench = results.locator('[data-aimd-workbench]');
  const molecule = results.getByRole('img', { name: /^水分子三维动画/ });
  const chart = results.locator('[data-plot]').first();
  await molecule.scrollIntoViewIfNeeded();
  assert.equal(await workbench.getAttribute('data-frame'), '0', 'Reduced motion preserves the initial frame');
  assert.ok(await molecule.isVisible());
  const geometryAtStart = await results.locator('[data-value]').allTextContents();
  await replay.click();
  await page.waitForFunction(() => Number(document.querySelector('[data-aimd-workbench]')?.getAttribute('data-frame')) > 60);
  await chart.press('End');
  const recordedFrame = Number(await workbench.getAttribute('data-frame'));
  assert.ok(recordedFrame > 60, 'Replay advances the saved trajectory');
  assert.equal(Number(await molecule.getAttribute('data-frame')), recordedFrame, 'The 3D view follows the selected frame');
  assert.ok((await results.locator('[data-time-cursor]').evaluateAll(nodes => nodes.map(node => Number(node.getAttribute('data-time-cursor'))))).every(frame => frame === recordedFrame), 'All curves follow the selected frame');
  assert.notDeepEqual(await results.locator('[data-value]').allTextContents(), geometryAtStart, 'Geometry updates with the trajectory');
  await replay.click();
  await page.waitForFunction(previous => Number(document.querySelector('[data-aimd-workbench]')?.getAttribute('data-frame')) < previous, recordedFrame);
  await page.waitForFunction(() => Number(document.querySelector('[data-aimd-workbench]')?.getAttribute('data-frame')) > 5);
  await chart.press('Home');
  assert.equal(await molecule.getAttribute('data-frame'), '0');
  assert.deepEqual(await results.locator('[data-value]').allTextContents(), geometryAtStart);
  await results.screenshot({ path: `${artifactDir}/aimd-replay-1440.png` });
  checks.push('AIMD saved results and source disclosure, loaded circuits, replay restart, synchronized 3D/curves and keyboard frame selection');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(new URL('examples/aimd/', root).href, { waitUntil: 'networkidle' });
  const menu = page.locator('.mobile-menu');
  await menu.locator('summary').click();
  assert.ok(await menu.getByRole('link', { name: '使用指南' }).isVisible());
  await page.keyboard.press('Escape');
  assert.equal(await menu.getAttribute('open'), null);
  await page.goto(root.href);
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement?.textContent?.trim()), '跳转到正文');
  assert.ok(await page.locator('.skip-link').evaluate(node => getComputedStyle(node).outlineStyle !== 'none'));
  await menu.locator('summary').click();
  await menu.getByRole('link', { name: '应用示例' }).click();
  await page.getByRole('link', { name: /水分子 AIMD.*查看示例/ }).click();
  await page.waitForURL(new URL('examples/aimd/', root).href);
  assert.ok(await page.getByRole('heading', { level: 1, name: '水分子 AIMD 运行示例' }).isVisible());
  assert.equal(await page.locator('a[href="#"], a[href=""]').count(), 0);
  await replay.scrollIntoViewIfNeeded();
  await replay.click();
  await page.waitForFunction(() => Number(document.querySelector('[data-aimd-workbench]')?.getAttribute('data-frame')) > 5);
  assert.ok(await page.locator('html').evaluate(node => node.scrollWidth <= innerWidth));
  await page.screenshot({ path: `${artifactDir}/aimd-replay-390.png`, fullPage: true });
  for (const link of await page.locator('a[download]').all()) {
    const response = await context.request.get(new URL(await link.getAttribute('href'), root).href);
    assert.equal(response.status(), 200);
  }
  const footer = page.getByRole('contentinfo');
  await footer.getByRole('link', { name: '用户指南', exact: true }).click();
  await page.waitForURL(new URL('docs/', root).href);
  await footer.getByRole('link', { name: '系统介绍', exact: true }).click();
  await page.waitForURL(new URL('#system', root).href);
  assert.ok(await page.locator('#system').isVisible());
  checks.push('Mobile navigation, keyboard focus, AIMD replay, downloads and two-column footer links');

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(new URL('docs/', root).href, { waitUntil: 'networkidle' });
  assert.ok(await page.locator('.site-header').isVisible());
  const chapters = page.getByRole('navigation', { name: '指南章节' });
  assert.deepEqual(await chapters.getByRole('link').allTextContents(), ['系统介绍', '使用指南', '应用示例']);
  assert.equal(await page.locator('.guide-content').getByRole('heading', { name: /^(系统功能|接口概览)$/, includeHidden: true }).count(), 0);
  assert.match(await page.locator('.guide-chapter:not([hidden])').innerText(), /通用融合编程框架/);
  await chapters.getByRole('link', { name: '使用指南', exact: true }).click();
  assert.ok(await page.locator('.guide-content').getByRole('heading', { name: '使用指南', exact: true }).isVisible());
  assert.equal(await page.locator('.guide-chapter:not([hidden])').count(), 1);
  await chapters.getByRole('link', { name: '应用示例', exact: true }).click();
  assert.ok(await page.locator('.guide-content').getByRole('link', { name: '水分子 AIMD', exact: true }).isVisible());
  assert.equal(await page.locator('.guide-content').getByRole('heading', { name: '使用指南', exact: true }).isVisible(), false);
  await page.reload();
  assert.equal(await chapters.locator('[aria-current]').innerText(), '应用示例');
  await page.goBack();
  assert.equal(await chapters.locator('[aria-current]').innerText(), '使用指南');
  await page.setViewportSize({ width: 390, height: 844 });
  await chapters.getByRole('link', { name: '系统介绍', exact: true }).click();
  assert.match(await page.locator('.guide-chapter:not([hidden])').innerText(), /通用融合编程框架/);
  assert.ok(await page.locator('html').evaluate(node => node.scrollWidth <= innerWidth));
  await chapters.getByRole('link', { name: '应用示例', exact: true }).click();
  assert.ok(await page.locator('.guide-content').getByRole('link', { name: '水分子 AIMD' }).isVisible());
  assert.ok(await page.locator('html').evaluate(node => node.scrollWidth <= innerWidth));
  checks.push('Portal guide: three chapters, general-purpose framework introduction, removed sections absent, deep links, browser back and mobile layout');

  const missing = await page.goto(new URL('this-page-does-not-exist/', root).href);
  assert.equal(missing?.status(), 404);
  await page.getByRole('heading', { name: '这个页面还没有连接。' }).waitFor();
  await page.getByRole('link', { name: '返回首页', exact: true }).click();
  await page.waitForURL(root.href);
  checks.push('404 page and return navigation');
  assert.deepEqual(errors, [], 'Browser JavaScript errors');
  assert.deepEqual([...external], [], 'Unexpected external resource requests');
  const report = { root: root.href, checks, internalLinksChecked: links.size, errors, externalRequests: [...external] };
  await writeFile(`${artifactDir}/report.json`, JSON.stringify(report, null, 2));
  console.log(`Passed ${checks.length} browser scenarios and ${links.size} internal links. Screenshots: ${artifactDir}/`);
} finally {
  await browser.close();
}

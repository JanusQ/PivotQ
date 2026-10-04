import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from '@playwright/test';

const root = new URL(process.env.PORTAL_TEST_URL || 'http://127.0.0.1:4321/');
if (!root.pathname.endsWith('/')) root.pathname += '/';
const pages = [
  '', 'examples/aimd/', 'examples/qram/', 'docs/', 'docs/installation/', 'docs/quickstart/',
  ...['components-actors', 'workflows', 'observability', 'jobs', 'hardware-profiles',
      'performance', 'providers'].map(name => `docs/${name}/`),
  'docs/api/',
  ...['runtime', 'components', 'workflows', 'quantum', 'providers', 'jobs',
      'observability', 'performance', 'errors'].map(name => `docs/api/${name}/`),
];
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
      if ((width === 390 || width === 1440) && ['', 'examples/aimd/', 'docs/', 'docs/installation/'].includes(route)) {
        const name = route === '' ? 'home' : route.startsWith('examples') ? 'aimd' : route === 'docs/installation/' ? 'docs-installation' : 'docs';
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
  assert.ok(await menu.getByRole('link', { name: '参考文档' }).isVisible());
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
  const sidebar = page.locator('#starlight__sidebar');
  assert.deepEqual(await sidebar.locator('.top-level > li > details > summary .large').allTextContents(), ['系统介绍', '使用文档', '应用示例']);
  assert.deepEqual(await sidebar.locator('.top-level > li > details > ul > li > details > summary .large').allTextContents(), [
    '入门', '混合编程', '运行与管理', '性能建模与预测', '后端扩展', 'API 参考',
  ]);
  async function expandDocsGroup(label) {
    const summary = sidebar.locator('summary').filter({ hasText: new RegExp(`^${label}$`) });
    if (!await summary.evaluate(node => node.parentElement.open)) await summary.click();
  }
  assert.ok(await sidebar.getByRole('link', { name: '安装', exact: true }).isVisible());
  assert.ok(await page.locator('.right-sidebar').isVisible());
  await sidebar.getByRole('link', { name: '安装', exact: true }).click();
  await page.waitForURL(new URL('docs/installation/', root).href);
  assert.ok(await page.getByRole('heading', { level: 1, name: '安装 PivotQ' }).isVisible());
  assert.ok(await page.locator('.pagination-links').isVisible());
  await sidebar.getByRole('link', { name: '快速上手', exact: true }).click();
  await page.waitForURL(new URL('docs/quickstart/', root).href);
  assert.match(await page.locator('.sl-markdown-content').innerText(), /def update_parameter/);
  async function assertDocsLocation(route, title, sidebarLabel = title) {
    await page.waitForURL(new URL(`docs/${route}`, root).href);
    assert.equal(page.url(), new URL(`docs/${route}`, root).href);
    assert.ok(await page.getByRole('heading', { level: 1, name: title, exact: true }).isVisible());
    assert.ok((await page.title()).includes(title));
    const activeLink = sidebar.locator('a[aria-current="page"]');
    assert.equal(await activeLink.count(), 1);
    assert.equal((await activeLink.innerText()).trim(), sidebarLabel);
  }
  await page.goBack();
  await assertDocsLocation('installation/', '安装 PivotQ', '安装');
  await page.goForward();
  await assertDocsLocation('quickstart/', '快速上手');
  await page.getByRole('link', { name: '通过 Provider 接入 QPU', exact: true }).click();
  await assertDocsLocation('quantum-backends/#接入-qpu-后端', '量子后端');
  assert.ok(await page.locator('[id="接入-qpu-后端"]').isVisible());
  await page.goBack();
  await assertDocsLocation('quickstart/', '快速上手');
  await page.goForward();
  await assertDocsLocation('quantum-backends/#接入-qpu-后端', '量子后端');
  assert.ok(await page.locator('[id="接入-qpu-后端"]').isVisible());
  await page.goBack();
  await assertDocsLocation('quickstart/', '快速上手');
  checks.push('SDK document and deep-link back/forward: URL, page title, h1 and active sidebar stay in sync');
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  const copy = page.locator('.expressive-code .copy button').first();
  await copy.click();
  assert.match(await page.evaluate(() => navigator.clipboard.readText()), /python packages\/framework\/examples\/hybrid_program.py/);
  await page.locator('[data-open-modal]').click();
  const searchInput = page.locator('.pagefind-ui__search-input');
  await searchInput.fill('quantum_backend');
  await page.locator('.pagefind-ui__result-link').first().waitFor();
  assert.ok(await page.locator('.pagefind-ui__result-link').count() > 0);
  const searchHref = await page.locator('.pagefind-ui__result-link').first().getAttribute('href');
  assert.ok(new URL(searchHref, root).pathname.startsWith(root.pathname + 'docs/'));
  await page.keyboard.press('Escape');
  await expandDocsGroup('API 参考');
  await sidebar.getByRole('link', { name: 'API 索引', exact: true }).click();
  await assertDocsLocation('api/', 'API 参考', 'API 索引');
  await sidebar.getByRole('link', { name: '运行时与结果引用', exact: true }).click();
  await page.waitForURL(new URL('docs/api/runtime/', root).href);
  assert.deepEqual(await page.locator('.docs-breadcrumbs > span:not([aria-current])').allTextContents(), ['使用文档', 'API 参考']);
  assert.equal(await sidebar.locator('a[aria-current="page"]').innerText(), '运行时与结果引用');
  assert.ok(await page.locator('.pagination-links').isVisible());
  // A direct URL must expand its category even when the reader previously collapsed it.
  const apiSummary = sidebar.locator('summary').filter({ hasText: /^API 参考$/ });
  await apiSummary.focus();
  await page.keyboard.press('Enter');
  assert.equal(await apiSummary.evaluate(node => node.parentElement.open), false);
  await page.goto(new URL('docs/api/quantum/#quantumresult', root).href, { waitUntil: 'networkidle' });
  assert.ok(await sidebar.getByRole('link', { name: '量子后端与结果', exact: true }).isVisible());
  assert.equal(await sidebar.locator('a[aria-current="page"]').innerText(), '量子后端与结果');
  assert.equal(await page.locator('#quantumresult').count(), 1);
  await page.goBack();
  await page.waitForURL(new URL('docs/api/runtime/', root).href);
  await page.goForward();
  await page.waitForURL(new URL('docs/api/quantum/#quantumresult', root).href);
  await page.goto(new URL('docs/api/', root).href, { waitUntil: 'networkidle' });
  for (const id of ['runtime', 'submit', 'get', 'release', 'close', 'waitstatus-与-report',
    'cpu-组件与-actor', 'workflow', 'quantum_backend', 'submit-1', '第三方-provider',
    'quantumresult', '集群作业', '性能模型与预测', '生命周期与错误']) {
    assert.equal(await page.locator(`[id="${id}"]`).count(), 1, `Legacy API anchor: ${id}`);
  }
  checks.push('Nested tutorial/API groups, keyboard folding, active breadcrumbs, API deep links, back/forward and legacy API anchors');
  await page.goto(new URL('docs/providers/', root).href, { waitUntil: 'networkidle' });
  assert.match(await page.locator('.sl-markdown-content').innerText(), /class CustomStatevectorProvider/);
  assert.match(await page.locator('.sl-markdown-content').innerText(), /register_quantum_backend/);
  await page.goto(new URL('docs/workflows/', root).href, { waitUntil: 'networkidle' });
  assert.match(await page.locator('.sl-markdown-content').innerText(), /def make_workflow/);
  await page.goto(new URL('docs/performance/', root).href, { waitUntil: 'networkidle' });
  assert.match(await page.locator('.sl-markdown-content').innerText(), /predictor.compare/);
  checks.push('Public SDK examples render from tested Python sources: workflow, provider, performance');
  const legacyRoutes = [
    ['guide-system-overview', 'architecture/'], ['system-overview', 'architecture/'],
    ['guide-使用指南', 'aimd/'], ['使用指南', 'aimd/'],
    ['guide-应用示例', 'examples/'], ['应用示例', 'examples/'],
    ...['1-选择应用并编译电路', '2-分配计算硬件并发起性能预测', '3-查看性能预测结果', '4-提交任务并查看运行状态', '5-查看水分子演化结果'].map(hash => [hash, `aimd/#${hash}`]),
  ];
  for (const [hash, route] of legacyRoutes) {
    await page.goto(new URL('docs/#' + encodeURIComponent(hash), root).href);
    await page.waitForURL(new URL('docs/' + route, root).href);
    if (route.includes('#')) assert.equal(await page.locator(`[id="${hash}"]`).count(), 1);
  }
  await page.goto(new URL('docs/aimd/', root).href, { waitUntil: 'networkidle' });
  assert.equal(await page.locator('.sl-markdown-content img').count(), 6);
  assert.equal(await page.locator('.docs-image-link').count(), 6);
  assert.match(await page.locator('.sl-markdown-content').innerText(), /不能作为.*Python SDK/);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(new URL('docs/installation/', root).href, { waitUntil: 'networkidle' });
  await page.locator('.sl-menu-button').click();
  await expandDocsGroup('混合编程');
  assert.ok(await sidebar.getByRole('link', { name: '量子后端', exact: true }).isVisible());
  await sidebar.getByRole('link', { name: '量子后端', exact: true }).click();
  await page.waitForURL(new URL('docs/quantum-backends/', root).href);
  assert.ok(await page.getByRole('heading', { level: 1, name: '量子后端' }).isVisible());
  assert.ok(await page.locator('html').evaluate(node => node.scrollWidth <= innerWidth));
  await page.screenshot({ path: `${artifactDir}/docs-quantum-390.png`, fullPage: true });
  await page.locator('.sl-menu-button').click();
  await expandDocsGroup('API 参考');
  await sidebar.getByRole('link', { name: '运行时与结果引用', exact: true }).click();
  await page.waitForURL(new URL('docs/api/runtime/', root).href);
  assert.ok(await page.locator('html').evaluate(node => node.scrollWidth <= innerWidth));
  checks.push('SDK docs: nested sidebar groups, API pages, right TOC, code copy, Pagefind search, legacy hashes, AIMD screenshots and mobile navigation');

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

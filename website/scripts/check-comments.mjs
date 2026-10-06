import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from '@playwright/test';

// Exercise the October 5 page feedback against a running site, including deployment bases.
// This checks navigation and diagram presentation; it does not execute or benchmark jobs.
const root = new URL(process.env.PORTAL_TEST_URL || 'http://127.0.0.1:4321/');
if (!root.pathname.endsWith('/')) root.pathname += '/';
const artifactDir = `artifacts/comments-${root.pathname === '/' ? 'root' : 'subpath'}`;
await mkdir(artifactDir, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.env.PORTAL_TEST_BROWSER ? { executablePath: process.env.PORTAL_TEST_BROWSER } : {}),
});
const context = await browser.newContext({ reducedMotion: 'reduce' });
const page = await context.newPage();
const errors = [];
const checks = [];
page.on('pageerror', error => errors.push(error.message));
const title = '任务编排和性能分析：PivotQ 可利用真机运行或性能仿真引擎生成详细的性能报告，发现瓶颈。';

try {
  for (const width of [320, 390, 768, 1000, 1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const route of ['', 'docs/', 'docs/examples/', 'examples/aimd/', 'examples/qram/', 'docs/aimd/']) {
      const response = await page.goto(new URL(route, root).href, { waitUntil: 'networkidle' });
      assert.equal(response.status(), 200, route);
      assert.ok(await page.locator('html').evaluate(node => node.scrollWidth <= innerWidth + 1), `${width}px ${route}: no page overflow`);
      assert.equal(await page.locator('main h1').count(), 1);
      const nav = page.locator('.flow-primary-nav');
      assert.equal(await nav.getByRole('link', { name: /^(系统|编程模型)$/, includeHidden: true }).count(), 0);
      assert.equal(await nav.getByRole('link', { name: '文档', exact: true, includeHidden: true }).count(), 1);
      const visibleCopy = await page.locator('body').innerText();
      assert.doesNotMatch(visibleCopy, /参考文档|水分子\s*AIMD/);
      const footer = page.getByRole('contentinfo');
      for (const name of ['文档', '水分子动力学模拟', '量子随机存储器']) {
        assert.ok(await footer.getByRole('link', { name, exact: true }).isVisible());
      }
      if (!route) {
        const heading = page.locator('#system-title');
        assert.equal(await heading.evaluate(node => {
          const copy = node.cloneNode(true);
          copy.querySelectorAll('.flow-section-number').forEach(number => number.remove());
          return copy.textContent.trim();
        }), title);
        assert.deepEqual(await page.locator('.flow-section-heading h2 .flow-section-number').allTextContents(), ['01', '02', '03'], 'Homepage headings retain their ordered section numbers');
        assert.deepEqual(await page.locator('.flow-section-heading h2 .flow-section-label').allTextContents(), ['编程模型：', '任务编排和性能分析：', '教程：']);
        assert.equal(await page.locator('.flow-section-kicker').count(), 0, 'The number and category are part of the heading without a separate kicker');
        for (const sectionTitle of await page.locator('.flow-section-heading h2').all()) {
          assert.ok(await sectionTitle.evaluate(node => node.scrollWidth <= node.clientWidth + 1), `${width}px section title wraps within its available width`);
        }
        const section = await page.locator('.flow-analysis-heading').boundingBox();
        const link = await page.getByRole('link', { name: '查看编排和分析文档', exact: true }).boundingBox();
        assert.ok(link.x >= section.x && link.x + link.width <= section.x + section.width + 1, 'Analysis link stays inside its section');
        const workflow = page.locator('[data-flow-workspace]');
        assert.equal(await workflow.getByRole('tablist').count(), 0);
        assert.equal(await workflow.locator('.flow-workspace-toolbar, .flow-workspace-title, .flow-workspace-led').count(), 0, 'The removed workflow title bar is absent');
        assert.equal(await workflow.getByRole('region', { name: '编程仿真工作流', exact: true }).getAttribute('id'), 'flow-workspace-panel', 'The diagram retains its accessible name');
        const descriptionTops = await workflow.locator('.flow-node-core > p').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().top));
        assert.ok(Math.max(...descriptionTops) - Math.min(...descriptionTops) < 1, 'Core node descriptions align');
        // Alternative execution paths converge on one report, centered between the branch rows.
        const sharedReport = workflow.locator('[data-flow-report="shared"]');
        assert.equal(await workflow.locator('[data-flow-report]').count(), 1, 'Both branches share one report');
        assert.equal(await sharedReport.count(), 1);
        assert.equal((await sharedReport.locator('.flow-node-name').innerText()).replace(/\s/g, ''), '真机/仿真性能报告');
        assert.deepEqual(await sharedReport.locator('.flow-report-fields li').allTextContents(), ['各任务运行时间', '运行节点', '运行指令顺序', '运行复杂度']);
        assert.equal(await workflow.locator('[data-flow-branch]').count(), 2);
        assert.equal(await workflow.locator('.flow-merge').count(), 1, 'The alternative paths have a merge connector');
        const sharedBounds = await sharedReport.boundingBox();
        assert.ok(sharedBounds);
        const branchCenters = [];
        for (const branch of ['hardware', 'simulation']) {
          const source = workflow.locator(`[data-flow-branch="${branch}"]`);
          assert.equal(await source.count(), 1);
          assert.ok(await source.evaluate(node => node.classList.contains('flow-node-emphasis')), `${branch} is highlighted`);
          const bounds = await source.boundingBox();
          assert.ok(bounds && sharedBounds.x > bounds.x + bounds.width, `${branch} leads to the shared report on the right`);
          branchCenters.push(bounds.y + bounds.height / 2);
        }
        assert.ok(branchCenters[0] < branchCenters[1], 'Hardware and simulation occupy separate branch rows');
        assert.ok(Math.abs(sharedBounds.y + sharedBounds.height / 2 - (branchCenters[0] + branchCenters[1]) / 2) < 1, 'Shared report is centered between both branches');
        assert.equal(await workflow.locator('.flow-node-emphasis').count(), 4, 'Composition, both branches and the shared report are highlighted');
        assert.equal(await workflow.locator('.flow-node-compose.flow-node-emphasis').count(), 1, 'Task composition is highlighted');
        assert.ok(await sharedReport.evaluate(node => node.classList.contains('flow-node-emphasis')), 'Shared report is highlighted');
        if (width <= 390) {
          await workflow.scrollIntoViewIfNeeded();
          const next = workflow.locator('[data-flow-next]');
          const previous = workflow.locator('[data-flow-prev]');
          assert.ok(await previous.isDisabled());
          for (let step = 0; step < 8 && !await next.isDisabled(); step += 1) {
            const before = await workflow.locator('#flow-workspace-panel').evaluate(node => node.scrollLeft);
            await next.click();
            // Scroll events update button states on the next frame, including reduced-motion scrolling.
            await page.waitForFunction(previous => {
              const panel = document.querySelector('#flow-workspace-panel');
              const next = document.querySelector('[data-flow-next]');
              return panel.scrollLeft > previous && next.disabled === (panel.scrollLeft >= panel.scrollWidth - panel.clientWidth - 1);
            }, before);
          }
          assert.ok(await next.isDisabled(), 'Navigation reaches the final column');
          const panel = await workflow.locator('#flow-workspace-panel').boundingBox();
          const report = await sharedReport.boundingBox();
          assert.ok(report && panel && report.x >= panel.x && report.x + report.width <= panel.x + panel.width + 1, 'Shared report fits the mobile panel');
          assert.ok(await previous.isEnabled());
          await previous.click();
          await page.waitForFunction(() => !document.querySelector('[data-flow-next]').disabled);
        }
        await page.locator('#workflow').screenshot({ path: `${artifactDir}/workflow-${width}.png` });
      }
      if ([390, 1440].includes(width) && ['docs/', 'examples/aimd/', 'docs/aimd/'].includes(route)) {
        await page.screenshot({ path: `${artifactDir}/${route.replaceAll('/', '-')}${width}.png` });
      }
      checks.push(`${width}px ${route || '/'} content, navigation and layout`);
    }
  }

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(root.href, { waitUntil: 'networkidle' });
  await page.getByRole('link', { name: '查看编排和分析文档', exact: true }).click();
  await page.waitForURL(new URL('docs/#使用文档', root).href);
  assert.equal(await page.locator('[id="使用文档"]').count(), 1);
  const usageTable = page.locator('[id="使用文档"]').locator('xpath=following::table[1]');
  for (const name of ['工作流', '执行报告', '性能预测']) {
    assert.ok(await usageTable.getByRole('link', { name, exact: true }).isVisible(), `Usage documentation includes ${name}`);
  }
  await page.goto(new URL('docs/', root).href, { waitUntil: 'networkidle' });
  assert.equal(await page.locator('a[href$="/docs/aimd/"], a[href="./aimd/"]').count(), 0, 'Docs overview has no tutorial promotion');
  const sidebar = page.locator('#starlight__sidebar');
  assert.equal(await sidebar.locator('details, summary, .caret').count(), 0, 'Documentation groups have no collapse controls or arrows');
  const sidebarLinkCount = await sidebar.locator('.top-level a').count();
  assert.ok(sidebarLinkCount > 0, 'Documentation sidebar contains navigation links');
  assert.equal(await sidebar.locator('.top-level a:visible').count(), sidebarLinkCount, 'All documentation groups are expanded');
  for (const label of await sidebar.locator('.docs-sidebar-group-label').all()) {
    await label.click();
    assert.equal(await sidebar.locator('.top-level a:visible').count(), sidebarLinkCount, 'Clicking a group title cannot hide its links');
  }
  const examples = sidebar.locator('.top-level > li > .docs-sidebar-group').filter({ has: page.locator('.docs-sidebar-group-label > .large').filter({ hasText: /^应用教程$/ }) });
  assert.deepEqual((await examples.locator('a').allTextContents()).map(text => text.trim()), ['介绍', '水分子动力学模拟', '量子随机存储器']);
  await examples.getByRole('link', { name: '水分子动力学模拟', exact: true }).click();
  await page.waitForURL(new URL('examples/aimd/', root).href);
  await page.getByRole('link', { name: '水分子动力学模拟工作台教程', exact: true }).click();
  await page.waitForURL(new URL('docs/aimd/', root).href);
  assert.equal(await page.locator('.flow-guide-content img').count(), 6);
  for (const screenshot of await page.locator('.flow-guide-content img').all()) {
    await screenshot.scrollIntoViewIfNeeded();
    await screenshot.evaluate(image => image.decode());
  }
  checks.push('Analysis deep link, example navigation and preserved six-image tutorial');
  assert.deepEqual(errors, [], 'Browser errors');
  await writeFile(`${artifactDir}/report.json`, JSON.stringify({ root: root.href, checks, errors }, null, 2));
  console.log(`PASS: ${checks.length} feedback checks; screenshots and report: ${artifactDir}/`);
} finally {
  await browser.close();
}

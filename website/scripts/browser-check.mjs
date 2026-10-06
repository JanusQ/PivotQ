import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';
import sharp from 'sharp';

const root = new URL(process.env.PORTAL_TEST_URL || 'http://127.0.0.1:4321/');
if (!root.pathname.endsWith('/')) root.pathname += '/';
const docsRoutes = [
  '', 'architecture/', 'installation/', 'quickstart/', 'hybrid-programs/',
  'classical-tasks/', 'gpu-computing/', 'components-actors/', 'quantum-backends/',
  'workflows/', 'observability/', 'jobs/', 'hardware-profiles/', 'performance/',
  'providers/', 'troubleshooting/', 'examples/', 'aimd/', 'api/',
  ...['runtime', 'components', 'workflows', 'quantum', 'providers', 'jobs',
    'observability', 'performance', 'errors'].map(name => `api/${name}/`),
].map(route => `docs/${route}`);
const pages = ['', 'examples/aimd/', 'examples/qram/', ...docsRoutes];
const screenshotRoutes = new Set([
  '', 'examples/aimd/', 'examples/qram/', 'docs/', 'docs/aimd/',
  'docs/installation/', 'docs/quickstart/', 'docs/gpu-computing/', 'docs/api/runtime/',
]);
const artifactDir = `artifacts/${root.pathname === '/' ? 'root' : 'subpath'}`;
await mkdir(artifactDir, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  args: ['--no-sandbox'],
  ...(process.env.PORTAL_TEST_BROWSER ? { executablePath: process.env.PORTAL_TEST_BROWSER } : {}),
});
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
  for (const [width, height] of [[1024, 768], [1336, 824], [1440, 900], [1920, 1080]]) {
    await page.setViewportSize({ width, height });
    await page.goto(root.href, { waitUntil: 'networkidle' });
    const edges = await page.evaluate(() => {
      const bounds = selector => {
        const { top, right, bottom, left } = document.querySelector(selector).getBoundingClientRect();
        return { top, right, bottom, left };
      };
      return {
        scene: bounds('.flow-architecture-scene'),
        primary: bounds('.flow-architecture-code'),
        gpu: bounds('[data-code-block="gpu"]'),
        submit: bounds('[data-code-block="submit"]'),
      };
    });
    const aligned = (first, second, edge) => Math.abs(first[edge] - second[edge]) < 1;
    assert.ok(aligned(edges.scene, edges.primary, 'top') && aligned(edges.scene, edges.primary, 'bottom'), `Upper architecture boxes align at ${width}px`);
    assert.ok(aligned(edges.gpu, edges.submit, 'top') && aligned(edges.gpu, edges.submit, 'bottom'), `Lower code boxes align at ${width}px`);
    assert.ok(aligned(edges.scene, edges.gpu, 'left') && aligned(edges.scene, edges.gpu, 'right'), `Left column edges align at ${width}px`);
    assert.ok(aligned(edges.primary, edges.submit, 'left') && aligned(edges.primary, edges.submit, 'right'), `Right column edges align at ${width}px`);
    if (width === 1440) {
      await page.evaluate(top => window.scrollTo(0, top + 80), edges.scene.top);
      const scrollTopGap = await page.evaluate(() => {
        const scene = document.querySelector('.flow-architecture-scene').getBoundingClientRect();
        const primary = document.querySelector('.flow-architecture-code').getBoundingClientRect();
        return Math.abs(scene.top - primary.top);
      });
      assert.ok(scrollTopGap < 1, `Architecture stays aligned while scrolling (${scrollTopGap}px)`);
    }
  }
  checks.push('Architecture columns and rows remain aligned on desktop and during scroll');

  const lazyPage = await context.newPage();
  await lazyPage.setViewportSize({ width: 320, height: 640 });
  await lazyPage.goto(new URL('examples/aimd/', root).href, { waitUntil: 'networkidle' });
  const lazyCode = lazyPage.locator('[data-source]');
  assert.equal(await lazyCode.getAttribute('data-editor-ready'), null, 'AIMD editor waits until its code is visible');
  assert.ok(await lazyCode.locator('[data-code-fallback]').isVisible(), 'Static code is readable before the editor loads');
  await lazyCode.scrollIntoViewIfNeeded();
  await lazyPage.waitForFunction(() => document.querySelector('[data-source]')?.getAttribute('data-editor-ready') === 'true');
  await lazyPage.close();
  checks.push('AIMD static code precedes the on-demand editor');

  const headerGeometry = async () => {
    await page.evaluate(() => document.fonts.ready);
    return page.locator('.flow-brand, .flow-primary-nav a, .flow-github, .flow-mobile-menu summary').evaluateAll(nodes =>
      nodes.filter(node => node.getBoundingClientRect().width > 0).map(node => {
        const { x, y, width, height } = node.getBoundingClientRect();
        return { label: node.textContent.trim(), x, y, width, height };
      }));
  };
  const assertSameHeader = (before, after, width) => {
    assert.deepEqual(after.map(item => item.label), before.map(item => item.label), `Same header controls at ${width}px`);
    before.forEach((item, index) => {
      for (const key of ['x', 'y', 'width', 'height']) {
        assert.ok(Math.abs(item[key] - after[index][key]) < .6,
          `Header ${item.label} ${key} remains stable at ${width}px: ${item[key]} → ${after[index][key]}`);
      }
    });
  };
  for (const width of [320, 390, 768, 1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(root.href, { waitUntil: 'networkidle' });
    const before = await headerGeometry();
    if (width <= 760) await page.locator('.flow-mobile-menu summary').click();
    await page.locator('.flow-header-inner a:visible').filter({ hasText: /^文档$/ }).click();
    await page.waitForURL(new URL('docs/', root).href);
    await page.waitForLoadState('networkidle');
    assertSameHeader(before, await headerGeometry(), width);
    if (width <= 760) await page.locator('.flow-mobile-menu summary').click();
    await page.locator('.flow-header-inner a:visible').filter({ hasText: /^首页$/ }).click();
    await page.waitForURL(root.href);
    await page.waitForLoadState('networkidle');
    assertSameHeader(before, await headerGeometry(), width);
    checks.push(`${width}px home ↔ docs keeps logo, navigation and actions in place`);
  }

  // Cover each public route at mobile, tablet, and desktop sizes before interactions.
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const route of pages) {
      const response = await page.goto(new URL(route, root).href, { waitUntil: 'networkidle' });
      assert.equal(response?.status(), 200, `Page status: ${route || '/'}`);
      assert.equal(await page.locator('main h1').count(), 1, `One h1: ${route || '/'}`);
      assert.equal(await page.locator('html').getAttribute('lang'), 'zh-CN');
      assert.ok(await page.locator('main h1').isVisible());
      const footer = page.getByRole('contentinfo');
      for (const name of ['文档', '水分子动力学模拟', '量子随机存储器']) {
        assert.ok(await footer.getByRole('link', { name, exact: true }).isVisible(), `Footer ${name}: ${route || '/'}`);
      }
      const universityLogo = footer.locator('img[alt="浙江大学"]');
      assert.equal(await universityLogo.count(), 1, `Footer university logo: ${route || '/'}`);
      assert.equal(await universityLogo.locator('xpath=..').getAttribute('href'), 'https://www.zju.edu.cn/');
      const dimensions = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: innerWidth }));
      assert.ok(dimensions.content <= dimensions.viewport + 1, `Overflow at ${width}px: ${route || '/'} (${dimensions.content})`);
      for (const href of await page.locator('a[href]').evaluateAll(nodes => nodes.map(node => node.href))) {
        const url = new URL(href);
        if (url.origin !== root.origin) continue;
        assert.ok(url.pathname.startsWith(root.pathname), `Link escapes deployment base: ${url.href}`);
        assert.ok(!url.pathname.includes('undefined'), `Invalid link: ${url.href}`);
        url.hash = '';
        links.add(url.href);
      }
      if ((width === 320 || width === 390 || width === 1440) && screenshotRoutes.has(route)) {
        if (!route) {
          const applicationPreview = page.locator('.flow-application-media-aimd img');
          await applicationPreview.scrollIntoViewIfNeeded();
          await applicationPreview.evaluate(image => image.decode());
          assert.ok(await applicationPreview.evaluate(image => image.naturalWidth > 0), 'AIMD application preview loads');
          await page.evaluate(() => window.scrollTo(0, 0));
          await page.waitForFunction(() => window.scrollY === 0);
        }
        const name = route ? route.replaceAll('/', '-').replace(/-$/, '') : 'home';
        await page.screenshot({ path: `${artifactDir}/${name}-${width}.png`, fullPage: true });
      }
      if (!route && width <= 768) {
        await page.waitForFunction(() => document.querySelector('[data-hardware-canvas]')?.getAttribute('data-scene-ready') === 'true');
        const mobileCanvas = page.locator('[data-hardware-canvas]');
        await mobileCanvas.scrollIntoViewIfNeeded();
        const frame = await mobileCanvas.boundingBox();
        assert.ok(frame);
        await page.mouse.move(frame.x + frame.width * .5, frame.y + frame.height * .5);
        await page.mouse.down();
        await page.mouse.move(frame.x + frame.width * .9, frame.y + frame.height * .5, { steps: 12 });
        await page.mouse.up();
        const collisions = await page.evaluate(() => {
          const labels = [...document.querySelectorAll('.flow-scene-label:not([hidden])')].map(node => node.getBoundingClientRect());
          const intersects = (a, b) => Math.min(a.right, b.right) > Math.max(a.left, b.left) && Math.min(a.bottom, b.bottom) > Math.max(a.top, b.top);
          return labels.flatMap((label, index) => labels.slice(index + 1).filter(other => intersects(label, other)).map(() => index));
        });
        assert.deepEqual(collisions, [], `Rotated hardware labels do not overlap at ${width}px`);
        const smallestLabelFont = await page.locator('.flow-scene-label small:visible').evaluateAll(nodes => Math.min(...nodes.map(node => parseFloat(getComputedStyle(node).fontSize))));
        assert.ok(smallestLabelFont >= 12, `Hardware label descriptions remain readable at ${width}px`);
        const codeOverflow = await page.locator('[data-code-block] pre').evaluateAll(nodes => nodes.filter(node => node.scrollWidth > node.clientWidth + 1).length);
        assert.equal(codeOverflow, 0, `All four code blocks fit at ${width}px`);
        checks.push(`${width}px hardware labels and code fit after rotation`);
      }
      checks.push(`${width}px ${route || '/'}: page, footer, links and width`);
    }
  }
  for (const href of links) {
    const response = await context.request.get(href);
    assert.equal(response.status(), 200, `Internal link: ${href}`);
  }

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(root.href, { waitUntil: 'networkidle' });
  const hero = page.locator('.flow-hero');
  assert.equal(await page.locator('main').getByRole('heading', { level: 1 }).innerText(), 'PivotQ');
  const photo = hero.locator('img.flow-hero-photo');
  assert.ok(await photo.evaluate(node => node.complete && node.naturalWidth > 0), 'User-provided hero photograph loads');
  assert.equal((await hero.locator('.flow-hero-title').innerText()).replace(/\s+/g, ' ').trim(), '统一描述 QPU、CPU、GPU 的计算任务，由 PivotQ 自动调度并执行。');
  assert.equal((await hero.locator('.flow-hero-description').innerText()).trim(), 'PivotQ 帮助编程者构建和管理跨 CPU、GPU 与 QPU 的量子经典混合计算任务。');
  assert.deepEqual(await page.locator('.flow-section-heading h2 .flow-section-label').allTextContents(), ['编程模型：', '任务编排和性能分析：', '教程：'], 'Homepage headings combine each category with its title');
  assert.deepEqual(await page.locator('.flow-section-heading h2 .flow-section-number').allTextContents(), ['01', '02', '03'], 'Homepage headings retain their ordered section numbers');
  const exampleCards = page.locator('.flow-home-applications .flow-application');
  assert.equal(await exampleCards.count(), 2, 'Homepage presents both tutorials');
  for (const [index, route] of ['examples/aimd/', 'examples/qram/'].entries()) {
    const card = exampleCards.nth(index);
    assert.equal(await card.getAttribute('href'), new URL(route, root).pathname);
    assert.match(await card.locator('.flow-application-link').innerText(), /查看教程/);
  }
  const architecture = page.locator('[data-hardware-architecture]');
  const canvas = architecture.locator('canvas[data-hardware-canvas]');
  await canvas.waitFor();
  await page.waitForFunction(() => document.querySelector('canvas[data-hardware-canvas]')?.getAttribute('data-scene-ready') === 'true');
  assert.ok(await canvas.evaluate(node => node.width > 0 && node.height > 0), 'Hardware scene has a drawing buffer');
  const preview = await sharp(await canvas.screenshot()).resize({ width: 48 }).raw().toBuffer();
  const colors = new Set();
  for (let index = 0; index < preview.length; index += 3) colors.add(`${preview[index]},${preview[index + 1]},${preview[index + 2]}`);
  assert.ok(colors.size > 50, `Hardware scene is visibly rendered (${colors.size} colors)`);
  assert.ok(await page.getByRole('navigation', { name: '主导航' }).isVisible());
  assert.equal(await architecture.locator('[data-code-block]').count(), 4, 'CPU, QPU, GPU and submission each have a code block');
  const hardwareCode = Object.fromEntries(await architecture.locator('[data-code-block]').evaluateAll(nodes =>
    nodes.map(node => [node.getAttribute('data-code-block'), node.querySelector('code')?.textContent ?? ''])));
  assert.match(hardwareCode.cpu, /geometry_A[\s\S]*predict_geometry_energy_and_force[\s\S]*forces_eV_per_A[\s\S]*VelocityVerlet[\s\S]*dynamics\.run\(steps\)/, 'CPU code prepares geometry, computes forces and advances the trajectory');
  assert.match(hardwareCode.qpu, /FusionQPUCircuitFeatureExtractor[\s\S]*QPUCircuitService[\s\S]*extract_features\([\s\S]*quantum_request[\s\S]*features/, 'QPU code extracts circuit features');
  assert.match(hardwareCode.gpu, /ClassicalPredictRequest\([\s\S]*features=features[\s\S]*classical_api\.predict\([\s\S]*energies_eV/, 'GPU code predicts energy from quantum features');
  assert.match(hardwareCode.submit, /build_job_spec\([\s\S]*quantum_target[\s\S]*RayJobClient\(address\)\.submit\(spec\)/, 'Final block submits the AIMD job spec');
  const cameraDistance = await canvas.getAttribute('data-camera-distance');
  for (const kind of ['cpu', 'qpu', 'gpu']) {
    const label = architecture.locator(`.flow-scene-label[data-hardware="${kind}"]`);
    const block = architecture.locator(`[data-code-block="${kind}"]`);
    assert.ok(await label.isVisible(), `${kind} label is visible on the 3D scene`);
    assert.ok(await block.isVisible(), `${kind} code block is visible`);
    assert.equal(await label.evaluate(node => getComputedStyle(node).color), await block.locator('[data-code-title]').evaluate(node => getComputedStyle(node).color), `${kind} colors link model and code`);
    const dataHighlight = architecture.locator(`.flow-code-data-${kind}`).first();
    assert.equal(await label.evaluate(node => getComputedStyle(node).color), await dataHighlight.evaluate(node => getComputedStyle(node).color), `${kind} color identifies shared data in the code`);
    await label.click();
    assert.equal(await architecture.getAttribute('data-active-hardware'), kind, `${kind} label selects its code`);
    assert.equal(await canvas.getAttribute('data-camera-distance'), cameraDistance, 'Label focus keeps camera distance');
  }
  await canvas.scrollIntoViewIfNeeded();
  const frame = await canvas.boundingBox();
  assert.ok(frame, 'Hardware scene is in view');
  const startRotation = await canvas.getAttribute('data-scene-rotation');
  const startDistance = await canvas.getAttribute('data-camera-distance');
  await page.mouse.move(frame.x + frame.width * .5, frame.y + frame.height * .5);
  await page.mouse.down();
  await page.mouse.move(frame.x + frame.width * .68, frame.y + frame.height * .6, { steps: 8 });
  await page.mouse.up();
  assert.notEqual(await canvas.getAttribute('data-scene-rotation'), startRotation, 'Dragging rotates the hardware scene');
  await page.mouse.wheel(0, 700);
  await canvas.press('+');
  await canvas.press('-');
  assert.equal(await canvas.getAttribute('data-camera-distance'), startDistance, 'Wheel and keyboard cannot zoom the hardware scene');
  await canvas.press('Home');
  await page.waitForFunction(() => document.querySelector('[data-hardware-canvas]')?.dataset.focus === 'qpu');
  checks.push('Hero photograph, 3D scene pixels, labels, four code blocks, rotation and fixed zoom');

  const touchContext = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    reducedMotion: 'reduce',
  });
  const touchPage = await touchContext.newPage();
  await touchPage.goto(root.href, { waitUntil: 'networkidle' });
  await touchPage.waitForFunction(() => document.querySelector('[data-hardware-canvas]')?.getAttribute('data-scene-ready') === 'true');
  const touchCanvas = touchPage.locator('[data-hardware-canvas]');
  const touchClient = await touchContext.newCDPSession(touchPage);
  const swipe = async (x, y, dx, dy) => {
    await touchClient.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
    for (let step = 1; step <= 10; step += 1) {
      await touchClient.send('Input.dispatchTouchEvent', {
        type: 'touchMove', touchPoints: [{ x: x + dx * step / 10, y: y + dy * step / 10 }],
      });
      await touchPage.waitForTimeout(20);
    }
    await touchClient.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  };
  await touchCanvas.scrollIntoViewIfNeeded();
  const touchFrame = await touchCanvas.boundingBox();
  assert.ok(touchFrame);
  const beforeTouchScroll = await touchPage.evaluate(() => scrollY);
  await swipe(touchFrame.x + touchFrame.width / 2, touchFrame.y + touchFrame.height * .76, 0, -120);
  await touchPage.waitForTimeout(350);
  assert.ok(await touchPage.evaluate(() => scrollY) > beforeTouchScroll + 20, 'Vertical swipe over mobile 3D canvas scrolls the page');
  await touchCanvas.scrollIntoViewIfNeeded();
  const rotateFrame = await touchCanvas.boundingBox();
  assert.ok(rotateFrame);
  const beforeTouchRotation = await touchCanvas.getAttribute('data-scene-rotation');
  await swipe(rotateFrame.x + rotateFrame.width * .35, rotateFrame.y + rotateFrame.height * .65, 90, 0);
  await touchPage.waitForFunction(previous => document.querySelector('[data-hardware-canvas]')?.getAttribute('data-scene-rotation') !== previous, beforeTouchRotation);
  const mobileCodeFont = await touchPage.locator('[data-code-block] pre').first().evaluate(node => parseFloat(getComputedStyle(node).fontSize));
  assert.ok(mobileCodeFont >= 12, `Mobile code remains legible (${mobileCodeFont}px)`);
  await touchContext.close();
  checks.push('Mobile vertical swipe scrolls through the 3D scene, horizontal swipe rotates, code is readable');

  const fallbackContext = await browser.newContext({ reducedMotion: 'reduce' });
  await fallbackContext.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (type, ...args) {
      if (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl') return null;
      return original.call(this, type, ...args);
    };
  });
  const fallbackPage = await fallbackContext.newPage();
  await fallbackPage.goto(root.href, { waitUntil: 'networkidle' });
  await fallbackPage.waitForFunction(() => document.querySelector('[data-hardware-architecture]')?.classList.contains('flow-architecture-failed'));
  const fallbackArchitecture = fallbackPage.locator('[data-hardware-architecture]');
  assert.ok(await fallbackArchitecture.locator('.flow-architecture-poster').isVisible(), 'Static architecture image remains without WebGL');
  assert.equal(await fallbackArchitecture.locator('.flow-scene-label:visible').count(), 3, 'Hardware labels remain without WebGL');
  assert.equal(await fallbackArchitecture.locator('[data-code-block]').count(), 4, 'Code examples remain without WebGL');
  await fallbackContext.close();
  checks.push('Static architecture fallback without WebGL');

  const workflow = page.locator('[data-flow-workspace]');
  const panel = workflow.locator('#flow-workspace-panel');
  assert.equal(await workflow.getByRole('tablist').count(), 0, 'The removed stage switch is absent');
  assert.equal(await workflow.locator('.flow-workspace-toolbar, .flow-workspace-title, .flow-workspace-led').count(), 0, 'The removed workflow title bar is absent');
  assert.equal(await workflow.getByRole('region', { name: '编程仿真工作流', exact: true }).getAttribute('id'), 'flow-workspace-panel', 'The diagram retains its accessible name');
  assert.match(await panel.innerText(), /量子-经典\s*混合程序[\s\S]*任务编排/);
  assert.deepEqual(await workflow.locator('.flow-resource-tags span').allTextContents(), ['CPU', 'GPU', 'QPU']);
  // Both alternatives converge on one report, without implying either execution path precedes the other.
  const sharedReport = panel.locator('[data-flow-report="shared"]');
  assert.equal(await panel.locator('[data-flow-report]').count(), 1, 'Both branches share one report');
  assert.equal(await sharedReport.count(), 1);
  assert.equal((await sharedReport.locator('.flow-node-name').innerText()).replace(/\s/g, ''), '真机/仿真性能报告');
  assert.deepEqual(await sharedReport.locator('.flow-report-fields li').allTextContents(), ['各任务运行时间', '运行节点', '运行指令顺序', '运行复杂度']);
  assert.equal(await panel.locator('[data-flow-branch]').count(), 2);
  assert.equal(await panel.locator('.flow-merge').count(), 1, 'The alternative paths have a merge connector');
  const sharedBounds = await sharedReport.boundingBox();
  assert.ok(sharedBounds);
  const branchCenters = [];
  for (const branch of ['hardware', 'simulation']) {
    const source = panel.locator(`[data-flow-branch="${branch}"]`);
    assert.equal(await source.count(), 1);
    assert.ok(await source.evaluate(node => node.classList.contains('flow-node-emphasis')), `${branch} is highlighted`);
    const bounds = await source.boundingBox();
    assert.ok(bounds && sharedBounds.x > bounds.x + bounds.width, `${branch} leads to the shared report on the right`);
    branchCenters.push(bounds.y + bounds.height / 2);
  }
  assert.ok(branchCenters[0] < branchCenters[1], 'Hardware and simulation occupy separate branch rows');
  assert.ok(Math.abs(sharedBounds.y + sharedBounds.height / 2 - (branchCenters[0] + branchCenters[1]) / 2) < 1, 'Shared report is centered between both branches');
  assert.equal(await panel.locator('.flow-node-emphasis').count(), 4, 'Composition, both branches and the shared report are highlighted');
  assert.equal(await panel.locator('.flow-node-compose.flow-node-emphasis').count(), 1, 'Task composition is highlighted');
  assert.ok(await sharedReport.evaluate(node => node.classList.contains('flow-node-emphasis')), 'Shared report is highlighted');
  assert.deepEqual(await page.locator('.flow-primary-nav a').allTextContents(), ['首页', '教程', '文档']);
  const analysisLink = page.getByRole('link', { name: '查看编排和分析文档' });
  await analysisLink.click();
  await page.waitForURL(new URL('docs/#使用文档', root).href);
  assert.equal(await page.locator('[id="使用文档"]').count(), 1);
  const usageTable = page.locator('[id="使用文档"]').locator('xpath=following::table[1]');
  for (const name of ['工作流', '执行报告', '性能预测']) {
    assert.ok(await usageTable.getByRole('link', { name, exact: true }).isVisible(), `Usage documentation includes ${name}`);
  }
  checks.push('Two workflow branches share a centered report, four highlighted nodes, report fields and analysis documentation link');

  await page.goto(new URL('examples/aimd/', root).href, { waitUntil: 'networkidle' });
  assert.ok(await page.getByRole('heading', { level: 1, name: '水分子动力学模拟' }).isVisible());
  const notebook = page.locator('.aimd-notebook');
  assert.equal(await notebook.locator('.aimd-notebook-chapter').count(), 4, 'AIMD notebook has four ordered chapters');
  assert.equal(await notebook.locator('#circuit').evaluate(node => node.classList.contains('aimd-notebook-chapter')), true, 'Circuit anchor opens the full chapter');
  assert.match(await notebook.locator('#question').innerText(), /能量和力[\s\S]*量子电路[\s\S]*经典模型/);
  const modelEquations = notebook.locator('.aimd-model-equations');
  assert.ok(await modelEquations.getByRole('heading', { name: '比较相邻构型的能量，求出原子受力' }).isVisible());
  const fractionsRender = await modelEquations.locator('mfrac').evaluateAll(fractions =>
    fractions.length > 0 && fractions.every(fraction => {
      const [numerator, denominator] = [...fraction.children].map(child => child.getBoundingClientRect());
      return fraction.namespaceURI === 'http://www.w3.org/1998/Math/MathML'
        && numerator.width > 0 && denominator.width > 0 && numerator.bottom <= denominator.top;
    }));
  assert.ok(fractionsRender, 'AIMD fractions render as mathematical notation with numerator above denominator');
  assert.ok(await modelEquations.locator('math').evaluateAll(nodes =>
    nodes.every(node => Boolean(node.getAttribute('aria-label')))), 'Every equation has a readable accessible description');
  await modelEquations.locator('summary').click();
  for (const source of await modelEquations.locator('.aimd-model-sources a').all()) {
    assert.match(await source.getAttribute('href'), /^https:\/\/github\.com\/JanusQ\/PivotQ\/blob\/main\/applications\/h2o-hybrid-aimd\//, 'Formula provenance points to the actual AIMD application');
  }
  await modelEquations.locator('summary').click();
  assert.equal(await notebook.locator('.aimd-notebook-gate-guide > div').count(), 4, 'AIMD explains the circuit gate families');
  assert.equal(await notebook.locator('.aimd-notebook-time-step li').count(), 4, 'AIMD connects coordinates through forces to the next step');
  await page.getByRole('region', { name: /^模型门结构图/ }).waitFor();
  await page.getByRole('region', { name: /^基础门分解图/ }).waitFor();
  const circuitNavigation = notebook.locator('[data-circuit-card="physical"] [data-circuit-navigation]');
  const circuitViewport = notebook.locator('[data-circuit-card="physical"] [data-circuit-viewport]');
  const expectCircuitNavigationAt = async target => {
    // Smooth scrolling and its scroll handler can update on different frames.
    // Wait for the destination and all navigation controls before browsing back.
    await expect.poll(() => circuitViewport.evaluate((viewport, target) => {
      const navigation = viewport.closest('[data-circuit-card]').querySelector('[data-circuit-navigation]');
      const maximum = viewport.scrollWidth - viewport.clientWidth;
      const left = viewport.scrollLeft;
      return {
        atDestination: Math.abs(left - target) <= 1,
        positionMatches: Number(navigation.querySelector('[data-circuit-position]').value)
          === (maximum ? Math.round(left / maximum * 100) : 0),
        previousMatches: navigation.querySelector('[data-circuit-previous]').disabled === (left <= 1),
        nextMatches: navigation.querySelector('[data-circuit-next]').disabled === (left >= maximum - 1),
      };
    }, target), { message: `Circuit position and controls follow browsing to ${target}px` }).toEqual({
      atDestination: true, positionMatches: true, previousMatches: true, nextMatches: true,
    });
  };
  assert.ok(await circuitNavigation.isVisible(), 'Long circuit has horizontal navigation');
  await expectCircuitNavigationAt(0);
  const circuitDestination = await circuitViewport.evaluate(viewport =>
    Math.min(viewport.scrollWidth - viewport.clientWidth, viewport.scrollLeft + viewport.clientWidth * .75));
  await circuitNavigation.locator('[data-circuit-next]').click();
  await expectCircuitNavigationAt(circuitDestination);
  assert.ok(Number(await circuitNavigation.locator('[data-circuit-position]').inputValue()) > 0, 'Circuit position follows browsing');
  await circuitNavigation.locator('[data-circuit-previous]').click();
  await expectCircuitNavigationAt(0);
  const results = page.locator('.analysis-results');
  assert.match(await results.locator('.aimd-notebook-prose').innerText(), /另一份归档的 CSV[\s\S]*并非代码 3 的运行结果/, 'Archived trajectory remains distinct from the displayed CPU calculation');
  const source = results.locator('.analysis-result-source');
  await source.locator('summary').click();
  assert.match(await source.innerText(), /教程(?:中的)?轨迹.*1001 帧/);
  assert.equal(await source.locator('a[download]').count(), 2, 'Imported trajectory CSV files are downloadable');
  const sourceLink = source.getByRole('link', { name: '查看数据来源说明' });
  assert.equal((await context.request.get(new URL(await sourceLink.getAttribute('href'), root).href)).status(), 200);
  await source.locator('summary').click();
  const replay = results.getByRole('button', { name: '重新播放' });
  const workbench = results.locator('[data-aimd-workbench]');
  const molecule = results.getByRole('img', { name: /^水分子三维动画/ });
  const chart = results.locator('[data-plot]').first();
  await molecule.scrollIntoViewIfNeeded();
  await page.waitForFunction(() => !document.querySelector('[data-restart]')?.disabled);
  assert.equal(await workbench.getAttribute('data-frame'), '0', 'Reduced motion preserves initial frame');
  const geometryAtStart = await results.locator('[data-value]').allTextContents();
  const chartBounds = await chart.boundingBox();
  assert.ok(chartBounds, 'Trajectory chart is visible');
  await page.mouse.click(chartBounds.x + chartBounds.width * .9, chartBounds.y + chartBounds.height * .5);
  const selectedFrame = Number(await workbench.getAttribute('data-frame'));
  assert.ok(selectedFrame > 800, 'A chart click can inspect later frames before playback');
  assert.equal(Number(await workbench.getAttribute('data-revealed-frame')), selectedFrame, 'Seeking reveals the selected trajectory segment');
  await chart.press('End');
  assert.equal(await workbench.getAttribute('data-frame'), '1000', 'End selects the final frame before playback');
  await chart.press('Home');
  assert.equal(await workbench.getAttribute('data-frame'), '0');
  assert.deepEqual(await results.locator('[data-value]').allTextContents(), geometryAtStart);
  await replay.click();
  await page.waitForFunction(() => Number(document.querySelector('[data-aimd-workbench]')?.getAttribute('data-frame')) > 10);
  await chart.press('End');
  const recordedFrame = Number(await workbench.getAttribute('data-frame'));
  assert.ok(recordedFrame > 10, 'Replay advances recorded trajectory');
  assert.equal(Number(await molecule.getAttribute('data-frame')), recordedFrame, '3D view follows selected frame');
  assert.ok((await results.locator('[data-time-cursor]').evaluateAll(nodes => nodes.map(node => Number(node.getAttribute('data-time-cursor'))))).every(frame => frame === recordedFrame), 'Curves follow selected frame');
  assert.notDeepEqual(await results.locator('[data-value]').allTextContents(), geometryAtStart, 'Geometry follows selected frame');
  await chart.press('Home');
  assert.equal(await workbench.getAttribute('data-frame'), '0');
  assert.deepEqual(await results.locator('[data-value]').allTextContents(), geometryAtStart);
  checks.push('AIMD notebook, circuit views, imported data disclosure and synchronized replay');

  const noJsContext = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 320, height: 844 } });
  const noJsPage = await noJsContext.newPage();
  await noJsPage.goto(new URL('examples/aimd/', root).href, { waitUntil: 'load' });
  const staticForceEquation = noJsPage.getByRole('region', { name: '中心有限差分求力公式，可横向滚动' });
  await staticForceEquation.scrollIntoViewIfNeeded();
  assert.ok(await staticForceEquation.locator('math').last().isVisible(), 'Math remains readable without JavaScript');
  await staticForceEquation.focus();
  // Math font metrics differ between local machines and the CI runner; the formula may already fit.
  const forceEquationOverflows = await staticForceEquation.evaluate(node => node.scrollWidth > node.clientWidth);
  if (forceEquationOverflows) {
    await staticForceEquation.press('ArrowRight');
    // Poll from Node: page timers are disabled in this no-JavaScript context.
    await expect.poll(() => staticForceEquation.evaluate(node => node.scrollLeft)).toBeGreaterThan(0);
  }
  assert.ok(await noJsPage.locator('html').evaluate(node => node.scrollWidth <= innerWidth), 'A long mobile formula scrolls within its panel');
  const staticCircuits = noJsPage.locator('.aimd-notebook-circuit-fallback');
  assert.equal(await staticCircuits.count(), 2, 'Two circuit fallbacks exist without JavaScript');
  assert.match(await staticCircuits.first().innerText(), /几何编码 Ry 门/);
  const staticImage = staticCircuits.locator('img');
  await staticImage.scrollIntoViewIfNeeded();
  assert.ok(await staticImage.evaluate(node => node.complete && node.naturalWidth > 0), 'Native circuit image loads without JavaScript');
  assert.equal(await noJsPage.getByText('正在加载模型门结构…').count(), 0, 'No permanent circuit loading state without JavaScript');
  await noJsPage.locator('.analysis-result-source summary').click();
  assert.equal(await noJsPage.locator('.analysis-result-source a[download]').count(), 2);
  assert.ok(await noJsPage.locator('.wb-nojs').isVisible(), 'No-JavaScript data links are visible');
  assert.equal(await noJsPage.locator('.wb-analysis-grid').isVisible(), false, 'Empty interactive charts are hidden without JavaScript');
  await noJsContext.close();
  checks.push('AIMD formulas, keyboard scrolling, static circuit and CSV access without JavaScript');

  await page.goto(new URL('examples/qram/', root).href, { waitUntil: 'networkidle' });
  const qramNotebook = page.locator('.qram-notebook');
  assert.ok(await qramNotebook.getByRole('heading', { level: 1, name: /如何通过地址 10 找到并读出数据/ }).isVisible());
  assert.ok(await qramNotebook.getByRole('heading', { level: 2, name: '普通内存和量子地址' }).isVisible());
  assert.equal(await qramNotebook.locator('.qram-notebook-section').count(), 5, 'QRAM notebook has five ordered steps');
  assert.match(await qramNotebook.locator('.qram-notebook-scope').innerText(), /没有可运行的量子随机存储器任务或真机读写数据/);
  assert.ok(await qramNotebook.locator('.qram-code-cell').first().isVisible());
  assert.match(await qramNotebook.locator('.qram-output-cell').first().innerText(), /右 → 左\s+存储单元 10/);
  assert.ok(await qramNotebook.getByRole('img', { name: /量子随机存储器概念示意/ }).isVisible());
  assert.equal(await qramNotebook.locator('.qram-notebook-figure text').first().textContent(), '|10⟩');
  assert.equal(await qramNotebook.locator('.qram-memory-table tbody tr').count(), 4, 'QRAM toy memory has four addresses');
  assert.match(await qramNotebook.locator('.qram-query-rule').innerText(), /b ⊕ mₐ/);
  assert.match(await qramNotebook.locator('.qram-superposition').innerText(), /\|01⟩\|0⟩ \+ \|10⟩\|1⟩/);
  await qramNotebook.getByRole('navigation', { name: '继续阅读' }).getByRole('link', { name: /水分子动力学模拟教程/ }).click();
  await page.waitForURL(new URL('examples/aimd/', root).href);
  checks.push('QRAM notebook steps, path output, concept scope and onward navigation');

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(new URL('docs/', root).href, { waitUntil: 'networkidle' });
  const sidebar = page.locator('#starlight__sidebar');
  assert.deepEqual(await sidebar.locator('.top-level > li > .docs-sidebar-group > .docs-sidebar-group-label > .large').allTextContents(), ['系统介绍', '使用文档', '应用教程']);
  assert.deepEqual(await sidebar.locator('.top-level > li > .docs-sidebar-group > ul > li > .docs-sidebar-group > .docs-sidebar-group-label > .large').allTextContents(), [
    '入门', '混合编程', '运行与管理', '性能建模与预测', '后端扩展', 'API 参考',
  ]);
  async function assertDocsGroupsVisible() {
    assert.equal(await sidebar.locator('details, summary, .caret').count(), 0, 'Documentation groups have no collapse controls or arrows');
    const links = sidebar.locator('.top-level a');
    assert.ok(await links.count() > 0, 'Documentation sidebar contains navigation links');
    assert.equal(await sidebar.locator('.top-level a:visible').count(), await links.count(), 'Every documentation group keeps all its links visible');
  }
  await assertDocsGroupsVisible();
  for (const label of await sidebar.locator('.docs-sidebar-group-label').all()) {
    await label.click();
    await assertDocsGroupsVisible();
  }
  assert.equal(await sidebar.locator('.docs-tutorial-link').count(), 0, 'Documentation sidebar has no tutorial promotion');
  assert.equal(await page.locator('main a[href$="/docs/aimd/"], main a[href="./aimd/"]').count(), 0, 'Docs overview does not promote the example tutorial');
  const exampleGroup = sidebar.locator('.top-level > li > .docs-sidebar-group').filter({ has: page.locator('.docs-sidebar-group-label > .large').filter({ hasText: /^应用教程$/ }) });
  assert.deepEqual((await exampleGroup.locator('a').allTextContents()).map(text => text.trim()), ['介绍', '水分子动力学模拟', '量子随机存储器']);
  for (const [name, route] of [['水分子动力学模拟', 'examples/aimd/'], ['量子随机存储器', 'examples/qram/']]) {
    assert.equal(await exampleGroup.getByRole('link', { name, exact: true }).evaluate(link => link.href), new URL(route, root).href);
  }
  assert.equal(await page.locator('main .flow-guide-tutorial').count(), 0, 'Docs overview does not embed the complete example tutorial');
  const installationLink = page.getByRole('link', { name: 'Docker 安装与启动说明', exact: true });
  assert.equal(await installationLink.evaluate(link => link.href), new URL('docs/installation/#使用-docker-安装', root).href);
  assert.ok(await page.locator('.right-sidebar').isVisible());
  async function assertDocsLocation(route, title, sidebarLabel = title) {
    await page.waitForURL(new URL(`docs/${route}`, root).href);
    assert.ok(await page.getByRole('heading', { level: 1, name: title, exact: true }).isVisible());
    assert.ok((await page.title()).includes(title));
    const activeLink = sidebar.locator('a[aria-current="page"]');
    assert.equal(await activeLink.count(), 1);
    assert.ok(await activeLink.isVisible(), 'The current documentation page remains visible in its group');
    assert.equal((await activeLink.innerText()).trim(), sidebarLabel);
    await assertDocsGroupsVisible();
  }
  await sidebar.getByRole('link', { name: 'PivotQ', exact: true }).click();
  await assertDocsLocation('architecture/', 'PivotQ');
  await sidebar.getByRole('link', { name: '安装', exact: true }).click();
  await assertDocsLocation('installation/', '安装 PivotQ', '安装');
  assert.match(await page.locator('.sl-markdown-content').innerText(), /docker pull janusq\/pivotq:latest[\s\S]*localhost:8787/);
  assert.ok(await page.locator('.pagination-links').isVisible());
  await sidebar.getByRole('link', { name: '快速上手', exact: true }).click();
  await assertDocsLocation('quickstart/', '快速上手');
  assert.match(await page.locator('.sl-markdown-content').innerText(), /def update_parameter/);
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
  await page.goBack();
  await assertDocsLocation('quickstart/', '快速上手');
  checks.push('Shared categorized docs navigation, independent tutorial, Docker instructions and SDK deep-link history');

  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.locator('.expressive-code .copy button').first().click();
  assert.match(await page.evaluate(() => navigator.clipboard.readText()), /python packages\/framework\/examples\/hybrid_program.py/);
  assert.equal(await page.locator('starlight-search, [data-open-modal], .pagefind-ui__search-input').count(), 0, 'Documentation search is removed');
  await page.keyboard.press('ControlOrMeta+k');
  assert.equal(await page.getByRole('dialog').count(), 0, 'The former search shortcut does not open a dialog');
  checks.push('SDK code copy works and documentation search is absent');

  await sidebar.getByRole('link', { name: 'API 索引', exact: true }).click();
  await assertDocsLocation('api/', 'API 参考', 'API 索引');
  await sidebar.getByRole('link', { name: '运行时与结果引用', exact: true }).click();
  await assertDocsLocation('api/runtime/', '运行时与结果引用');
  assert.deepEqual(await page.locator('.docs-breadcrumbs > span:not([aria-current])').allTextContents(), ['使用文档', 'API 参考']);
  assert.ok(await page.locator('.pagination-links').isVisible());
  const apiLabel = sidebar.locator('.docs-sidebar-group-label').filter({ hasText: /^API 参考$/ });
  await apiLabel.click();
  await assertDocsGroupsVisible();
  assert.equal((await sidebar.locator('a[aria-current="page"]').innerText()).trim(), '运行时与结果引用', 'Clicking the API group title preserves the current page');
  await page.goto(new URL('docs/api/quantum/#quantumresult', root).href, { waitUntil: 'networkidle' });
  await assertDocsGroupsVisible();
  assert.ok(await sidebar.getByRole('link', { name: '量子后端与结果', exact: true }).isVisible(), 'Direct API links remain visible in the permanently expanded category');
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
  checks.push('API index, permanently expanded categories, active breadcrumbs, direct API links and legacy API anchors');

  for (const [route, examples] of [
    ['providers/', [/class CustomStatevectorProvider/, /register_quantum_backend/]],
    ['workflows/', [/def make_workflow/]],
    ['performance/', [/predictor.compare/]],
    ['gpu-computing/', [/GPU/, /CPU/, /QPU/]],
  ]) {
    await page.goto(new URL(`docs/${route}`, root).href, { waitUntil: 'networkidle' });
    const content = await page.locator('.sl-markdown-content').innerText();
    for (const example of examples) assert.match(content, example, `SDK example: ${route}`);
  }
  checks.push('Public SDK workflow, provider, performance examples and CPU/GPU/QPU documentation');

  const legacyRoutes = [
    ['guide-system-overview', 'architecture/'], ['system-overview', 'architecture/'],
    ['guide-使用指南', 'aimd/'], ['使用指南', 'aimd/'],
    ['guide-应用示例', 'examples/'], ['应用示例', 'examples/'],
    ['guide-应用教程', 'examples/'], ['应用教程', 'examples/'],
    ['guide-启动工作台', '#启动工作台'],
    ...['1-选择应用并编译电路', '2-分配计算硬件并发起性能预测', '3-查看性能预测结果', '4-提交任务并查看运行状态', '5-查看水分子演化结果'].map(hash => [hash, `aimd/#${hash}`]),
  ];
  for (const [hash, route] of legacyRoutes) {
    await page.goto(new URL('docs/#' + encodeURIComponent(hash), root).href);
    await page.waitForURL(new URL('docs/' + route, root).href);
    if (route.includes('#')) assert.equal(await page.locator(`[id="${route.split('#')[1]}"]`).count(), 1);
  }
  await page.goto(new URL('examples/aimd/', root).href, { waitUntil: 'networkidle' });
  await page.getByRole('link', { name: '水分子动力学模拟工作台教程', exact: true }).click();
  await page.waitForURL(new URL('docs/aimd/', root).href);
  checks.push('Legacy docs URLs resolve and the example links to its separate tutorial');

  await page.goto(new URL('docs/aimd/', root).href, { waitUntil: 'networkidle' });
  const tutorial = page.locator('.flow-guide-tutorial');
  assert.ok(await tutorial.getByRole('heading', { level: 1, name: /^水分子动力学模拟\s*工作台教程$/ }).isVisible());
  assert.equal(await tutorial.locator('.flow-guide-content h2').count(), 5, 'AIMD tutorial includes five source sections');
  assert.equal(await tutorial.locator('.flow-guide-content img').count(), 6, 'AIMD tutorial includes six source screenshots');
  assert.equal(await tutorial.locator('.flow-guide-image-link').count(), 6, 'Each tutorial screenshot opens its full image');
  for (const screenshot of await tutorial.locator('.flow-guide-content img').all()) {
    await screenshot.scrollIntoViewIfNeeded();
    await screenshot.evaluate(image => image.decode());
    assert.ok(await screenshot.evaluate(image => image.naturalWidth > 0), 'Tutorial screenshot loads');
  }
  assert.match(await tutorial.locator('.flow-guide-content').innerText(), /不能直接作为.*Python SDK[\s\S]*qhai\.tasks/, 'Workbench syntax remains distinct from the public SDK');
  const tutorialAnchors = await tutorial.locator('.flow-guide-chapters a[href^="#"]').evaluateAll(nodes => nodes.map(node => node.getAttribute('href')));
  assert.equal(tutorialAnchors.length, 5, 'Tutorial navigation includes each section');
  assert.ok(await page.evaluate(anchors => anchors.every(anchor => document.getElementById(decodeURIComponent(anchor.slice(1)))), tutorialAnchors), 'Tutorial anchors resolve to headings');
  checks.push('AIMD tutorial, screenshots and section navigation');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(root.href, { waitUntil: 'networkidle' });
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement?.textContent?.trim()), '跳转到正文');
  const mobileWorkflow = page.locator('[data-flow-workspace]');
  const mobilePrevious = mobileWorkflow.locator('[data-flow-prev]');
  const mobileNext = mobileWorkflow.locator('[data-flow-next]');
  assert.ok(await mobileNext.isVisible(), 'Mobile workflow has visible node navigation');
  assert.ok(await mobilePrevious.isDisabled(), 'Workflow begins at its first node');
  await mobileNext.click();
  await page.waitForFunction(() => document.querySelector('#flow-workspace-panel')?.scrollLeft > 20);
  await page.waitForFunction(() => !(document.querySelector('[data-flow-prev]')?.disabled));
  assert.ok(await mobilePrevious.isEnabled(), 'Previous node becomes available after advancing');
  await mobilePrevious.click();
  await page.waitForFunction(() => (document.querySelector('#flow-workspace-panel')?.scrollLeft ?? 1) < 20);
  assert.equal(await mobileWorkflow.getByRole('tablist').count(), 0);
  const scrollOrigin = await page.evaluate(() => ({ x: scrollX, y: scrollY }));
  for (let step = 0; step < 8 && !await mobileNext.isDisabled(); step += 1) {
    const previousScroll = await mobileWorkflow.locator('#flow-workspace-panel').evaluate(node => node.scrollLeft);
    await mobileNext.click();
    await page.waitForFunction(previous => {
      const panel = document.querySelector('#flow-workspace-panel');
      const next = document.querySelector('[data-flow-next]');
      return panel.scrollLeft > previous && next.disabled === (panel.scrollLeft >= panel.scrollWidth - panel.clientWidth - 1);
    }, previousScroll);
  }
  assert.ok(await mobileNext.isDisabled(), 'Mobile arrows reach the final column');
  const reportBounds = await mobileWorkflow.locator('[data-flow-report="shared"]').boundingBox();
  const viewportBounds = await mobileWorkflow.locator('#flow-workspace-panel').boundingBox();
  assert.ok(reportBounds && viewportBounds && reportBounds.x >= viewportBounds.x && reportBounds.x + reportBounds.width <= viewportBounds.x + viewportBounds.width + 1, 'Mobile arrows reveal the complete shared performance report');
  assert.deepEqual(await page.evaluate(() => ({ x: scrollX, y: scrollY })), scrollOrigin, 'Diagram navigation keeps the page in place');
  assert.ok(await page.locator('html').evaluate(node => node.scrollWidth <= innerWidth), 'Workflow does not create page overflow');
  checks.push('Mobile workflow arrows reach both execution branches and the shared report');
  const menu = page.locator('.flow-mobile-menu');
  await menu.locator('summary').click();
  assert.ok(await menu.getByRole('link', { name: '文档' }).isVisible());
  await page.keyboard.press('Escape');
  assert.equal(await menu.getAttribute('open'), null);
  await menu.locator('summary').click();
  await menu.getByRole('link', { name: '教程', exact: true }).click();
  await page.waitForURL(new URL('#applications', root).href);
  assert.equal(await menu.getAttribute('open'), null);
  await page.locator('.flow-application').filter({ hasText: '水分子动力学模拟' }).click();
  await page.waitForURL(new URL('examples/aimd/', root).href);
  await replay.scrollIntoViewIfNeeded();
  await replay.click();
  await page.waitForFunction(() => Number(document.querySelector('[data-aimd-workbench]')?.getAttribute('data-frame')) > 5);
  assert.ok(await page.locator('html').evaluate(node => node.scrollWidth <= innerWidth));
  await page.getByRole('contentinfo').getByRole('link', { name: '文档' }).click();
  await page.waitForURL(new URL('docs/', root).href);
  await page.locator('.docs-sidebar-toggle').click();
  await assertDocsGroupsVisible();
  await sidebar.getByRole('link', { name: '量子后端', exact: true }).click();
  await page.waitForURL(new URL('docs/quantum-backends/', root).href);
  assert.ok(await page.getByRole('heading', { level: 1, name: '量子后端' }).isVisible());
  assert.ok(await page.locator('html').evaluate(node => node.scrollWidth <= innerWidth));
  await page.locator('.docs-sidebar-toggle').click();
  await assertDocsGroupsVisible();
  await sidebar.getByRole('link', { name: '运行时与结果引用', exact: true }).click();
  await page.waitForURL(new URL('docs/api/runtime/', root).href);
  assert.ok(await page.locator('html').evaluate(node => node.scrollWidth <= innerWidth));
  checks.push('Mobile menu, skip link, application replay and categorized SDK/API navigation');

  const missing = await page.goto(new URL('this-page-does-not-exist/', root).href);
  assert.equal(missing?.status(), 404);
  await page.getByRole('link', { name: '返回首页' }).click();
  await page.waitForURL(root.href);
  checks.push('404 return navigation');
  assert.deepEqual(errors, [], 'Browser JavaScript errors');
  assert.deepEqual([...external], [], 'Unexpected external resource requests');
  const report = { root: root.href, checks, internalLinksChecked: links.size, errors, externalRequests: [...external] };
  await writeFile(`${artifactDir}/report.json`, JSON.stringify(report, null, 2));
  console.log(`Passed ${checks.length} browser scenarios and ${links.size} internal links. Screenshots: ${artifactDir}/`);
} finally {
  await browser.close();
}

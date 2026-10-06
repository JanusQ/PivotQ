import assert from 'node:assert/strict';
import { readFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { siteSettings } from './site-settings.mjs';

const { site, base } = siteSettings({ release: true });
const output = path.resolve(process.env.PORTAL_RELEASE_DIR || 'dist');
const origin = new URL(site);
const expectedRoot = `${site}${base}`;
const htmlFiles = [];
const cssFiles = [];
const resourceFiles = new Set();
const contents = new Map();
const anchorChecks = new Set();
const docsRoutes = [
  '', 'architecture/', 'installation/', 'quickstart/', 'hybrid-programs/',
  'classical-tasks/', 'gpu-computing/', 'components-actors/', 'quantum-backends/',
  'workflows/', 'observability/', 'jobs/', 'hardware-profiles/', 'performance/',
  'providers/', 'troubleshooting/', 'examples/', 'aimd/', 'api/',
  ...['runtime', 'components', 'workflows', 'quantum', 'providers', 'jobs',
    'observability', 'performance', 'errors'].map(name => `api/${name}/`),
].map(route => `docs/${route}`);
const requiredRoutes = ['', 'examples/aimd/', 'examples/qram/', ...docsRoutes];
const decode = value => value.replace(/&(?:amp|quot|apos|lt|gt|#\d+|#x[\da-f]+);/gi, entity => {
  const named = { '&amp;': '&', '&quot;': '"', '&apos;': "'", '&lt;': '<', '&gt;': '>' };
  return named[entity.toLowerCase()] ?? String.fromCodePoint(parseInt(entity.slice(entity[2].toLowerCase() === 'x' ? 3 : 2, -1), entity[2].toLowerCase() === 'x' ? 16 : 10));
});

async function walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) await walk(file);
    else if (entry.name.endsWith('.html')) htmlFiles.push(file);
    else if (entry.name.endsWith('.css')) cssFiles.push(file);
  }
}

function attrs(tag) {
  return Object.fromEntries([...tag.matchAll(/([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)]
    .map(match => [match[1], decode(match[2] ?? match[3])]));
}

async function textFile(file) {
  if (!contents.has(file)) contents.set(file, await readFile(file, 'utf8'));
  return contents.get(file);
}

async function localTarget(url) {
  assert.ok(url.pathname.startsWith(base), `资源或页面链接逃逸部署路径：${url.href}`);
  const relative = decodeURIComponent(url.pathname.slice(base.length));
  let target = path.resolve(output, relative);
  assert.ok(target === output || target.startsWith(`${output}${path.sep}`), `非法资源路径：${url.href}`);
  const info = await stat(target).catch(() => null);
  assert.ok(info, `构建产物缺少：${url.href}`);
  if (info.isDirectory()) {
    target = path.join(target, 'index.html');
    assert.ok((await stat(target).catch(() => null))?.isFile(), `目录缺少页面：${url.href}`);
  }
  resourceFiles.add(target);
  return target;
}

async function checkReference(value, from, { checkAnchor = false } = {}) {
  if (!value || /^(data:|mailto:|tel:)/i.test(value)) return;
  const target = new URL(value, from);
  if (!['http:', 'https:'].includes(target.protocol)) return;
  assert.ok(!['localhost', '127.0.0.1', '0.0.0.0', '[::1]'].includes(target.hostname), `包含本机链接：${from.href} -> ${target.href}`);
  if (target.origin !== origin.origin) return;
  const file = await localTarget(target);
  if (checkAnchor && target.hash && file.endsWith('.html') && !anchorChecks.has(target.href)) {
    const id = decodeURIComponent(target.hash.slice(1));
    const ids = [...(await textFile(file)).matchAll(/\b(?:id|name)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)]
      .map(match => decode(match[1] ?? match[2]));
    assert.ok(ids.includes(id), `页面锚点不存在：${from.href} -> ${target.href}`);
    anchorChecks.add(target.href);
  }
}

async function checkCss(css, from) {
  for (const match of css.matchAll(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^\s)]*))\s*\)/g)) {
    // SVG filters may reference an ID in the current document.
    const value = match[1] ?? match[2] ?? match[3];
    if (!value.startsWith('#')) await checkReference(value, from);
  }
  for (const match of css.matchAll(/@import\s+["']([^"']+)["']/g)) await checkReference(match[1], from);
}

await walk(output);
for (const route of requiredRoutes) await localTarget(new URL(`${base}${route}`, origin));
assert.ok(htmlFiles.includes(path.join(output, '404.html')), '构建产物缺少 404 页面。');
const canonicalUrls = new Set();
for (const file of htmlFiles) {
  const relative = path.relative(output, file).split(path.sep).join('/');
  const html = await textFile(file);
  const route = relative === 'index.html' ? '' : relative.replace(/index\.html$/, '');
  const url = new URL(`${base}${route}`, origin);
  const tags = [...html.matchAll(/<([a-z][\w:-]*)\b[^>]*>/gi)].map(match => ({ name: match[1], attributes: attrs(match[0]) }));
  if (relative === '404.html') {
    assert.ok(tags.some(({ attributes }) => attributes.name === 'robots' && attributes.content?.includes('noindex')), '404 必须禁止索引。');
  } else {
    const canonical = tags.find(({ attributes }) => attributes.rel === 'canonical')?.attributes;
    assert.equal(canonical?.href, url.href, `canonical 不匹配：${relative}`);
    canonicalUrls.add(url.href);
  }
  for (const { name, attributes } of tags) {
    for (const key of ['src', 'href', 'poster']) {
      if (attributes[key]) await checkReference(attributes[key], url, { checkAnchor: name === 'a' && key === 'href' });
    }
    if (attributes.srcset && !attributes.srcset.startsWith('data:')) {
      for (const candidate of attributes.srcset.split(',')) await checkReference(candidate.trim().split(/\s+/)[0], url);
    }
    if (attributes.style) await checkCss(attributes.style, url);
    if (name === 'meta' && ['og:image', 'twitter:image'].includes(attributes.property || attributes.name)) {
      await checkReference(attributes.content, url);
    }
  }
  for (const match of html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/g)) await checkCss(match[1], url);
}
for (const file of cssFiles) {
  const relative = path.relative(output, file).split(path.sep).join('/');
  await checkCss(await textFile(file), new URL(`${base}${relative}`, origin));
}

const tutorialHtml = await textFile(path.join(output, 'docs/aimd/index.html'));
const tutorialContent = tutorialHtml.match(/<article\b[^>]*class="[^"]*flow-guide-content[^"]*"[^>]*>([\s\S]*?)<\/article>/)?.[1];
assert.ok(tutorialContent, 'AIMD 工作台教程必须保持独立页面。');
const tutorialImages = [...tutorialContent.matchAll(/<img\b[^>]*>/g)].map(match => attrs(match[0]));
assert.equal(tutorialImages.length, 6, 'AIMD 工作台教程必须保留六张原始截图。');
for (const screenshot of tutorialImages) {
  assert.ok(screenshot.alt?.trim(), '教程截图缺少文字说明。');
  await checkReference(screenshot.src, new URL(`${base}docs/aimd/`, origin));
}
const exampleHtml = await textFile(path.join(output, 'examples/aimd/index.html'));
assert.ok([...exampleHtml.matchAll(/<a\b[^>]*>/g)].some(match => {
  const href = attrs(match[0]).href;
  return href && new URL(href, new URL(`${base}examples/aimd/`, origin)).pathname === `${base}docs/aimd/`;
}), '水分子动力学模拟教程缺少独立工作台教程链接。');

const sitemapIndex = await readFile(path.join(output, 'sitemap-index.xml'), 'utf8');
const sitemapFiles = [...sitemapIndex.matchAll(/<loc>(.*?)<\/loc>/g)].map(match => new URL(decode(match[1])));
assert.ok(sitemapFiles.length, '站点地图索引为空。');
const sitemapUrls = new Set();
for (const url of sitemapFiles) {
  assert.equal(url.origin, origin.origin);
  const xml = await textFile(await localTarget(url));
  for (const match of xml.matchAll(/<loc>(.*?)<\/loc>/g)) {
    const value = decode(match[1]);
    assert.ok(value.startsWith(expectedRoot), `站点地图出现错误域名或路径：${value}`);
    assert.ok(!value.endsWith('/404/') && !value.endsWith('/404.html'), '404 不应出现在站点地图。');
    await localTarget(new URL(value));
    sitemapUrls.add(value);
  }
}
for (const url of canonicalUrls) assert.ok(sitemapUrls.has(url), `站点地图缺少页面：${url}`);
const robots = await readFile(path.join(output, 'robots.txt'), 'utf8');
assert.ok(robots.includes(`Sitemap: ${expectedRoot}sitemap-index.xml`), 'robots.txt 未指向正确的站点地图。');
await assert.rejects(stat(path.join(output, 'pagefind', 'pagefind.js')), { code: 'ENOENT' }, '文档搜索已关闭，不应生成搜索索引。');
console.log(`发布产物检查通过：${canonicalUrls.size} 个页面、${resourceFiles.size} 个本地页面/资源、${anchorChecks.size} 个页面锚点、${docsRoutes.length} 个文档路由、教程六张截图、站点地图、robots.txt、无搜索索引及 404。`);
console.log(`目标网址：${expectedRoot}（仅检查本地构建产物，不代表已部署或验证域名可访问。）`);

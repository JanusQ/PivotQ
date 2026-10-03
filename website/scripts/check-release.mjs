import assert from 'node:assert/strict';
import { readFile, readdir, stat } from 'node:fs/promises';
import path from 'node:path';
import { siteSettings } from './site-settings.mjs';

const { site, base } = siteSettings({ release: true });
const output = path.resolve(process.env.PORTAL_RELEASE_DIR || 'dist');
const origin = new URL(site);
const expectedRoot = `${site}${base}`;
const htmlFiles = [];
const resourceFiles = new Set();
const decode = value => value.replaceAll('&amp;', '&');

async function walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) await walk(file);
    else if (entry.name.endsWith('.html')) htmlFiles.push(file);
  }
}

function attrs(tag) {
  return Object.fromEntries([...tag.matchAll(/([\w:-]+)\s*=\s*["']([^"']*)["']/g)].map(match => [match[1], decode(match[2])]));
}

async function localTarget(url) {
  assert.ok(url.pathname.startsWith(base), `资源或页面链接逃逸部署路径：${url.href}`);
  const relative = decodeURIComponent(url.pathname.slice(base.length));
  const target = path.resolve(output, relative);
  assert.ok(target === output || target.startsWith(`${output}${path.sep}`), `非法资源路径：${url.href}`);
  const info = await stat(target).catch(() => null);
  assert.ok(info, `构建产物缺少：${url.href}`);
  if (info.isDirectory()) await stat(path.join(target, 'index.html'));
  resourceFiles.add(target);
}

await walk(output);
assert.ok(htmlFiles.length >= 5, '构建产物未包含首页、两个应用、使用指南和 404。');
const canonicalUrls = new Set();
for (const file of htmlFiles) {
  const relative = path.relative(output, file).split(path.sep).join('/');
  const html = await readFile(file, 'utf8');
  const route = relative === 'index.html' ? '' : relative.replace(/index\.html$/, '');
  const url = new URL(`${base}${route}`, origin);
  const tags = [...html.matchAll(/<(?:a|link|script|img|source|meta)\b[^>]*>/g)].map(match => attrs(match[0]));
  if (relative === '404.html') {
    assert.ok(tags.some(tag => tag.name === 'robots' && tag.content?.includes('noindex')), '404 必须禁止索引。');
  } else {
    const canonical = tags.find(tag => tag.rel === 'canonical');
    assert.equal(canonical?.href, url.href, `canonical 不匹配：${relative}`);
    canonicalUrls.add(url.href);
  }
  for (const tag of tags) {
    const value = tag.src || tag.href;
    if (!value || value.startsWith('#') || /^(data:|mailto:|tel:)/.test(value)) continue;
    const target = new URL(value, url);
    assert.ok(!['localhost', '127.0.0.1', '0.0.0.0', '[::1]'].includes(target.hostname), `包含本机链接：${relative}`);
    if (target.origin === origin.origin) await localTarget(target);
  }
}

const sitemapIndex = await readFile(path.join(output, 'sitemap-index.xml'), 'utf8');
const sitemapFiles = [...sitemapIndex.matchAll(/<loc>(.*?)<\/loc>/g)].map(match => new URL(decode(match[1])));
assert.ok(sitemapFiles.length, '站点地图索引为空。');
const sitemapUrls = new Set();
for (const url of sitemapFiles) {
  assert.equal(url.origin, origin.origin);
  await localTarget(url);
  const xml = await readFile(path.join(output, url.pathname.slice(base.length)), 'utf8');
  for (const match of xml.matchAll(/<loc>(.*?)<\/loc>/g)) {
    const value = decode(match[1]);
    assert.ok(value.startsWith(expectedRoot), `站点地图出现错误域名或路径：${value}`);
    assert.ok(!value.endsWith('/404/') && !value.endsWith('/404.html'), '404 不应出现在站点地图。');
    sitemapUrls.add(value);
  }
}
for (const url of canonicalUrls) assert.ok(sitemapUrls.has(url), `站点地图缺少页面：${url}`);
const robots = await readFile(path.join(output, 'robots.txt'), 'utf8');
assert.ok(robots.includes(`Sitemap: ${expectedRoot}sitemap-index.xml`), 'robots.txt 未指向正确的站点地图。');
await stat(path.join(output, 'pagefind', 'pagefind.js'));
console.log(`发布产物检查通过：${canonicalUrls.size} 个页面、${resourceFiles.size} 个本地页面/资源、站点地图、robots.txt、搜索索引及 404。`);
console.log(`目标网址：${expectedRoot}（仅检查本地构建产物，不代表已部署或验证域名可访问。）`);

import { loadEnv } from 'vite';

export function siteSettings({ release = false } = {}) {
  const env = { ...loadEnv(process.env.NODE_ENV || 'production', process.cwd(), ''), ...process.env };
  const rawBase = (env.SITE_BASE || '/').trim();
  if (!rawBase.startsWith('/') || /[?#\\\s]/.test(rawBase) || rawBase.includes('..') || rawBase.includes('//')) {
    throw new Error('SITE_BASE 必须是 / 或 /qhai/ 这样的 URL 路径，不包含域名、查询参数或相对路径。');
  }
  const base = rawBase.replace(/\/?$/, '/');
  const origin = (env.SITE_URL || '').trim();
  if (release && !origin) throw new Error('正式构建必须设置 SITE_URL，例如 https://你的正式域名。');
  if (!origin) return { base, site: undefined };

  const url = new URL(origin);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('SITE_URL 只填写 http(s) 域名；部署子目录单独通过 SITE_BASE 设置。');
  }
  if (release && (url.protocol !== 'https:' || /^(localhost|127\.|0\.0\.0\.0|\[::1\])/.test(url.hostname))) {
    throw new Error('正式构建的 SITE_URL 必须使用公网 HTTPS 域名，不能使用本机地址。');
  }
  return { base, site: url.origin };
}

if (process.argv.includes('--release')) {
  try {
    const settings = siteSettings({ release: true });
    console.log(`发布配置：${settings.site}${settings.base}`);
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}

import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { site } from './src/data/site.ts';
import { siteSettings } from './scripts/site-settings.mjs';

const settings = siteSettings();

export default defineConfig({
  output: 'static',
  base: settings.base,
  ...(settings.site ? { site: settings.site } : {}),
  trailingSlash: 'always',
  integrations: [starlight({
    title: site.name,
    description: site.description,
    disable404Route: true,
    defaultLocale: 'root',
    locales: { root: { label: '简体中文', lang: 'zh-CN' } },
    customCss: ['./src/styles/docs.css'],
    components: { ThemeSelect: './src/components/DocsTheme.astro', SiteTitle: './src/components/DocsTitle.astro' },
    social: site.githubUrl ? [{ icon: 'github', label: 'GitHub', href: site.githubUrl }] : [],
    sidebar: [
      { label: '系统介绍与使用指南', slug: 'docs' },
      { label: 'AIMD 案例', link: '/examples/aimd/' },
      { label: 'QRAM', link: '/examples/qram/' },
    ],
    head: [{ tag: 'meta', attrs: { name: 'theme-color', content: '#ffffff' } }],
  })],
});

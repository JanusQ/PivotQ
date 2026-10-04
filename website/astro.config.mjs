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
    components: {
      ThemeSelect: './src/components/DocsTheme.astro',
      SiteTitle: './src/components/DocsTitle.astro',
      Header: './src/components/DocsHeader.astro',
      PageTitle: './src/components/DocsPageTitle.astro',
      Footer: './src/components/DocsFooter.astro',
    },
    social: site.githubUrl ? [{ icon: 'github', label: 'GitHub', href: site.githubUrl }] : [],
    sidebar: [
      { label: '系统介绍', items: [
        { label: '文档首页', slug: 'docs' },
        { label: '系统与执行方式', slug: 'docs/architecture' },
      ] },
      { label: '使用文档', items: [
        { label: '入门', items: [
          { label: '安装', slug: 'docs/installation' },
          { label: '快速上手', slug: 'docs/quickstart' },
          { label: '常见问题', slug: 'docs/troubleshooting' },
        ] },
        { label: '混合编程', collapsed: true, items: [
          { label: '经典任务', slug: 'docs/classical-tasks' },
          { label: '量子后端', slug: 'docs/quantum-backends' },
          { label: '混合程序', slug: 'docs/hybrid-programs' },
          { label: '组件与 Actor', slug: 'docs/components-actors' },
          { label: '可复用工作流', slug: 'docs/workflows' },
        ] },
        { label: '运行与管理', collapsed: true, items: [
          { label: '集群作业', slug: 'docs/jobs' },
          { label: '状态与执行报告', slug: 'docs/observability' },
        ] },
        { label: '性能建模与预测', collapsed: true, items: [
          { label: '硬件性能模型', slug: 'docs/hardware-profiles' },
          { label: '性能预测', slug: 'docs/performance' },
        ] },
        { label: '后端扩展', collapsed: true, items: [
          { label: '扩展量子后端', slug: 'docs/providers' },
        ] },
        { label: 'API 参考', collapsed: true, items: [
          { label: 'API 索引', slug: 'docs/api' },
          { label: '运行时与结果引用', slug: 'docs/api/runtime' },
          { label: '组件与 Actor', slug: 'docs/api/components' },
          { label: '工作流', slug: 'docs/api/workflows' },
          { label: '量子后端与结果', slug: 'docs/api/quantum' },
          { label: 'Provider 协议', slug: 'docs/api/providers' },
          { label: '集群作业', slug: 'docs/api/jobs' },
          { label: '执行报告', slug: 'docs/api/observability' },
          { label: '性能模型与预测', slug: 'docs/api/performance' },
          { label: '异常类型', slug: 'docs/api/errors' },
        ] },
      ] },
      { label: '应用示例', items: [
        { label: '示例导航', slug: 'docs/examples' },
        { label: '工作台教程', slug: 'docs/aimd' },
      ] },
    ],
    head: [{ tag: 'meta', attrs: { name: 'theme-color', content: '#ffffff' } }],
  })],
});

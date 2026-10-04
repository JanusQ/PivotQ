# 门户发布说明

门户位于 PivotQ 仓库的 `website/`。它是多页静态站点，发布产物为 `website/dist/`，不需要运行时 Python、Ray、QPU、数据库或 Node 服务。源文件、依赖与实验目录不属于发布内容。

## GitHub Pages

目标地址：`https://janusq.github.io/PivotQ/`。

仓库管理员先进入 **Settings → Pages → Build and deployment → Source**，选择 **GitHub Actions**。使用工作流内的 `GITHUB_TOKEN` 和 GitHub Pages 部署身份，无需创建或保存个人访问令牌。

仓库根目录的 `.github/workflows/website.yml` 使用 Node.js 24，在 `website/` 中通过 `npm ci` 按锁文件安装依赖，并以以下配置执行正式构建、检查及浏览器回归：

```text
SITE_URL=https://janusq.github.io
SITE_BASE=/PivotQ/
```

- PR 只执行验证，不部署。
- `website/`、`packages/framework/examples/` 或本工作流的改动推送到 `main` 后会触发验证，通过后上传 `website/dist/` 并部署至 GitHub Pages；也可以在 `main` 手动运行。文档构建会读取仓库中的实际 Python 示例源码，因此示例更新也会触发网站重建。
- 功能分支上的手动运行只验证，不部署。

维护者自行提交、推送并合并变更。首次发布后，以 Actions 的部署结果和实际 HTTPS 访问为准；配置文件存在不代表已经上线。

## 本地复现正式构建

使用 Node.js 24，从仓库根目录进入门户后执行：

```bash
cd website
npm ci
npx playwright install chromium
SITE_URL=https://janusq.github.io SITE_BASE=/PivotQ/ npm run build:release
SITE_URL=https://janusq.github.io SITE_BASE=/PivotQ/ npm run preview -- --port 4323
```

访问 `http://127.0.0.1:4323/PivotQ/`。预览必须保留与构建相同的 `SITE_URL` / `SITE_BASE`，不能用默认根路径预览这份子目录产物。另开终端，在 `website/` 执行：

```bash
PORTAL_TEST_URL=http://127.0.0.1:4323/PivotQ/ npm run test:browser
```

正式构建会校验配置、类型、静态资源、canonical、sitemap、robots.txt、文档搜索索引与站内路径。浏览器回归覆盖导航、响应式布局、电路视图及已有轨迹播放，不提交计算任务。构建检查不代替实际公网验收。

日常本地开发不设置上述变量，使用 `npm run dev`，默认地址为 `http://127.0.0.1:4321/`。若改用 `.env` 保存部署变量，应避免与当前预览目标冲突，且不提交 `.env`。

## 自有服务器 / 学校服务器

获得实际域名与托管路径后，以该地址重新构建。例如部署到域名根目录：

```bash
SITE_URL=https://你的正式域名 SITE_BASE=/ npm run build:release
```

`SITE_URL` 只包含 HTTPS 域名；子目录单独通过 `SITE_BASE` 指定。域名申请、学校上线手续、DNS 和 TLS 证书由所属单位及托管管理员办理。

1. 将 `dist/` **内部的全部内容**上传至网站目录，例如 `/srv/qhai-site/`，避免多套一层 `dist/`。
2. 参考 `deploy/nginx.conf.example` 配置 Nginx。模板监听 HTTP 8080，适用于已有 HTTPS 网关后方；独立提供服务时需配置实际域名、TLS 证书及 HTTP 到 HTTPS 的跳转。
3. 在目标服务器执行 `nginx -t` 后再加载配置，并从校外网络验证实际 HTTPS 地址。

不要启用“所有地址返回首页”的 SPA 重写。保留 `_astro/`、`pagefind/`、文档目录、`404.html`、`robots.txt` 与 sitemap 文件。

### 服务器子目录部署

例如使用 `SITE_BASE=/PivotQ/` 构建，将产物放入 `/srv/www/PivotQ/`。现有 Nginx `server` 使用 `root /srv/www;` 时可添加：

```nginx
location = /PivotQ { return 301 /PivotQ/; }
location /PivotQ/ {
    try_files $uri $uri/ =404;
    error_page 404 /PivotQ/404.html;
    add_header Cache-Control "no-cache";
}
location = /PivotQ/404.html { internal; }
location /PivotQ/_astro/ {
    try_files $uri =404;
    error_page 404 /PivotQ/404.html;
    add_header Cache-Control "public, max-age=31536000, immutable";
}
```

由管理员结合现有站点配置验证，不能用该片段覆盖同域的其他网站。搜索引擎读取域名根目录的 `/robots.txt`；服务器子目录部署时，由根站点维护者将生成文件中的 `Sitemap:` 行合入根站点规则。GitHub Pages 项目站的部署不会修改组织根站点的 robots.txt。

## 上线验收与更新

- 首页、AIMD、QRAM 与文档可以直接打开并刷新；错误路径返回 HTTP 404。
- 中文搜索、手机导航、代码展示与轨迹播放正常，浏览器无本地资源加载错误。
- canonical 和 sitemap 使用实际域名与路径，GitHub 入口指向 `https://github.com/JanusQ/PivotQ`。

可对已发布站点执行只读浏览器验收：

```bash
PORTAL_TEST_URL=https://janusq.github.io/PivotQ/ npm run test:browser
```

GitHub Pages 更新沿用工作流；自有服务器更新应先上传完整产物，再切换站点目录，保留上一版以便回退。HTML 与搜索索引需重新验证缓存，带哈希的 `_astro/` 资源可长期缓存。

## 已知依赖告警

2026-10-03 的 `npm audit` 报告 7 项告警（5 high、2 low），源自以下两个上游问题；其余条目是依赖关系传播的计数。目前未在本站调用方式中发现对应的触发条件，此结论仅适用于当前静态网站。

- [`http-cache-semantics` 缓存响应泄露](https://github.com/advisories/GHSA-ch52-4w7c-c8xp)：Astro 使用该包处理构建时远程图片缓存；本站未使用远程图片，GitHub Pages 也不运行 Astro 服务。当前上游尚无已发布的修复版本。
- [DOMPurify 原地净化漏洞](https://github.com/advisories/GHSA-p98j-92pf-mc4p)：漏洞要求 `IN_PLACE` 模式及移除节点的净化钩子；Monaco 当前调用未开启该模式，本站编辑器只读展示仓库内的示例代码。DOMPurify 已有补丁，但 Monaco 内嵌的旧源码需由其上游更新，单独覆盖依赖版本不能修复实际浏览器代码。

此次迁移保留锁文件。后续升级上游依赖时重新审计并运行正式构建与浏览器检查；不要使用 `npm audit fix --force` 自动跨大版本降级现有框架。

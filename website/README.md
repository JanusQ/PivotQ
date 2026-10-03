# PivotQ 门户网站

本目录是 PivotQ 门户的维护位置。网站使用 Astro、TypeScript、CSS 与 Starlight，包含首页、系统介绍与使用指南、水分子 AIMD 静态示例和 QRAM 介绍。门户是只读静态网站，没有后端或在线计算接口；计算工作台位于仓库的 `dashboard/`。

## 本地开发

使用 Node.js 24，在仓库根目录执行：

```bash
cd website
npm ci
npm run dev
```

默认访问 `http://127.0.0.1:4321/`。检查并预览静态产物：

```bash
npm run check
npm run build
npm run preview
```

开发服务和预览服务不要同时占用同一端口。浏览器回归需要先启动预览，在另一个终端执行：

```bash
npx playwright install chromium
npm run test:browser
```

## 内容维护

| 内容 | 文件 |
| --- | --- |
| 名称、GitHub 与可选应用地址 | `src/data/site.ts` |
| 首页 | `src/pages/index.astro` |
| 系统介绍与使用指南 | `src/content/docs/docs/index.md` |
| AIMD 页面 | `src/pages/examples/aimd.astro` |
| QRAM 介绍 | `src/pages/examples/qram.astro` |
| 逻辑电路 | `src/components/QuantumCircuit.astro` |
| 示例数据、图片与电路源码 | `public/aimd/` |
| 首页互联图片 | `public/images/quantum-hpc-interconnect.png` |
| 页面样式 | `src/styles/global.css` |

系统是连接经典计算（CPU）与量子计算（QPU）的通用融合编程框架，水分子 AIMD 只是应用示例。维护时遵循 `AGENTS.md` 的内容与数据来源约定。

AIMD 页面读取 `public/aimd/imported/` 的 CSV 绘制曲线与三维轨迹，“重新播放”只重播已有数据。该导入轨迹未附硬件后端记录；`public/aimd/` 根目录保存的 qfp 历史运行数据与 `results.json`、使用指南独立采集的 CPU 操作记录均是不同来源，不能混用。详细条件与单位见 `public/aimd/README.md`。QRAM 当前仅为概念介绍。

GitHub 入口为 `https://github.com/JanusQ/PivotQ`。AIMD 与 QRAM 卡片默认进入站内介绍；外部应用地址可通过 `aimdUrl` / `qramUrl` 配置。

## 发布

GitHub Pages 目标地址为 `https://janusq.github.io/PivotQ/`，正式构建配置为：

```bash
SITE_URL=https://janusq.github.io SITE_BASE=/PivotQ/ npm run build:release
```

仓库工作流 `.github/workflows/website.yml` 对 PR 执行构建、检查和浏览器回归；仅 `main` 分支的推送或在 `main` 手动运行工作流可部署。仓库管理员需将 **Settings → Pages → Source** 设为 **GitHub Actions**。配置工作流本身不代表网站已经上线；提交、推送与合并由维护者完成。

子目录预览、验收及学校服务器部署步骤见 [DEPLOYMENT.md](DEPLOYMENT.md)。

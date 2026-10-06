# PivotQ 量超智融合系统门户

门户采用蓝色工作流设计，展示 CPU、GPU、QPU 的协作方式，并提供完整文档、水分子动力学模拟教程与量子随机存取存储器教学笔记。源码位于 PivotQ 仓库的 `website/`，由 `website-flow/` 新版迁入；独立源码包也可以在 `website-flow/` 下构建。

这是 Astro 多页静态站点。实际计算工作台位于仓库的 `dashboard/`；GPU 调度、公开 SDK 与性能模型的适用范围见文档。水分子动力学应用的 Linux 可视化操作教程通过教程页面链接打开，保留独立 `/docs/aimd/` 路由。

## 本地开发

使用 Node.js 24，在仓库根目录执行：

```bash
cd website
npm ci
npm run dev
```

访问 <http://127.0.0.1:4321/>，支持热更新。独立源码包进入其 `website-flow/` 目录执行相同命令；端口已被占用时可使用 `npm run dev -- --port 4324`。

检查并预览构建产物：

```bash
npm run check
npm run build
npm run preview -- --port 4324
```

访问 <http://127.0.0.1:4324/>。构建预览不提供源码热更新。浏览器回归在另一个终端运行：

```bash
npx playwright install chromium
PORTAL_TEST_URL=http://127.0.0.1:4324/ npm run test:browser
```

已有 Chrome 时可用 `PORTAL_TEST_BROWSER` 指定可执行文件路径。

## 页面与维护位置

| 内容 | 维护位置 |
| --- | --- |
| 系统名称、描述与 GitHub 链接 | `src/data/site.ts` |
| 首页及教程入口 | `src/pages/index.astro` |
| 实验室照片与首屏 | `src/components/HomeOverview.astro`、`src/assets/hero-lab.png` |
| CPU/GPU/QPU 三维示意与代码片段 | `src/components/HardwareArchitecture.astro`、`src/lib/hardware-scene.ts` |
| 三维场景静态回退图 | `public/images/hardware-render-poster.webp` |
| 工作流步骤展示 | `src/components/FlowWorkbench.astro` |
| 文档、SDK 与 API | `src/content/docs/docs/`、`src/content/guide/system.md` |
| 文档导航与主题 | `astro.config.mjs`、`src/components/Docs*.astro`、`src/styles/docs.css` |
| 独立水分子动力学应用的 Linux 可视化操作教程与六张截图 | `src/pages/docs/aimd.astro`、`src/content/guide/aimd.md`、`src/assets/guides/aimd/` |
| 水分子动力学模拟 notebook、轨迹与来源 | `src/pages/examples/aimd.astro`、`public/aimd/` |
| 量子随机存取存储器教学笔记与本地程序 | `src/pages/examples/qram.astro`、`src/lib/qram_query.py` |
| 全站辅助文字字号 | `src/styles/typography.css`：标签 14px、说明 15px、主要导航 16px；通过公共页头供门户与文档使用。窄屏优先换行和调整间距，图表刻度按实际缩放单独适配。 |

文档保留系统介绍、入门、混合编程、GPU 计算、运行管理、性能预测、Provider 扩展和分模块 API 参考。SDK 代码展示优先读取仓库中的实际示例；独立源码包保留可展示的示例副本。

首页 01 的四段代码以仓库中的水分子动力学模拟应用为例：CPU 读取原子位置、根据能量变化求力并推进轨迹；QPU 阶段运行电路，取得测量特征；GPU 用这些特征预测势能；最后由 CPU 提交整项作业。计算时，这些步骤按输入、量子特征、势能预测、位置更新的顺序反复衔接。应用源码位于 `applications/h2o-hybrid-aimd/`。门户只展示关键步骤，不在页面中提交任务；三维设备模型与实验室照片不表示实际部署或实测结果。场景可拖拽旋转，滚轮不能缩放；聚焦画布后按 Home 键恢复初始视角。

GPU 是系统支持的计算资源。公开 `pivotq` Python SDK 当前没有直接的 GPU 资源参数，GPU 计算经内部 Ray 组件或应用桥接配置；GPU 性能预测使用 `packages/perf-sim` 的模型及命令行入口。水分子动力学应用的 Linux 可视化操作教程截图的目标配置是 CPU/QPU，实际运行采用 CPU 数值模拟；首页的 GPU/QPU 分工不能当作那次运行的记录。

水分子动力学模拟轨迹回放读取已保存的 CSV；电路代码、导入轨迹与教程截图来自不同来源，详见 `public/aimd/README.md`。量子随机存取存储器是理想态矢量教学程序，不提交 PivotQ 任务。更多维护约定见 [AGENTS.md](AGENTS.md)。

## 构建与发布

仓库 `.github/workflows/website.yml` 构建 `website/`。各分支推送网站相关改动时自动验证，PR 也会验证；仅 main 的推送或手动运行发布到 GitHub Pages。配置目标为 <https://janusq.github.io/PivotQ/>；是否已发布以实际 Actions 结果和 HTTPS 访问为准。

```bash
SITE_URL=https://janusq.github.io SITE_BASE=/PivotQ/ npm run build:release
SITE_URL=https://janusq.github.io SITE_BASE=/PivotQ/ npm run preview -- --port 4324
PORTAL_TEST_URL=http://127.0.0.1:4324/PivotQ/ npm run test:browser
```

发布预览与测试都须包含 `/PivotQ/`。自有服务器、Nginx 与发布检查说明见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 2026-10-05 页面反馈

本次反馈修改仅作用于 `website/`（本机 4321），未修改 4322 的 `website-flow/`。首页任务编排后分别进入真机执行或离散事件仿真，并展示对应的性能报告；阶段切换按钮和顶部“系统”入口已移除。网站统一使用“文档”“水分子动力学模拟”“量子随机存储器”；完整工作台教程保留在教程入口。用户提供的万量子比特、千卡、百万事件规模文案按原意展示，本次验证范围是页面内容、链接、交互和布局，不包含性能基准测试。

本轮页面反馈可通过 `PORTAL_TEST_URL=http://127.0.0.1:4321/ npm run test:comments` 复查；测试覆盖 320–1920px 布局、桌面标题单行、分支与报告、手机横向导航、文档入口和六张教程截图。浏览器截图及检查记录位于 `artifacts/comments-root/`；传入带子路径的 URL 时位于 `artifacts/comments-subpath/`。如使用本机 Chrome，设置 `PORTAL_TEST_BROWSER` 指向浏览器可执行文件。

## 2026-10-06 文案与入口说明

门户说明 Linux 服务、浏览器操作界面与水分子应用的关系；按修改清单更新首页、教程与 dashboard 文案。首页已移除未经验证的规模数字与复杂度字段。六张教程截图保留为明确标注的历史记录。逐项处理与技术依据见 [修改核对](COPY_REVIEW_2026-10-06.md)。

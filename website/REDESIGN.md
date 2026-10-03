# 2026-10-01 门户改版交付

源码已更新至 zju `/opt/data/private/zhn/launch-event/intro-website/site`，预览静态文件为该目录下的 `dist/`。

## 完成内容

- 首页精简为主视觉、两个应用入口、三个系统能力和单一指南入口，使用用户提供的「量超智互联.jpg」。
- AIMD：F2/A2 逻辑电路、原生门电路、运行入口、动力学/量子代码节选、固定运行曲线、轨迹图、结果表与 CSV/JSON 下载。
- QRAM：可访问的介绍页面；尚无项目实现与运行结果，明确标注材料准备状态。
- 文档：原多篇模块说明合并为一篇功能与接口介绍，留给项目作者继续编写。

## 验证

- Node.js 24 下 `npm run check`：20 个文件，0 errors / 0 warnings / 0 hints。
- `npm run build`：5 个静态页面（含 404）。未设置正式域名，普通预览构建不生成 sitemap。
- `node scripts/check-results.mjs`：1001 帧；步数、初始温度、时间、总能量变化及极差与源 CSV 一致。
- 以示例测试域名和 `/qhai/` 构建的子目录产物：4 内容页、24 本地页面/资源及 sitemap、robots、搜索索引、404 检查通过。此为本地构建检查，不代表域名部署。
- 实际浏览器验收：390/768/1440px 首页、AIMD、QRAM、指南；手机菜单/Escape、代码复制、中文搜索、404 返回、电路及代码折叠；页面加载后无横向溢出。
- 服务器当前预览的 4 页面和 10 项静态资源均返回 HTTP 200。
- 浏览器验收通过 Codex 浏览器执行；可复用 `scripts/browser-check.mjs` 已适配新页面，但本次没有另行运行该脚本。

## 备份与入口

- 改版前 Git HEAD：`a89048e`；工作树初始为干净。
- 完整源码备份：`/opt/data/private/zhn/launch-event/intro-website/site-before-redesign-20261001.tgz`（不含依赖、Git、缓存与构建产物）。
- 原文档额外保留于服务器 `site/artifacts/previous-docs/`。
- 本地源码：`D:/projects/front/site`；截图和 HTTP 记录：`D:/projects/front/evidence/`。
- 服务器原预览仍为 `127.0.0.1:4321`；本机当前 SSH 隧道入口为 `http://127.0.0.1:14321/`，依赖隧道在线。

## 待作者提供

完整使用指南、QRAM 项目内容、可公开 GitHub 地址、正式 ZJU 域名与发布路径。尚未发布公网；没有后端、注册登录或在线任务提交。

数据与电路的详细出处见 `public/aimd/README.md`；未将模拟结果描述成真实 QPU 结果。

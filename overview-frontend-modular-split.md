# 前端模块化拆分（已完成 · 两阶段）

## 做了什么

### 第一阶段（独立页面）
- **后端 `web/app.py`**：`do_GET` 新增多页面静态路由白名单 `/invoices.html` `/companies.html` `/common.css` `/common.js` `/index.js`（404 兜底），`/api/*` 不变。
- **公共基座**：`web/common.css`（原 `index.html` 内联样式外提 + 独立页顶栏 `.topbar`/`.topnav` 导航样式 + 新增 `.subtabs` 子导航样式）、`web/common.js`（`API`/`escapeHtml`/`fmt*`/`stripEmpty`/`pdfCell`/`attrBadge`/`pollJob`/进度条 + `renderNav` 跨页导航生成）。
- **独立页面**：`web/invoices.html`（发票台账）、`web/companies.html`（公司管理），各自自包含、共享公共基座。

### 第二阶段（index.html 精简）
- **`web/index.js`（新增，37KB）**：用生成器从原 `index.html` 内联脚本**逐行节选**「账号 / 抓取 / 匹配」逻辑，剔除已独立的发票/公司函数与已上移 `common.js` 的共享工具（`API`/`escapeHtml`/`fmt*`/`pollJob` 等）。两处定向裁剪：`loadSelectors` 去掉发票筛选下拉；`startPoll` 去掉抓取完成后调用的发票 `load()`；新增 `switchTab` + 读 `?tab` 启动逻辑。
- **`web/index.html`（重写，18.5KB，原 109KB）**：`head` 引用 `common.css`（删内联 style）；顶部 5-tab 换 `renderNav` 链接式导航；新增 `.subtabs` 子导航（账号/抓取/匹配）；删除发票台账 Tab、公司管理 Tab 及其弹窗（导出/公司编辑/批量改所属公司）；引用 `common.js` + `index.js`。

## 解决的核心痛点
原「查看发票」= tab 内跳回台账 + 下拉筛选，上下文丢失、无反馈，观感像手动查。
现在：公司页点「查看发票」→ 跳 `invoices.html?company_id=X`，顶部面包屑 **公司管理 › X公司 › 发票**，URL 自带状态、可书签、上下文不丢。

原 `index.html` 单文件约 2200 行，账号/抓取/匹配逻辑与发票/公司逻辑耦合、难以复用。
现在：四页面共享 `common.css`/`common.js`，发票台账、公司管理作为独立可复用页面，账号/抓取/匹配留在 `index.html` 内以 `.subtabs` 子导航切换，跨页经 `renderNav` + 面包屑保持连贯。

## 文件清单
- 新增：`web/common.css`、`web/common.js`、`web/invoices.html`、`web/companies.html`、`web/index.js`
- 重写：`web/index.html`（精简为账号/抓取/匹配外壳）
- 改动：`web/app.py`（静态路由白名单 + `/index.js`）

## 验证结果（全部通过）
- `node --check` 对 `common.js` / `index.js` / 线上 `index.js` 均 OK。
- `index.html` / `invoices.html` / `companies.html` / `common.css` / `common.js` / `index.js` 全 HTTP 200。
- 启动路径用 DOM/fetch 桩在 Node 跑通 `?tab=accounts` / `?tab=fetch` / `?tab=match` 三种，均无运行时错误。
- 启动接口 `/api/accounts` `/api/fetch/status` `/api/companies` `/api/invoices` `/api/cities` `/api/buyers` 均 200。
- `index.html` 已无 `tab-invoices` / `tab-companies` / 内联 `<script>` / `function load()` 残留。

## 本地访问（后端 managed venv，PID 27824，端口 8000）
- 发票台账：http://localhost:8000/invoices.html
- 公司管理：http://localhost:8000/companies.html
- 账号 / 抓取 / 匹配：http://localhost:8000/（默认账号 tab；`?tab=fetch` / `?tab=match` 直达）

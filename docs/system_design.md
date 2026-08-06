# invoice_hub 性能优化 · 系统架构设计 + 任务分解

> **作者**：高见远（架构师 / software-architect）
> **版本**：v1.0 · 对应 PRD「票归集性能优化（简单版）」
> **基线目标**：切换与加载「零等待」、数据常驻、交互即时；切 tab 回看 0 网络等待；二次进页面 <200ms 秒显、无闪烁；单发票页 DB 连接 ~6→~1；列表接口 SQL 2→1；排序/筛选 0 次服务端请求。
> **硬约束**：保持**零构建原生 JS**（不引入 Vite/打包器/前端框架）；后端保持 **Python 标准库零第三方依赖**；改动模块化复用，不推翻重写。

---

## 1. 实现方案 + 框架选型

### 1.1 核心技术挑战

| # | 挑战 | 当前痛点（代码锚点） | 目标 |
|---|------|----------------------|------|
| C1 | 导航全量重载 | `web/common.js:72-83` `renderNav` 纯 `<a href="invoices.html">` | 切 tab 不重载、数据常驻 |
| C2 | 缓存仅会话内有效 | `web/invoices.html:184-195` `_cachedRows` 切页即丢；`load()` L216-248 每次重 fetch | 进页面先渲染缓存再后台刷新 |
| C3 | 连接 churn | `db.py:94-104` `conn()` 每次新建 | 单请求线程级复用 → ~1 连接 |
| C4 | 列表两次 SQL | `web/app.py:333-334` 调 `get_invoices` + `get_invoices_count` | `COUNT(*) OVER()` 合 1 次 |
| C5 | 多余服务端请求 | `web/invoices.html:297-305` 排序点击触发 `load()` | 排序/筛选全前端 |
| C6 | 零缓存头 | `web/app.py:58-67 _json` / `268-293 _send_file` 均无 | 静态资源 + 只读 API 加 Cache-Control/ETag |
| C7 | 缓存失效与跨 tab 一致 | 无统一机制 | 写后主动 purge + 跨 tab 广播 |

### 1.2 选型结论（零依赖）

- **后端**：维持 `http.server` + `ThreadingHTTPServer`。新增能力全部用标准库实现：
  - 缓存头：`app.py` 增加 `_cache_control` / `_etag` 辅助函数（无新包）。
  - 连接池：`db.py` 用 `threading.local` + `threading.Lock` + `queue.Queue` 自研轻量池（WAL 已开启，`db.py:101`）。
  - SSE（P2）：`ThreadingHTTPServer` 长连接写出 `text/event-stream`（标准库可做到，**不引入** `websockets`）。
- **前端**：保持原生 JS、零构建。新增模块（`cache.js` / `store.js` / `router.js` / `views/*`）均为普通 `<script>` 顺序加载或 ES Module（`type="module"` 浏览器原生支持，无需打包）。复用 `common.js` 的 `API`/`fmt*`/`pollJob`/`renderNav`。
- **不引入**：Vite、React/Vue、webpack、websockets、任何 ORM。**理由**：用户明确偏好「零构建/数据驱动/反硬编码」且当前不想引入框架（PRD Q5）；本地单用户桌面场景，标准库 + 原生 JS 已足够，引入工具链反而增加维护面与部署复杂度。

### 1.3 SPA 改造的具体形态（P1·E）

**单壳 + 哈希路由 + 视图模块 + 全局 store**，导航不重载、数据常驻：

```
app.html  ── 单入口外壳：<div id="view"></div> + 顶部 nav(哈希链接) + 「更新中」角标 + 顶部细进度条 + 骨架屏容器
  ├─ router.js     解析 location.hash (#/invoices, #/companies, #/console)
  │                 映射 ViewCtor；onhashchange → unmount 旧视图 / mount 新视图（无整页刷新）
  ├─ store.js      全局 store：invoices[] / companies[] / accounts[] / filters / stats；pub-sub
  ├─ cache.js      缓存契约（见 §3）：内存 + sessionStorage + localStorage 协调；跨 tab 失效
  ├─ api.js        ApiClient：get/post；post 成功后按命名空间 purge 缓存 + 广播
  └─ views/
       ├─ invoices.js   原 invoices.html 的 <script> 逻辑抽为 mount/unmount；排序/筛选前端本地
       ├─ companies.js  原 companies.html 逻辑；抽屉改「内联挂载」(共享 store，去掉 iframe)
       └─ console.js    原 index.js 逻辑（账号/抓取/匹配 三个子 tab）
```

- **抽屉去 iframe 化**：当前 `web/companies.html:217-232` 用 iframe 复用 invoices.html，「首次展开才设 src、收起保留状态」是良好的「局部常驻」思路。SPA 后改为在同一页面内联挂载 `InvoicesView` 到子容器（共享 store 与模块），更彻底地避免重复加载与双滚动条。
- **MPA 兼容**：SPA 上线前，P0 改动（A/B/C/D）直接在现有 `invoices.html`/`companies.html` 上做，保持 MPA 可用；SPA 上线后，旧 `.html` 加一行重定向到 `app.html#/...` 作为兜底。

### 1.4 六个待确认问题：推荐方案 + 理由

**Q1 改造节奏：先 P0 上线见效，还是一次性大改？**
> **推荐：分阶段，先 P0。** 理由：P0(A/B/C/D) 直接命中北极星「像本地 App」——缓存优先渲染、零等待、连接复用、单 SQL——且低风险、不触碰架构（MPA 即可落地）。SPA(P1·E/F) 是更大架构变动，应先验证 P0 带来的体感收益与数据规模，再决定是否值得做 SPA；若数据量很小，P0 已足够「像本地 App」，SPA 可暂缓。与用户「零构建、分阶段」偏好一致。

**Q2 数据量级：全量进内存(F)什么量级需保留后端分页？**
> **推荐阈值（可配置）**：
> - `IN_MEMORY_CAP = 50000`（桌面默认）：≤ 此值 → 全量进内存，翻页/排序/筛选全前端。
> - `> 50000`：回退服务端分页（仍对「当前页结果」做前端缓存以支持秒回看），新增 `get_invoices_all(filters, cap)` 一次性返回（受 cap 保护，超限截断并提示）。
> - 设备自适应：移动端把 cap 降到 `10000`（每行约 1–2KB JSON，5 万≈50–100MB，桌面可接受、移动偏重）。
> 理由：给用户明确、可代码常量化的回退边界，避免「全量进内存」在大数据下拖垮弱设备。

**Q3 缓存失效策略：只读 API 缓存多久刷新？写后如何立即失效？**
> **推荐**：
> - 前端缓存条目带 `v`(dataVersion) + `ts`(拉取时刻)。软 TTL（如 5min）仅用于「是否值得后台刷新」的提示，不阻塞渲染。
> - 只读 API 响应头携带 `X-Data-Version: N`（N 为全局数据版本，见 §3 `DataVersion`）。后台静默重拉时比较返回 version 与本地 `v`：相同 → 数据未变、跳过重渲染；增大 → 数据已变、更新缓存并差异刷新。
> - **写后即时失效**：任一写操作（删除/上传/改归属/公司 CRUD/账号 CRUD）成功后，`ApiClient.post` 按受影响命名空间 `cache.purge(ns)`，并写入 `localStorage` 失效信号 + 派发 `ih:invalidate` 事件；其他 tab 经 `storage` 事件收到后 purge 自身缓存并重渲染。后端同步 `bump_data_version()`。
> 理由：版本号机制既能「长时间不重拉未变数据」，又能在写后秒级失效，无需轮询。

**Q4 会话边界：sessionStorage(单 tab) vs localStorage(跨 tab)？多 tab 一致？**
> **推荐：两者配合（数据在 sessionStorage，协调在 localStorage）**：
> - **sessionStorage** 存重型数据集（发票/公司列表）——按 tab 隔离，避免多 tab 重复占内存、规避 localStorage 配额（~5MB）瓶颈。是实现「<200ms 秒显」的主缓存。
> - **localStorage** 只存轻量「缓存清单/失效日志 + 全局 dataVersion」——用于跨 tab 协调。监听 `storage` 事件：某 tab 写后 purge，其余 tab 收事件后 purge 自己的 sessionStorage 并后台刷新。
> - 内存 Map 作为最热层（SPA 会话内最快）。三者回退链：**内存 → sessionStorage → 网络**。
> 理由：兼顾「秒显」与「多 tab 一致」，且不踩 localStorage 配额。

**Q5 SPA 构建：是否引入 Vite/打包器？**
> **推荐：保持零构建原生 JS**，用客户端哈希路由 + 视图模块。理由：用户当前明确不想引框架/打包器；零构建开发闭环最简、部署即静态文件，可被现有 `http.server` 直接服务；`<script type="module">` 原生支持模块化，无需打包。若未来规模膨胀再评估，但当前不需要。

**Q6 度量基线：可落地的基线采集方式？**
> **推荐（零依赖）**：
> - **前端**：`perf.js` 用 Performance API——`performance.mark('nav_start')`/`measure('first_data_paint', …)` 测「导航→首屏数据」耗时；`performance.getEntriesByType('resource')` 统计切 tab 的请求数。结果 `console.table` 输出，并可选 POST 到 `app.py` 新增的 `GET /api/debug/metrics`（仅 `PERF=1` 时启用）。
> - **后端连接数**：把 `conn()` 换成池，`ConnectionPool.stats()` 暴露 `{active, max, created}`；`app.py` 新增 `GET /api/debug/connpool`（仅 `PERF=1`）返回当前活跃连接，验证 ~6→~1。
> - **SQL 次数**：`db.py` 加全局计数器（包裹 `execute`），`/api/debug/connpool` 同时返回「本请求 SQL 数」，验证列表 2→1。
> 理由：全部基于标准库/浏览器原生能力，可在本地一键复现，无需外接 APM。

---

## 2. 文件列表及职责（相对路径）

> 前缀 `web/`、`db.py`、`api.py` 均在项目根 `invoice_hub/` 下。

### 2.1 后端（修改/新增）
| 文件 | 动作 | 职责 |
|------|------|------|
| `web/app.py` | 修改 | 增缓存头辅助 `_cache_control/_etag/_no_cache`；`/api/invoices` 改用 `get_invoices_merged`（单 SQL）；新增 `GET /api/version`、`GET /api/debug/connpool`、`GET /api/debug/metrics`(PERF)、`GET /api/stream`(P2 SSE)；静态与只读 API 套缓存头 |
| `db.py` | 修改 | 用 `ConnectionPool` 替换 `conn()`（`get_conn/put_conn`，线程级复用 + 上限）；新增 `get_invoices_merged`（窗口函数）；新增 `DataVersion`(`get/bump`)；新增 `get_invoices_all`（P1 全量）；新增 SQL/连接计数器；保留 `_get_companies_snapshot` 作只读缓存范本 |
| `api.py` | 修改(小) | 暴露 `get_data_version()`；写路径调用 `bump_data_version()`（或在 db 层统一 bump） |

### 2.2 前端（新增/修改）
| 文件 | 动作 | 职责 |
|------|------|------|
| `web/cache.js` | **新增** | `CacheStore`：命名空间 + 内存/sessionStorage/localStorage 三级；`get/set/purge/purgeAll`；`storage` 事件跨 tab 失效 |
| `web/store.js` | **新增** | `GlobalStore`：数据集/筛选/统计状态 + `subscribe/emit` pub-sub |
| `web/router.js` | **新增** | 哈希路由：`#/invoices`、`#/companies`、`#/console` → ViewCtor；mount/unmount；P2 预取钩子 |
| `web/api.js` | **新增** | `ApiClient`：`get/post`；`post` 成功后按 ns purge + 广播 |
| `web/perf.js` | **新增** | 基线度量（Performance API + 后端计数器读取） |
| `web/app.html` | **新增** | SPA 外壳（P1·E）：`#view` 容器 + nav + 「更新中」角标 + 顶部细进度条 + 骨架屏；注册 SW(P2) |
| `web/views/invoices.js` | **新增** | 发票台账视图模块（从 `invoices.html` 抽离）；排序/筛选前端本地 |
| `web/views/companies.js` | **新增** | 公司管理视图模块（抽屉内联挂载，去 iframe） |
| `web/views/console.js` | **新增** | 操作台视图模块（账号/抓取/匹配） |
| `web/common.js` | 修改 | 保留 `API/fmt*/pollJob`；新增 `renderNavSpa`（哈希链接）、`postWithInvalidate` 薄封装；`renderNav` 保留供 MPA 兜底 |
| `web/invoices.html` | 修改(P0) | 引入 `cache.js/store.js`，改 `load()` 为「缓存优先 + 后台刷新」；排序点击不再触发服务端 fetch；保留 MPA 兜底（SPA 后加重定向） |
| `web/companies.html` | 修改(P0) | 同样接入缓存优先；抽屉逻辑保持 |
| `web/index.html` / `web/index.js` | 修改(P0/P1) | P0 接缓存；P1 逻辑迁至 `views/console.js` |
| `web/common.css` | 修改 | 新增 SPA 外壳样式、`updating` 角标、顶部进度条、骨架屏、视图容器 |
| `web/sw.js` | **新增(P2·G)** | Service Worker：预缓存 app shell + 静态，运行时缓存，导航兜底 |
| `docs/system_design.md` | **新增** | 本设计文档 |
| `docs/sequence-diagram.mermaid` | **新增** | 调用时序图 |
| `docs/class-diagram.mermaid` | **新增** | 类/结构图 |

---

## 3. 数据结构与接口

### 3.1 前端全局 Store 结构（`store.js`）
```js
GlobalStore.state = {
  invoices: [],          // P1·F 全量进内存后的数据集
  companies: [],         // 公司清单（接 /api/companies）
  accounts: [],          // 账号（接 /api/accounts）
  filters: {},           // 当前发票筛选条件（来自搜索栏/URL）
  stats: null,           // 统计卡
  meta: { dataVersion: 0, lastFetchTs: 0 }
}
// API: getState() / setState(patch) / subscribe(fn)→unsub / emit(evt, payload)
```

### 3.2 缓存契约（`cache.js`）——key / 版本 / TTL
```
命名空间 NS = { INVOICES:'invoices', COMPANIES:'companies', ACCOUNTS:'accounts', STATS:'stats' }
key 格式:  ih:<ns>:<fingerprint>
           fingerprint = 稳定哈希(filters 序列化)  // 同一筛选条件命中同一缓存
value:     { v: <dataVersion>, ts: <拉取时刻ms>, data: <payload> }

内存层:  this._mem = Map<ns+key, entry>            // 最热，SPA 会话内
会话层:  sessionStorage['ih:'+ns+':'+key] = JSON    // 秒显主缓存（按 tab）
协调层:  localStorage['ih:manifest'] = {ns:[keys]}  // 轻量清单 + dataVersion
失效信号:localStorage['ih:invalidations'] = push({ns, key?, ts})  // 跨 tab 广播
TTL:      SOFT_TTL = 5*60*1000  // 仅用于「是否提示后台刷新」，不阻塞渲染
```
- `get(ns,key)`：内存 → sessionStorage → null（三级回退）。
- `set(ns,key,data,version)`：写三级 + 更新 manifest。
- `purge(ns,key?)`：清指定（或整 ns）+ 写失效信号 + 派发 `ih:invalidate`。
- `_onStorageEvt(e)`：监听 `storage`，收到 `ih:invalidations` 则 purge 本地并按需后台刷新当前视图。

### 3.3 后端连接池接口（`db.py`）
```python
class ConnectionPool:
    def __init__(self, max_connections: int = 16): ...
    def get_conn(self) -> sqlite3.Connection:   # 线程级复用：同线程返回同一连接
    def put_conn(self, conn): ...                # 实际为 no-op（连接随线程常驻，WAL 下安全）
    def stats(self) -> dict:                     # {active, max, created}
# 替换原 conn()：db.py 内所有调用方改为 get_conn()；对外保留 conn() 别名兼容。
```
**WAL 线程安全约定**：每个线程独享自己的连接对象（绝不跨线程共享同一连接）；WAL 允许多读者并发、写者经 WAL 锁串行化；`PRAGMA busy_timeout=8000`（`db.py:100`）保证写竞争时等待而非报错。后台抓取线程（engine）使用其自身线程的连接，与主请求线程互不干扰。

### 3.4 数据版本接口（`db.py`）
```python
class DataVersion:
    _ver: int = 0            # 进程内镜像
    def get(self) -> int: ...
    def bump(self): ...      # 内存 +1，并持久化到 meta 表(key='data_version')
# 触发点（写路径）：insert_invoice / delete_invoices / update_invoice_fields /
#                   assign_invoices / upsert_company / update_company / delete_company /
#                   account CRUD。建议统一在 db 层 mutation 函数尾部调用，覆盖 CLI/引擎/Web 全部路径。
# 读取：/api/version 返回 {"version":N}；只读响应附带 X-Data-Version: N 头。
```

### 3.5 列表合并接口（`db.py` + `app.py`）
```python
# db.py
def get_invoices_merged(filters=None, page=1, page_size=50):
    """单 SQL：内层筛选+JOIN+排序，外层 COUNT(*) OVER() 取总数，再 LIMIT/OFFSET。
       返回 (rows:list[dict], total:int)。窗口函数在 LIMIT 前计算，故 total 为全量匹配数。"""
# app.py  /api/invoices
rows, total = db.get_invoices_merged(filters, page, page_size)
_json_cached(self, {"rows": rows, "total": total, "page": page, "page_size": page_size}, version=db.get_data_version())
# 移除原 get_invoices_count 调用（标记 @deprecated，保留函数不删，避免外部引用断裂）
```
合并 SQL 骨架：
```sql
SELECT *, COUNT(*) OVER() AS _total
FROM (
  SELECT i.*, a.name AS account_name, a.email AS account_email, c.name AS company_name
  FROM invoices i
  LEFT JOIN accounts a ON i.account_id=a.id
  LEFT JOIN companies c ON i.company_id=c.id
  WHERE <_apply_filters 同原逻辑>
  ORDER BY i.invoice_date DESC, i.id DESC
)
LIMIT ? OFFSET ?;
```

### 3.6 类图
> 见 `docs/class-diagram.mermaid`（前端 CacheStore/GlobalStore/Router/View/ApiClient/Perf + 后端 ConnectionPool/InvoiceRepo/DataVersion/CacheHeaders/Handler，含关系与线程安全/版本注释）。

---

## 4. 程序调用流程（时序图）

> 见 `docs/sequence-diagram.mermaid`，含三个场景：
> 1. **切 tab 回看**（缓存命中 → 先显快照 + 顶部「更新中」→ 后台静默刷新 → 304/差异更新/失败保留快照标「X 分钟前」）。
> 2. **进页面首次加载**（有缓存 <200ms 秒显 + 角标 / 无缓存仅首次骨架屏 → 合并单 SQL 拉取）。
> 3. **P2 SSE 推进度**（替代 `/api/jobs` 轮询）。

关键差异点（对应诊断锚点修复）：
- `web/invoices.html:227-230` 原「仅缓存空才显加载中」→ 改为「命中即秒显，永不全屏遮罩，改用柔和角标/细进度条」。
- `web/invoices.html:297-305` 原排序点击 `load()` 触发服务端 fetch → 改为仅本地 `renderRows` 重排（0 网络请求）。
- `web/app.py:333-334` 原两次 SQL → 合并为 `get_invoices_merged` 一次。

---

## 5. 任务列表（有序、含依赖、按 P0→P1→P2 分组）

> 标注 `⚡可并行` 表示与同阶段其它任务无强依赖、可同期开工。每项含：任务名 / 改哪些文件 / 依赖 / 验收点 / 预估风险。

### P0（Tier1，必须，先上线见效）
**T-P0-A · 后端静态资源 + 只读 API 加缓存头**
- 文件：`web/app.py`(新增 `_cache_control/_etag/_no_cache` + 套用到静态 `_STATIC_PAGES` 与只读 JSON 路由)
- 依赖：无 ⚡可并行
- 验收：静态资源响应含 `Cache-Control`+`ETag`；只读 JSON 含 `Cache-Control: no-cache`+`ETag`；二次访问静态资源走 304/不重下载。
- 风险：低（纯响应头，不改业务逻辑）。

**T-P0-B · 前端缓存优先渲染（cache.js + store.js + 改 invoices/companies）**
- 文件：`web/cache.js`(新)、`web/store.js`(新)、`web/invoices.html`、`web/companies.html`、`web/common.js`(加 `postWithInvalidate`)
- 依赖：T-P0-A（用其 `X-Data-Version`/ETag 判失效）⚡与 A/C/D 可并行起步
- 验收：切 tab 回看 **0 网络等待**、**<200ms 秒显**；仅首次无缓存用骨架屏；禁止全屏「加载中」遮罩，改用「更新中」角标/顶部细进度条；后台刷新失败保留快照并标「X 分钟前数据」。
- 风险：中（跨 tab 一致性、缓存失效边界需仔细；先用 sessionStorage 主缓存，localStorage 仅协调）。

**T-P0-C · SQLite 连接线程级复用 / 池**
- 文件：`web/db.py`(以 `ConnectionPool` 替换 `conn()`，保留别名兼容)
- 依赖：无 ⚡可并行
- 验收：单发票页 DB 连接数 **~6 → ~1**（同请求内多次 `get_conn` 复用同一连接）；`GET /api/debug/connpool` 返回 `{active,max,created}`；并发读写在 WAL 下无 `database is locked`。
- 风险：中（须严守「每线程独立连接不跨线程共享」；后台 engine 线程独立连接已天然满足）。

**T-P0-D · 合并查列表 + 总数（`COUNT(*) OVER()`）**
- 文件：`web/db.py`(新增 `get_invoices_merged`)、`web/app.py`(`/api/invoices` 改用并移除 `get_invoices_count` 调用)
- 依赖：T-P0-C（建议在其后，复用池化连接）⚡与 A/B 可并行
- 验收：列表接口 **SQL 次数 2→1**；返回 `{rows,total}` 与原两次结果一致；`/api/debug/connpool` 的「本请求 SQL 数」为 1。
- 风险：低（窗口函数标准用法；保留原函数不删避免外部断裂）。

### P1（Tier2，应有）
**T-P1-E · 改造真 SPA（app.html + router.js + views）**
- 文件：`web/app.html`(新)、`web/router.js`(新)、`web/views/invoices.js`(新)、`web/views/companies.js`(新)、`web/views/console.js`(新)、`web/common.js`(加 `renderNavSpa`)
- 依赖：T-P0-B（依赖 store/cache）、T-P0-A
- 验收：顶部导航切换 **不整页重载**、数据常驻（store 跨视图保留）；切 tab 无网络等待；旧 `.html` 加重定向兜底。
- 风险：高（架构变动面最大；抽屉去 iframe 化、三视图逻辑迁移需回归测试）。

**T-P1-F · 全量发票进内存，翻页/排序/筛选全前端**
- 文件：`web/store.js`(扩展 `invoices`)、`web/views/invoices.js`(本地分页/排序/筛选)、`web/db.py`(新增 `get_invoices_all(filters, cap)`)
- 依赖：T-P1-E、T-P0-B
- 验收：**排序/筛选触发 0 次服务端请求**；`IN_MEMORY_CAP`(默认5万/移动1万) 内全前端；超阈值自动回退服务端分页且仍缓存当前页。
- 风险：中-高（大数据下内存；需阈值回退与移动端降配）。

### P2（Tier3，锦上添花）
**T-P2-G · Service Worker**
- 文件：`web/sw.js`(新)、`web/app.html`(注册)
- 依赖：T-P0-A ⚡可并行
- 验收：二次访问静态资源离线/秒开；导航兜底；`sw.js` 更新策略不阻塞首屏。
- 风险：低-中（缓存失效需随版本号 bust；调试期易踩 stale）。

**T-P2-H · 预取下一视图**
- 文件：`web/router.js`(预取钩子)、`web/views/*`
- 依赖：T-P1-E
- 验收：hover/聚焦 nav 或空闲时预取下一视图数据；切过去即秒显。
- 风险：低。

**T-P2-I · SSE/WebSocket 推进度**
- 文件：`web/app.py`(新增 `GET /api/stream` SSE)、`web/common.js`(改用 `EventSource` 替代部分轮询)
- 依赖：T-P0-C（长连接占线程，需池化稳定）
- 验收：抓取/导出进度**实时推送**，不再定时轮询 `/api/jobs`；**不引入** `websockets` 第三方包（用标准库 SSE）。
- 风险：中（`ThreadingHTTPServer` 长连接占线程，单用户本地可承受；需心跳保活 + 限单连接 + 异常释放）。

### 并行关系小结
- **首批可并行**：T-P0-A、T-P0-C、T-P0-D（三者互不阻塞，D 建议稍后吃 C 的池）。
- **第二批**：T-P0-B（与 A 同期，用 A 的 version 机制）。
- **串行门槛**：P1 全依赖 P0（E 依赖 B/A；F 依赖 E/B）；P2 中 G 依赖 A、I 依赖 C、H 依赖 E。

---

## 6. 依赖包列表

| 包 | 用途 | 是否引入 | 说明 |
|----|------|----------|------|
| （无） | P0–P1 全部 | **不引入** | 后端标准库 + 前端原生 JS 已覆盖 |
| `websockets` | P2·I 实时进度 | **不引入（推荐）** | 用标准库 SSE(`text/event-stream` 长连接)替代，零依赖 |
| Service Worker | P2·G | 原生 | 浏览器原生，无需包 |
| ES Module | SPA 模块化 | 原生 | `<script type="module">` 浏览器原生支持，无需打包 |

**结论：保持零依赖。** 若未来确需 WebSocket（多用户并发场景），再评估引入 `websockets`；当前单用户本地场景 SSE 足够。

---

## 7. 共享知识（跨文件约定）

1. **缓存 key 命名规范**：`ih:<ns>:<fingerprint>`；`ns ∈ {invoices,companies,accounts,stats}`；`fingerprint = 稳定哈希(筛选条件 JSON)`。所有缓存读写必须经 `CacheStore`，禁止各页面自管 `sessionStorage`。
2. **Store 与 API 契约**：只读 API 统一返回可含 `version` 字段；响应头统一带 `X-Data-Version: N`。前端 `ApiClient.get` 把返回 `version` 写入缓存条目 `v`；后台重拉比较 `v` 与响应头 `version` 决定是否更新。
3. **数据版本单一真相源**：`DataVersion` 在 `db.py` 维护（内存 + `meta` 表持久化）。**任何写路径必须 `bump`**（集中在 db mutation 函数尾部最稳妥，覆盖 CLI/引擎/Web）。前端不做版本号自增，只读后端。
4. **连接池 WAL 线程安全约定**：每个线程独享自己的连接对象，绝不跨线程共享；WAL 多读单写由 `busy_timeout` 兜底；后台 engine 线程用自身连接。度量通过 `ConnectionPool.stats()` + `GET /api/debug/connpool`（`PERF=1` 启用）。
5. **缓存失效广播机制**：`ApiClient.post` 成功 → `cache.purge(ns)`（清内存+sessionStorage+manifest）→ 写 `localStorage['ih:invalidations']` + 派发 `ih:invalidate` → 其余 tab 经 `storage` 事件 purge 并按需后台刷新 → 轻提示（toast）。命名空间映射表（见下表）须在 `cache.js` 与 `api.js` 保持一致。

   | 写操作 | purge 的 ns |
   |--------|-------------|
   | 发票删除/上传/改归属/重新解析 | `invoices`, `stats` |
   | 公司 CRUD / 回填 | `companies`, `invoices`(归属变), `stats` |
   | 账号 CRUD | `accounts` |

6. **UI/UX 铁律**：缓存命中 → 先显快照 + 柔和「更新中」角标/顶部细进度条；**禁止全屏居中「加载中」遮罩**；仅首次无缓存用骨架屏；写成功立即失效相关缓存并轻提示；后台刷新失败保留并标注「显示的是 X 分钟前数据」。（对应 PRD UI/UX 要点）
7. **度量开关**：`PERF=1` 环境变量开启 `/api/debug/*` 与 `perf.js` 详细日志；默认关闭，零开销。

---

## 8. 待明确事项（需用户/主理人拍板）

1. **SPA 是否最终落地**（P1·E/F）：本设计默认「先 P0 见效，再评估 SPA」。是否确认走 SPA，还是 P0 达标后即停？→ 影响 `app.html`/`views/*` 投入。
2. **数据量级真实规模**：当前库内发票行数约多少？直接决定 `IN_MEMORY_CAP` 取 5 万还是更保守（如 1 万）；也决定 P1·F 是否必要。
3. **MPA 旧页面处置**：SPA 上线后，`invoices.html`/`companies.html`/`index.html` 是「加重定向兜底保留」还是「删除」？建议保留重定向兜底，降低回退风险。
4. **多 tab 必要性**：用户是否常用多 tab 同时开？若几乎单 tab，可简化 Q4 的 localStorage 协调层（仅内存+sessionStorage），进一步降复杂度。
5. **P2 优先级**：Service Worker / 预取 / SSE 是否都要，还是仅挑其一（如仅 SSE 推进度）？资源有限时建议优先 I(SSE) 提升抓取体感。
6. **移动端目标**：是否需要移动端适配？影响 P1·F 的 cap 降配与响应式工作量。

---

> 附：本设计可直接交工程师逐条实现；所有新增均为模块化文件、对现有逻辑「增量修改 + 保留兼容别名/函数」，不推翻重写，符合「零构建原生 JS、分阶段先 P0」约束。

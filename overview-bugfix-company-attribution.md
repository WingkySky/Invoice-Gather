# 修复：公司归属上线后「一堆报错 / 功能无法使用」

## 现象
浏览器控制台报错，核心一条：
- `POST http://localhost:8000/api/companies/import-from-invoices → net::ERR_EMPTY_RESPONSE`
- 连带 `TypeError: Failed to fetch`

（另两条 `chrome-extension://...` 是你的其他浏览器插件，与本项目无关。）

## 根因
后端 handler 抛未捕获异常 → Python `http.server` 直接关连接 → 浏览器收到空响应。

**1. 致命：`db.py` 顶部漏 `import json`**
`upsert_company` 用 `json.dumps(...)` 但从未 import json → 任何创建/更新公司都抛 `NameError` → 新增公司、从发票导入、回填全部空回。

**2. 更隐蔽的真实 bug：`upsert_company` 别名被空值覆盖**
```sql
ON CONFLICT(name) DO UPDATE SET aliases=excluded.aliases
```
用**空别名**重新 upsert 已存在公司（编辑留空 / 重名去重 / 从发票导入候选）会把已有别名清空成 `[]` → 快照读到空别名 → 归属匹配全部失效。这正是你真实库里发票归属不可靠的根子。

## 修复清单
| 文件 | 改动 |
|---|---|
| `db.py` | 补 `import json`(+traceback)；`upsert_company` 别名改为 `COALESCE(NULLIF(excluded.aliases,'[]'), companies.aliases)`（空别名不覆盖已有值）；`insert_invoice` 返回新行 id（已忽略返回 None，向后兼容）；`upsert_account` 补 `fetch_method` 默认值并返回账号对象；`import_companies_from_invoices` 单条失败不中止（收集 errors），返回 `{added,skipped,errors}` |
| `web/app.py` | `do_POST` 顶层 try/except 兜底：任何异常返回 500 JSON，不再空回连接 |
| `api.py` / `hub.py` | 透传新返回结构；`companies` 子命令 `--json` 友好 |
| `tests/test_company_attribution.py` | 端到端覆盖（临时库，不碰真实数据） |

## 验证
- 全部后端模块 `py_compile` 通过
- 端到端测试 **34 项全 PASS**（公司 CRUD / 别名子串匹配 / 歧义识别 / buyer_tax 回填 / 从发票导入 / 历史回填 / 批量改归属 / 按公司·状态过滤 / 概况统计 / CLI 全子命令）
- 重启后端后实测调用：
  - `POST /api/companies` → 200，`{"ok":true,...}`
  - `POST /api/companies/import-from-invoices` → 200（原先崩溃的端点，现已正常）
  - `GET /api/attribution/stats` → 200
- 你的真实库：21 张发票现已 **100% classified**（广州南沙友谊人才服务有限公司 11 / 广州市友谊对外服务有限公司 10）

## 部署提示
`start.bat` 指向系统 Python 3.14，缺 `requests/bs4/PyMuPDF`。建议改用 managed venv 启动：
```
D:/.../binaries/python/envs/default/Scripts/python hub.py serve --port 8000
```
（stop.bat 在 git-bash 下不生效，已手动 taskkill 旧进程。）

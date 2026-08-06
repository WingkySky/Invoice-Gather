# -*- coding: utf-8 -*-
"""QA 临时验证脚本（P0 回归）：合并查询正确性 + 连接复用 + DataVersion 持久化。
仅读取/轻量写入 meta 表，不污染 invoices 业务数据（用 data_version.bump 模拟一次写）。
"""
import os, sys, subprocess, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import db

PY = r"C:\Users\Ifesco\.workbuddy\binaries\python\versions\3.13.12\python.exe"

def rowset(rows):
    return {r["id"] for r in rows}

def compare(filter_desc, filters):
    m_rows, m_total = db.get_invoices_merged(filters, page=1, page_size=50)
    o_rows = db.get_invoices(filters, page=1, page_size=50)
    o_total = db.get_invoices_count(filters)
    ms, os_ = rowset(m_rows), rowset(o_rows)
    same_set = (ms == os_)
    same_total = (m_total == o_total)
    # 额外校验：merged 的 total 必须是全量筛选后总数（非当页行数）
    total_is_full = (m_total == o_total) and (m_total != len(m_rows) or m_total == 0 or len(m_rows) < 50)
    print(f"  [{filter_desc}] merged_rows={len(m_rows)} merged_total={m_total} | "
          f"old_rows={len(o_rows)} old_total={o_total} | set_match={same_set} total_match={same_total} total_is_full_count={total_is_full}")
    return same_set and same_total and total_is_full

print("===== 基础数据规模 =====")
base_rows, base_total = db.get_invoices_merged({}, page=1, page_size=50)
print(f"  全量 total={base_total}, 首页返回 {len(base_rows)} 行")

print("\n===== T-P0-D 合并查询 vs (旧 get_invoices + get_invoices_count) =====")
all_ok = True

# 1) 无筛选
all_ok &= compare("空筛选 {}", {})

# 发现真实可用的筛选值
sample = db.get_invoices({}, page=1, page_size=5)
# keyword：取一个真实 buyer 片段
kw = ""
if sample:
    b = sample[0].get("buyer") or sample[0].get("invoice_no") or ""
    kw = b[:3] if len(b) >= 3 else b
if kw:
    all_ok &= compare(f"keyword='{kw}'", {"keyword": kw})

# attribution_status：取库内存在的值
import sqlite3
c = db.conn()
statuses = [r[0] for r in c.execute("SELECT DISTINCT attribution_status FROM invoices WHERE attribution_status IS NOT NULL").fetchall()]
c.close()
for st in statuses[:2]:
    all_ok &= compare(f"attribution_status='{st}'", {"attribution_status": st})

# company_id：取一个非空 company_id
c = db.conn()
cid_row = c.execute("SELECT company_id FROM invoices WHERE company_id IS NOT NULL LIMIT 1").fetchone()
c.close()
if cid_row:
    cid = cid_row[0]
    all_ok &= compare(f"company_id={cid}", {"company_id": cid})

# amount_min：取中值
c = db.conn()
mx = c.execute("SELECT MAX(amount) FROM invoices WHERE amount IS NOT NULL").fetchone()[0]
c.close()
if mx:
    am = float(mx) / 2.0
    all_ok &= compare(f"amount_min={am}", {"amount_min": am})

# 2) 分页正确性：page=2&size=20，total 应为全量数（非 20）
print("\n===== T-P0-D 分页 total 正确性 (page=2,size=20) =====")
p2_rows, p2_total = db.get_invoices_merged({}, page=2, page_size=20)
print(f"  page2 total={p2_total} page2_rows={len(p2_rows)}  (total 应=全量 {base_total}，不应=当页行数)")
pagination_ok = (p2_total == base_total) and (len(p2_rows) == 20 or p2_total <= 20)
all_ok &= pagination_ok
print(f"  pagination_ok={pagination_ok}")

print("\n===== T-P0-C 连接线程级复用（同一线程多次 get_conn 应为同一对象） =====")
c1 = db.conn(); c2 = db.conn(); c3 = db.conn()
same_conn = (c1 is c2 is c3)
print(f"  c1 is c2 is c3 = {same_conn}")
# 验证 _PooledConnection.close() 不真正关闭：close 后仍能执行查询
try:
    c1.close()
    c1.execute("SELECT 1")
    close_noop = True
except Exception as e:
    close_noop = False
    print(f"  close 后查询异常: {e}")
print(f"  close() 为 no-op（仍可查询）={close_noop}")
all_ok &= (same_conn and close_noop)

print("\n===== 验收点5：DataVersion 持久化（bump 后新进程读取不归零） =====")
v0 = db.get_data_version()
print(f"  进程A 读取 version(v0)={v0}")
v1 = db.data_version.bump()
print(f"  进程A bump 后 version(v1)={v1}  期望={v0+1}")
bump_ok = (v1 == v0 + 1)

# 新进程读取（重新 import db，模拟重启）
sub = (
    "import sys,os; sys.path.insert(0, %r); import db; "
    "print('SUB_VERSION=' + str(db.get_data_version()))" % HERE
)
proc = subprocess.run([PY, "-c", sub], capture_output=True, text=True)
sub_out = proc.stdout.strip()
sub_ver = None
for line in sub_out.splitlines():
    if line.startswith("SUB_VERSION="):
        sub_ver = int(line.split("=")[1])
print(f"  进程B（新进程）读取 version={sub_ver}  期望={v1}")
persist_ok = (sub_ver == v1)
all_ok &= (bump_ok and persist_ok)
# 还原 version（把 meta 写回 v0，避免污染真实版本号）
db.data_version._ver = v0
try:
    cc = db.conn()
    cc.execute("UPDATE meta SET value=? WHERE key='data_version'", (v0,))
    cc.commit()
except Exception as e:
    print(f"  [warn] 还原 version 失败（不影响验证结论）: {e}")
print(f"  bump_ok={bump_ok} persist_ok={persist_ok} (已还原 version 至 {v0})")

print("\n===== 总体 =====")
print("ALL_OK =", all_ok)
sys.exit(0 if all_ok else 1)

"""
发票台账「统一搜索栏」专项测试。

验证 db._apply_filters 的 keyword 过滤确实命中 8 个字段：
  i.buyer / i.seller / i.invoice_no / i.city /
  a.name(邮箱名) / a.email(邮箱地址) / c.name(所属公司名) /
  CAST(i.amount AS TEXT)(金额文本子串)

同时验证 get_invoices_count / get_stats 已补齐 LEFT JOIN accounts a / companies c，
不再因命中 a.name 而报 `no such column: a.name`；并验证 company_id / date 区间过滤保留可用。

每个用例都做断言（不只跑通），且用临时目录隔离 DB，tearDown 还原模块级路径。
"""

import os
import sqlite3
import tempfile
import unittest

import db


class UnifiedSearchTest(unittest.TestCase):
    def setUp(self):
        # 用临时目录隔离 DB，避免污染真实 data/ 目录
        self.tmp = tempfile.mkdtemp()
        self._orig = (db.DATA_DIR, db.DB_PATH, db.PDF_DIR)
        db.DATA_DIR = self.tmp
        db.DB_PATH = os.path.join(self.tmp, "test.db")
        db.PDF_DIR = os.path.join(self.tmp, "pdfs")
        db.init()

        # 一个邮箱账号（三张发票都挂它）
        acc = db.upsert_account({
            "name": "腾讯邮箱", "email": "tencent@x.com", "password": "p",
            "imap_host": "h", "imap_port": 993, "use_ssl": 1,
            "folder": "INBOX", "enabled": 1,
        })
        self.acc_id = acc["id"]

        # 一个公司（用于验证 company_id 归属 + 公司名关键字命中）
        co = db.upsert_company({"name": "深圳某科技公司", "aliases": "[]"})
        self.co_id = co["id"]

        # 三张发票，覆盖不同字段值
        self.idA = self._insert({
            "buyer": "阿里巴巴", "seller": "携程", "amount": 100.0,
            "invoice_no": "INV100", "invoice_date": "2026-07-01", "city": "杭州",
        })
        self.idB = self._insert({
            "buyer": "字节跳动", "seller": "滴滴", "amount": 2100.5,
            "invoice_no": "INV200", "invoice_date": "2026-03-15", "city": "北京",
        })
        self.idC = self._insert({
            "buyer": "美团", "seller": "腾讯云", "amount": 50.25,
            "invoice_no": "INV300", "invoice_date": "2026-08-20", "city": "上海",
        })

        # insert_invoice 会按 buyer 自动重算 company_id（本例 buyer 均不命中公司，
        # 故 company_id 为 NULL）。按任务要求把 A/C 显式归属到 co_id。
        db.update_invoice_fields(self.idA, {"company_id": self.co_id})
        db.update_invoice_fields(self.idC, {"company_id": self.co_id})

    def tearDown(self):
        db.DATA_DIR, db.DB_PATH, db.PDF_DIR = self._orig

    # ---------------------------------------------------------------- helpers
    def _insert(self, overrides):
        """插入一张发票。insert_invoice 的 SQL 需要 remark / buyer_tax 两个绑定参数，
        这里统一补齐默认值，避免 ProgrammingError。"""
        inv = {
            "email_id": None,
            "account_id": self.acc_id,
            "buyer": "",
            "seller": "",
            "amount": 0.0,
            "invoice_no": "",
            "invoice_date": "",
            "city": "",
            "pdf_path": "",
            "source_type": "seed",
            "note": "",
            "remark": None,
            "buyer_tax": None,
        }
        inv.update(overrides)
        return db.insert_invoice(inv)

    @staticmethod
    def _ids(rows):
        return {r["id"] for r in rows}

    # ---------------------------------------------------------------- keyword 各字段命中
    def test_keyword_buyer(self):
        """keyword 应命中 i.buyer。"""
        ids = self._ids(db.get_invoices({"keyword": "阿里巴巴"}))
        self.assertEqual(ids, {self.idA})

    def test_keyword_seller(self):
        """keyword 应命中 i.seller（A 的携程、C 的腾讯云）。"""
        ids_a = self._ids(db.get_invoices({"keyword": "携程"}))
        self.assertEqual(ids_a, {self.idA})

        ids_c = self._ids(db.get_invoices({"keyword": "腾讯云"}))
        self.assertEqual(ids_c, {self.idC})

    def test_keyword_invoice_no(self):
        """keyword 应命中 i.invoice_no。"""
        ids = self._ids(db.get_invoices({"keyword": "INV200"}))
        self.assertEqual(ids, {self.idB})

    def test_keyword_city(self):
        """keyword 应命中 i.city。"""
        ids = self._ids(db.get_invoices({"keyword": "北京"}))
        self.assertEqual(ids, {self.idB})

    def test_keyword_account_name(self):
        """keyword 应命中 a.name（邮箱名）。三张发票同属一个账号，应全部命中。"""
        ids = self._ids(db.get_invoices({"keyword": "腾讯邮箱"}))
        self.assertEqual(ids, {self.idA, self.idB, self.idC})

    def test_keyword_account_email(self):
        """keyword 应命中 a.email（邮箱地址）。三张发票同账号，应全部命中。"""
        ids = self._ids(db.get_invoices({"keyword": "tencent@x.com"}))
        self.assertEqual(ids, {self.idA, self.idB, self.idC})

    def test_keyword_company_name(self):
        """keyword 应命中 c.name（所属公司名）。只命中 A/C（company_id=co_id），不命中 B。"""
        ids = self._ids(db.get_invoices({"keyword": "深圳某科技公司"}))
        self.assertEqual(ids, {self.idA, self.idC})

    def test_keyword_amount_numeric(self):
        """keyword 应命中 CAST(i.amount AS TEXT) 子串。
        100.0 -> '100.0' 含 '100'；2100.5 -> '2100.5' 含 '100'；50.25 -> '50.25' 不含 '100'。"""
        ids = self._ids(db.get_invoices({"keyword": "100"}))
        self.assertIn(self.idA, ids)
        self.assertIn(self.idB, ids)
        self.assertNotIn(self.idC, ids)
        self.assertEqual(ids, {self.idA, self.idB})

    def test_keyword_non_numeric_no_amount_error(self):
        """非数字 keyword 不能让 CAST(i.amount AS TEXT) 分支报错或误命中金额。

        注：任务原给的关键字 '阿里巴巴xyz' 是 buyer '阿里巴巴' 的【超串】，
        LIKE '%kw%' 要求 kw 是字段子串，故它实际命中 0 行；这里改用真正的非数字
        子串 '巴巴'（buyer '阿里巴巴' 的子串），既能命中发票A、又能验证金额分支
        不报错/不误命中（任何金额的 CAST 文本都不含 '巴巴'）。
        """
        ids = self._ids(db.get_invoices({"keyword": "巴巴"}))
        self.assertEqual(ids, {self.idA})

    # ---------------------------------------------------------------- count / stats JOIN 回归
    def test_count_and_stats_with_keyword_no_error(self):
        """get_invoices_count / get_stats 必须能带 keyword 且不抛异常（验证 JOIN 已补齐）。"""
        count = db.get_invoices_count({"keyword": "深圳某科技公司"})
        self.assertEqual(count, 2)

        stats = db.get_stats({"keyword": "深圳某科技公司"})
        self.assertEqual(stats["count"], 2)
        # A(100.0) + C(50.25) = 150.25
        self.assertAlmostEqual(stats["total"], 150.25, places=2)

    # ---------------------------------------------------------------- 其它过滤条件保留
    def test_company_id_filter(self):
        """company_id 过滤只返回 A/C。"""
        ids = self._ids(db.get_invoices({"company_id": self.co_id}))
        self.assertEqual(ids, {self.idA, self.idC})

    def test_date_range_filter(self):
        """date_from/date_to 区间只命中 7 月与 8 月的 A/C，不含 3 月的 B。"""
        ids = self._ids(db.get_invoices({
            "date_from": "2026-07-01", "date_to": "2026-12-31",
        }))
        self.assertEqual(ids, {self.idA, self.idC})


if __name__ == "__main__":
    unittest.main()

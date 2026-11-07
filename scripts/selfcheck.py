"""自检脚本：不依赖外部服务，可脱离 fnOS 运行。

用法：
    cd src && python3 ../scripts/selfcheck.py
    cd src && python3 -m unittest discover -s ../tests -v
"""
import os
import sqlite3
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

os.environ.setdefault("TRIM_PKGVAR", tempfile.mkdtemp(prefix="pms-var-"))
os.environ.setdefault("TRIM_PKGETC", tempfile.mkdtemp(prefix="pms-etc-"))
os.environ.setdefault("TRIM_APPDEST", tempfile.mkdtemp(prefix="pms-dest-"))

from db.connection import connect, migrate  # noqa: E402
from services import (due_calc, io_service, record_chain, stock_doc_service,  # noqa: E402
                      stock_service, supplier_service, wo_service)
from services.audit import canonical, sha256_hex  # noqa: E402


class DueCalcTest(unittest.TestCase):
    def test_compute_next_days(self):
        self.assertEqual(due_calc.compute_next("2026-01-31", 30, None, None)[0], "2026-03-02")

    def test_compute_next_hours(self):
        self.assertEqual(due_calc.compute_next(None, None, 1000.0, 250)[1], 1250.0)

    def test_status_overdue_by_date(self):
        state = due_calc.plan_state("2026-10-20", None, "2026-10-24", 0, 30, 100)
        self.assertEqual(state["status"], "overdue")
        self.assertEqual(state["days_left"], -4)

    def test_status_overdue_by_hours(self):
        state = due_calc.plan_state(None, 1200.0, "2026-10-24", 1250.0, 30, 100)
        self.assertEqual(state["status"], "overdue")
        self.assertEqual(state["driver"], "hours")

    def test_status_due_window(self):
        state = due_calc.plan_state("2026-11-10", None, "2026-10-24", 0, 30, 100)
        self.assertEqual(state["status"], "due")
        self.assertEqual(state["days_left"], 17)

    def test_status_ok_and_idle(self):
        self.assertEqual(due_calc.plan_state("2027-01-01", None, "2026-10-24", 0, 30, 100)["status"], "ok")
        self.assertEqual(due_calc.plan_state(None, None, "2026-10-24", 0, 30, 100)["status"], "idle")

    def test_leap_year(self):
        self.assertEqual(due_calc.compute_next("2028-02-01", 29, None, None)[0], "2028-03-01")


class SchemaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = connect(self.tmp.name)

    def tearDown(self):
        self.conn.close()
        os.unlink(self.tmp.name)

    def test_migrate_idempotent(self):
        first = migrate(self.conn)
        second = migrate(self.conn)
        self.assertTrue(first)
        self.assertEqual(second, [])
        version = self.conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()["v"]
        self.assertGreaterEqual(version, 1)

    def test_foreign_keys_on(self):
        self.assertEqual(self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_wal_mode(self):
        mode = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")


class StateMachineTest(unittest.TestCase):
    def test_workorder_transitions(self):
        self.assertTrue(wo_service.can_transition("open", "in_progress"))
        self.assertTrue(wo_service.can_transition("done", "verified"))
        self.assertTrue(wo_service.can_transition("done", "in_progress"))
        self.assertFalse(wo_service.can_transition("verified", "done"))
        self.assertFalse(wo_service.can_transition("cancelled", "open"))

    def test_record_transitions(self):
        self.assertTrue(record_chain.can_transition("draft", "submitted"))
        self.assertTrue(record_chain.can_transition("submitted", "verified"))
        self.assertFalse(record_chain.can_transition("verified", "draft"))
        self.assertFalse(record_chain.can_transition("verified", "submitted"))


class StockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = connect(self.tmp.name)
        migrate(self.conn)
        self.conn.execute(
            "INSERT INTO parts (code, name, unit, min_qty, on_hand, reserved)"
            " VALUES ('T-1', '测试件', 'PCS', 5, 10, 0)"
        )
        self.part_id = self.conn.execute("SELECT id FROM parts WHERE code='T-1'").fetchone()["id"]

    def tearDown(self):
        self.conn.close()
        os.unlink(self.tmp.name)

    def test_in_out_balance(self):
        stock_service.move(self.conn, self.part_id, "in", 5, None)
        stock_service.move(self.conn, self.part_id, "out", 3, None)
        part = stock_service.get(self.conn, self.part_id)
        self.assertEqual(part["on_hand"], 12)
        self.assertEqual(part["available"], 12)

    def test_no_negative_stock(self):
        with self.assertRaises(ValueError):
            stock_service.move(self.conn, self.part_id, "out", 99, None)
        self.assertEqual(stock_service.get(self.conn, self.part_id)["on_hand"], 10)

    def test_reserve_does_not_touch_on_hand(self):
        stock_service.move(self.conn, self.part_id, "reserve", 4, None)
        part = stock_service.get(self.conn, self.part_id)
        self.assertEqual(part["on_hand"], 10)
        self.assertEqual(part["available"], 6)

    def test_alert_threshold(self):
        self.assertFalse(stock_service.get(self.conn, self.part_id)["below_min"])
        stock_service.move(self.conn, self.part_id, "out", 6, None)
        self.assertTrue(stock_service.get(self.conn, self.part_id)["below_min"])


class StockDocTest(unittest.TestCase):
    """库存单据：入库 / 出库 / 盘库 的状态机与过账规则。"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = connect(self.tmp.name)
        migrate(self.conn)
        self.conn.execute(
            "INSERT INTO parts (code, name, unit, min_qty, on_hand, reserved, unit_price)"
            " VALUES ('T-1', '测试件', 'PCS', 5, 10, 0, 100)"
        )
        self.part_id = self.conn.execute("SELECT id FROM parts WHERE code='T-1'").fetchone()["id"]
        self.user = {"id": None, "username": "tester"}

    def tearDown(self):
        self.conn.close()
        os.unlink(self.tmp.name)

    def _doc(self, doc_type="in", qty=5, price=100, note=""):
        return stock_doc_service.create_doc(self.conn, doc_type, {
            "doc_date": "2026-10-24", "party": "测试供应商", "ref_no": "PO-1",
            "lines": [{"part_id": self.part_id, "qty": qty, "unit_price": price, "note": note}],
        }, self.user)

    def test_create_draft(self):
        doc = stock_doc_service.get_doc(self.conn, self._doc())
        self.assertEqual(doc["status"], "draft")
        self.assertTrue(doc["no"].startswith("RK-"))
        self.assertEqual(len(doc["lines"]), 1)
        self.assertEqual(doc["total_qty"], 5)
        self.assertEqual(doc["total_amount"], 500)

    def test_post_in_writes_move(self):
        doc_id = self._doc()
        stock_doc_service.post_doc(self.conn, doc_id, self.user)
        doc = stock_doc_service.get_doc(self.conn, doc_id)
        self.assertEqual(doc["status"], "posted")
        self.assertEqual(stock_service.get(self.conn, self.part_id)["on_hand"], 15)
        move = stock_service.moves(self.conn, self.part_id)[0]
        self.assertEqual(move["type"], "in")
        self.assertEqual(move["qty"], 5)
        self.assertEqual(move["ref_no"], doc["no"])

    def test_post_out_checks_available(self):
        stock_service.move(self.conn, self.part_id, "reserve", 8, None)  # 可用仅剩 2
        doc_id = self._doc("out", qty=5)
        with self.assertRaises(ValueError):
            stock_doc_service.post_doc(self.conn, doc_id, self.user)
        self.assertEqual(stock_service.get(self.conn, self.part_id)["on_hand"], 10)

    def test_post_out_ok(self):
        doc_id = self._doc("out", qty=4)
        stock_doc_service.post_doc(self.conn, doc_id, self.user)
        self.assertEqual(stock_service.get(self.conn, self.part_id)["on_hand"], 6)

    def test_adjust_requires_variance_note(self):
        doc_id = self._doc("adjust", qty=7)  # 差异 -3 但未填原因
        with self.assertRaises(ValueError):
            stock_doc_service.post_doc(self.conn, doc_id, self.user)

    def test_adjust_snapshots_book_and_variance(self):
        doc_id = self._doc("adjust", qty=7, note="破损报废 3 件")
        stock_doc_service.post_doc(self.conn, doc_id, self.user)
        line = stock_doc_service.get_doc(self.conn, doc_id)["lines"][0]
        self.assertEqual(line["book_qty"], 10)
        self.assertEqual(line["variance"], -3)
        self.assertEqual(stock_service.get(self.conn, self.part_id)["on_hand"], 7)

    def test_posted_doc_locked(self):
        doc_id = self._doc()
        stock_doc_service.post_doc(self.conn, doc_id, self.user)
        with self.assertRaises(ValueError):
            stock_doc_service.post_doc(self.conn, doc_id, self.user)
        with self.assertRaises(ValueError):
            stock_doc_service.cancel_doc(self.conn, doc_id, self.user)
        with self.assertRaises(ValueError):
            stock_doc_service.update_doc(self.conn, doc_id, {"lines": []}, self.user)

    def test_cancel_draft_keeps_stock(self):
        doc_id = self._doc()
        stock_doc_service.cancel_doc(self.conn, doc_id, self.user)
        self.assertEqual(stock_doc_service.get_doc(self.conn, doc_id)["status"], "cancelled")
        self.assertEqual(stock_service.get(self.conn, self.part_id)["on_hand"], 10)

    def test_doc_no_monthly_sequence(self):
        first = stock_doc_service.get_doc(self.conn, self._doc())
        second = stock_doc_service.get_doc(self.conn, self._doc())
        seq1 = int(first["no"].rsplit("-", 1)[1])
        seq2 = int(second["no"].rsplit("-", 1)[1])
        self.assertEqual(seq2, seq1 + 1)

    def test_stocktake_draft_prefills_book(self):
        doc = stock_doc_service.get_doc(
            self.conn, stock_doc_service.stocktake_draft(self.conn, user=self.user))
        self.assertEqual(doc["type"], "adjust")
        self.assertEqual(doc["lines"][0]["qty"], 10)

    def test_reorder_suggestion(self):
        self.assertEqual(stock_service.reorder_rows(self.conn), [])
        self.conn.execute("UPDATE parts SET on_hand = 2 WHERE id = ?", (self.part_id,))  # 剩 2 < 最低 5
        rows = stock_service.reorder_rows(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["suggested"], 8)  # max(2×5−2, 0)

    def test_validation_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            stock_doc_service.create_doc(self.conn, "in", {"lines": []}, self.user)
        with self.assertRaises(ValueError):
            stock_doc_service.create_doc(self.conn, "bad", {"lines": [
                {"part_id": self.part_id, "qty": 1}]}, self.user)
        with self.assertRaises(ValueError):
            stock_doc_service.create_doc(self.conn, "in", {"lines": [
                {"part_id": self.part_id, "qty": 0}]}, self.user)


class SupplierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = connect(self.tmp.name)
        migrate(self.conn)
        self.conn.execute("INSERT INTO parts (code, name) VALUES ('T-1', '测试件')")
        self.part_id = self.conn.execute("SELECT id FROM parts WHERE code='T-1'").fetchone()["id"]

    def tearDown(self):
        self.conn.close()
        os.unlink(self.tmp.name)

    def test_referenced_supplier_cannot_delete(self):
        sid = supplier_service.create(self.conn, {"name": "测试供应商"}, None)
        self.conn.execute("UPDATE parts SET supplier_id = ? WHERE id = ?", (sid, self.part_id))
        with self.assertRaises(ValueError):
            supplier_service.delete(self.conn, sid, None)
        self.assertEqual(len(supplier_service.list_suppliers(self.conn)), 1)
        # 解除引用后可以删除
        self.conn.execute("UPDATE parts SET supplier_id = NULL WHERE id = ?", (self.part_id,))
        supplier_service.delete(self.conn, sid, None)
        self.assertEqual(supplier_service.list_suppliers(self.conn), [])


class RecordChainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = connect(self.tmp.name)
        migrate(self.conn)
        self.conn.execute(
            "INSERT INTO record_books (code, title, regulation_ref, entry_types_json)"
            " VALUES ('T-BOOK', '测试簿', 'test', '[]')"
        )
        self.conn.execute(
            "INSERT INTO users (id, username, display_name, role, created_at)"
            " VALUES (1, 'tester', '测试', 'chief', '2026-10-24T00:00:00Z')"
        )
        self.book_id = self.conn.execute("SELECT id FROM record_books WHERE code='T-BOOK'").fetchone()["id"]

    def tearDown(self):
        self.conn.close()
        os.unlink(self.tmp.name)

    def _append(self, qty):
        return record_chain.append_entry(
            self.conn, self.book_id, "测试", "2026-10-24T02:00:00Z", {"qty": qty}, 1
        )

    def test_chain_ok(self):
        self._append(1)
        self._append(2)
        self.assertTrue(record_chain.verify_book(self.conn, self.book_id)["ok"])

    def test_tamper_detected(self):
        first = self._append(1)
        self._append(2)
        self.conn.execute("UPDATE record_entries SET particulars_json='{\"qty\":9}' WHERE id=?", (first["id"],))
        result = record_chain.verify_book(self.conn, self.book_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["first_bad_seq"], 1)

    def test_prev_hash_links(self):
        first = self._append(1)
        second = self._append(2)
        row = self.conn.execute(
            "SELECT prev_hash FROM record_entries WHERE id=?", (second["id"],)
        ).fetchone()
        self.assertEqual(row["prev_hash"], first["hash"])

    def test_amendment_keeps_original(self):
        first = self._append(1)
        self.conn.execute("UPDATE record_entries SET status='verified' WHERE id=?", (first["id"],))
        amended = record_chain.append_entry(
            self.conn, self.book_id, "测试", "2026-10-24T02:00:00Z", {"qty": 1, "note": "更正"}, 1,
            amends_entry_id=first["id"],
        )
        self.conn.execute("UPDATE record_entries SET status='amended' WHERE id=?", (first["id"],))
        original = self.conn.execute("SELECT * FROM record_entries WHERE id=?", (first["id"],)).fetchone()
        self.assertEqual(original["status"], "amended")
        new_row = self.conn.execute("SELECT * FROM record_entries WHERE id=?", (amended["id"],)).fetchone()
        self.assertEqual(new_row["amends_entry_id"], first["id"])
        # 内容不可变：原条目的 particulars 未被改写
        self.assertEqual(original["particulars_json"], canonical({"qty": 1}))
        self.assertTrue(record_chain.verify_book(self.conn, self.book_id)["ok"])

    def test_hash_deterministic(self):
        payload = {"b": 2, "a": 1}
        self.assertEqual(canonical(payload), canonical({"a": 1, "b": 2}))
        self.assertEqual(sha256_hex("x" + canonical(payload)), sha256_hex("x" + canonical({"a": 1, "b": 2})))


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = connect(self.tmp.name)
        migrate(self.conn)
        self.conn.execute(
            "INSERT INTO assets (code, name, category, criticality, created_at)"
            " VALUES (?,?,?,?,?)",
            ("A-1", "测试设备", "machinery", "B", "2026-10-24T00:00:00Z"),
        )
        self.conn.execute(
            "INSERT INTO maintenance_plans (asset_id, code, title, interval_days, est_hours,"
            " checklist_json, required_spares_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (1, "P-1", "测试计划", 30, 2.0, '["a", "b"]', "[]", "2026-10-24T00:00:00Z"),
        )

    def tearDown(self):
        self.conn.close()
        os.unlink(self.tmp.name)

    def test_same_handles_cross_type(self):
        self.assertTrue(io_service._same(1, True))
        self.assertTrue(io_service._same(1, 1.0))
        self.assertTrue(io_service._same("是", True))
        self.assertTrue(io_service._same("30", 30))
        self.assertFalse(io_service._same(30, 45))

    def test_export_then_import_is_idempotent(self):
        rows, cols = io_service.export_rows(self.conn, "plans")
        result = io_service.preview(self.conn, "plans", rows)
        self.assertEqual(result["summary"]["update"], 0)
        self.assertEqual(result["summary"]["error"], 0)
        self.assertEqual(result["summary"]["skip"], 1)

    def test_change_detected(self):
        rows, _ = io_service.export_rows(self.conn, "plans")
        rows[0]["日历间隔(天)"] = "45"
        result = io_service.preview(self.conn, "plans", rows)
        self.assertEqual(result["summary"]["update"], 1)
        changed = [x for x in result["rows"] if x["action"] == "update"][0]
        self.assertEqual(changed["changes"][0][0], "日历间隔(天)")

    def test_invalid_value_reports_error_and_skips(self):
        rows = [{"计划编码": "P-1", "设备编码": "A-1", "计划名称": "测试计划", "日历间隔(天)": "abc"}]
        result = io_service.preview(self.conn, "plans", rows)
        self.assertEqual(result["summary"]["error"], 1)
        self.assertEqual(result["summary"]["update"], 0)
        self.assertTrue(result["rows"][0]["errors"])

    def test_unknown_asset_rejected(self):
        rows = [{"计划编码": "P-1", "设备编码": "NOPE", "计划名称": "测试计划"}]
        result = io_service.preview(self.conn, "plans", rows)
        self.assertEqual(result["summary"]["error"], 1)
        self.assertIn("设备编码不存在", result["rows"][0]["errors"][0])

    def test_checklist_roundtrip(self):
        rows, _ = io_service.export_rows(self.conn, "plans")
        self.assertEqual(rows[0]["检查项"], "a；b")
        result = io_service.preview(self.conn, "plans", rows)
        self.assertEqual(result["summary"]["update"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

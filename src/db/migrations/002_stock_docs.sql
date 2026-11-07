-- v1.2.0 备件管理增强：供应商台账、库存单据（入库/出库/盘库）、备件档案扩充
-- 幂等由 schema_migrations 保证；parts 加列使用 ALTER TABLE，老数据无损。

CREATE TABLE IF NOT EXISTS suppliers (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  contact    TEXT NOT NULL DEFAULT '',
  phone      TEXT NOT NULL DEFAULT '',
  email      TEXT NOT NULL DEFAULT '',
  address    TEXT NOT NULL DEFAULT '',
  remarks    TEXT NOT NULL DEFAULT '',
  active     INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

-- 库存单据头：in=入库 / out=出库 / adjust=盘库；draft 可编辑，posted 锁定
CREATE TABLE IF NOT EXISTS stock_docs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  no           TEXT NOT NULL UNIQUE,
  type         TEXT NOT NULL CHECK (type IN ('in','out','adjust')),
  status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','cancelled')),
  doc_date     TEXT NOT NULL,
  party        TEXT NOT NULL DEFAULT '',
  ref_no       TEXT NOT NULL DEFAULT '',
  wo_id        INTEGER REFERENCES work_orders(id),
  note         TEXT NOT NULL DEFAULT '',
  total_qty    REAL NOT NULL DEFAULT 0,
  total_amount REAL NOT NULL DEFAULT 0,
  created_by   INTEGER REFERENCES users(id),
  created_at   TEXT NOT NULL,
  posted_by    INTEGER REFERENCES users(id),
  posted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_type_status ON stock_docs(type, status, doc_date);
CREATE INDEX IF NOT EXISTS idx_docs_wo ON stock_docs(wo_id);

-- 库存单据行：qty 对盘库单表示实盘数；book_qty/variance 在过账时快照
CREATE TABLE IF NOT EXISTS stock_doc_lines (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id     INTEGER NOT NULL REFERENCES stock_docs(id) ON DELETE CASCADE,
  part_id    INTEGER NOT NULL REFERENCES parts(id),
  qty        REAL NOT NULL,
  unit_price REAL NOT NULL DEFAULT 0,
  book_qty   REAL,
  variance   REAL,
  note       TEXT NOT NULL DEFAULT '',
  seq        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_doc_lines_doc ON stock_doc_lines(doc_id);

-- 备件档案扩充：常用供应商、保质期到期日（润滑油/橡胶/滤芯类）
ALTER TABLE parts ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id);
ALTER TABLE parts ADD COLUMN expiry_date TEXT;

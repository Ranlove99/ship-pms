-- 船舶 PMS · 初始 schema
-- 约定：时间戳为 UTC ISO8601（YYYY-MM-DDTHH:MM:SSZ）；仅日期字段用 YYYY-MM-DD

CREATE TABLE vessel (
  id              INTEGER PRIMARY KEY CHECK (id = 1),
  name            TEXT NOT NULL DEFAULT '',
  imo             TEXT NOT NULL DEFAULT '',
  call_sign       TEXT NOT NULL DEFAULT '',
  flag            TEXT NOT NULL DEFAULT '',
  port_of_registry TEXT NOT NULL DEFAULT '',
  gt              REAL NOT NULL DEFAULT 0,
  ship_type       TEXT NOT NULL DEFAULT '散货船',
  class_society   TEXT NOT NULL DEFAULT '',
  owner           TEXT NOT NULL DEFAULT '',
  manager         TEXT NOT NULL DEFAULT '',
  timezone        TEXT NOT NULL DEFAULT 'Asia/Shanghai',
  updated_at      TEXT NOT NULL
);

CREATE TABLE users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  display_name  TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('admin','master','chief','officer','crew')),
  password_hash TEXT,
  fnos_uid      TEXT,
  active        INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  last_login_at TEXT
);
CREATE INDEX idx_users_fnos ON users(fnos_uid);

CREATE TABLE assets (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  parent_id         INTEGER REFERENCES assets(id) ON DELETE RESTRICT,
  code              TEXT NOT NULL UNIQUE,
  name              TEXT NOT NULL,
  category          TEXT NOT NULL DEFAULT 'machinery',
  criticality       TEXT NOT NULL DEFAULT 'B' CHECK (criticality IN ('A','B','C')),
  maker             TEXT NOT NULL DEFAULT '',
  model             TEXT NOT NULL DEFAULT '',
  serial_no         TEXT NOT NULL DEFAULT '',
  location          TEXT NOT NULL DEFAULT '',
  install_date      TEXT NOT NULL DEFAULT '',
  running_hours     REAL NOT NULL DEFAULT 0,
  running_hours_at  TEXT,
  status            TEXT NOT NULL DEFAULT 'in_service'
                    CHECK (status IN ('in_service','standby','out_of_service','disposed')),
  notes             TEXT NOT NULL DEFAULT '',
  created_at        TEXT NOT NULL
);
CREATE INDEX idx_assets_parent ON assets(parent_id);

CREATE TABLE parts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  code          TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  spec          TEXT NOT NULL DEFAULT '',
  unit          TEXT NOT NULL DEFAULT 'PCS',
  maker_part_no TEXT NOT NULL DEFAULT '',
  location      TEXT NOT NULL DEFAULT '',
  min_qty       REAL NOT NULL DEFAULT 0,
  on_hand       REAL NOT NULL DEFAULT 0,
  reserved      REAL NOT NULL DEFAULT 0,
  unit_price    REAL NOT NULL DEFAULT 0,
  currency      TEXT NOT NULL DEFAULT 'CNY',
  critical      INTEGER NOT NULL DEFAULT 0,
  remarks       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE maintenance_plans (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id             INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  code                 TEXT NOT NULL,
  title                TEXT NOT NULL,
  interval_days        INTEGER,
  interval_hours       REAL,
  last_done_at         TEXT,
  last_done_hours      REAL,
  next_due_at          TEXT,
  next_due_hours       REAL,
  checklist_json       TEXT NOT NULL DEFAULT '[]',
  required_spares_json TEXT NOT NULL DEFAULT '[]',
  est_hours            REAL NOT NULL DEFAULT 0,
  responsible_role     TEXT NOT NULL DEFAULT 'officer',
  regulation_ref       TEXT NOT NULL DEFAULT '',
  active               INTEGER NOT NULL DEFAULT 1,
  created_at           TEXT NOT NULL
);
CREATE INDEX idx_plans_asset ON maintenance_plans(asset_id);
CREATE INDEX idx_plans_due ON maintenance_plans(next_due_at);

CREATE TABLE work_orders (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  no                    TEXT NOT NULL UNIQUE,
  asset_id              INTEGER NOT NULL REFERENCES assets(id),
  plan_id               INTEGER REFERENCES maintenance_plans(id),
  type                  TEXT NOT NULL DEFAULT 'planned'
                        CHECK (type IN ('planned','corrective','defect','inspection')),
  priority              TEXT NOT NULL DEFAULT 'normal'
                        CHECK (priority IN ('low','normal','high','critical')),
  status                TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open','in_progress','done','verified','cancelled')),
  title                 TEXT NOT NULL,
  description           TEXT NOT NULL DEFAULT '',
  due_at                TEXT,
  started_at            TEXT,
  completed_at          TEXT,
  completed_by          INTEGER REFERENCES users(id),
  verified_by           INTEGER REFERENCES users(id),
  verified_at           TEXT,
  running_hours_at_done REAL,
  man_hours             REAL,
  remarks               TEXT NOT NULL DEFAULT '',
  created_by            INTEGER REFERENCES users(id),
  created_at            TEXT NOT NULL
);
CREATE INDEX idx_wo_status ON work_orders(status);
CREATE INDEX idx_wo_asset ON work_orders(asset_id);
CREATE INDEX idx_wo_due ON work_orders(due_at);

CREATE TABLE wo_checklist_items (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  wo_id    INTEGER NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
  seq      INTEGER NOT NULL,
  text     TEXT NOT NULL,
  done     INTEGER NOT NULL DEFAULT 0,
  done_at  TEXT,
  done_by  INTEGER REFERENCES users(id),
  remark   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE wo_spares (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  wo_id   INTEGER NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
  part_id INTEGER NOT NULL REFERENCES parts(id),
  qty     REAL NOT NULL,
  action  TEXT NOT NULL CHECK (action IN ('reserve','issue','release'))
);

CREATE TABLE defects (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  no                TEXT NOT NULL UNIQUE,
  asset_id          INTEGER REFERENCES assets(id),
  found_at          TEXT NOT NULL,
  found_by          INTEGER REFERENCES users(id),
  severity          TEXT NOT NULL DEFAULT 'minor'
                    CHECK (severity IN ('minor','major','critical')),
  description       TEXT NOT NULL,
  root_cause        TEXT NOT NULL DEFAULT '',
  status            TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open','in_progress','fixed','closed')),
  wo_id             INTEGER REFERENCES work_orders(id),
  corrective_action TEXT NOT NULL DEFAULT '',
  closed_at         TEXT,
  closed_by         INTEGER REFERENCES users(id),
  created_at        TEXT NOT NULL
);

CREATE TABLE stock_moves (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  part_id  INTEGER NOT NULL REFERENCES parts(id),
  type     TEXT NOT NULL CHECK (type IN ('in','out','adjust','reserve','release')),
  qty      REAL NOT NULL,
  wo_id    INTEGER REFERENCES work_orders(id),
  ref_no   TEXT NOT NULL DEFAULT '',
  operator INTEGER REFERENCES users(id),
  at       TEXT NOT NULL,
  note     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_moves_part ON stock_moves(part_id, at);

CREATE TABLE certificates (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  category      TEXT NOT NULL DEFAULT 'statutory'
                CHECK (category IN ('statutory','class','other')),
  cert_no       TEXT NOT NULL DEFAULT '',
  issuer        TEXT NOT NULL DEFAULT '',
  issued_at     TEXT,
  expires_at    TEXT,
  reminder_days INTEGER NOT NULL DEFAULT 60,
  file_path     TEXT NOT NULL DEFAULT '',
  status        TEXT NOT NULL DEFAULT 'valid'
                CHECK (status IN ('valid','expired','superseded')),
  remarks       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE record_books (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  code             TEXT NOT NULL UNIQUE,
  title            TEXT NOT NULL,
  regulation_ref   TEXT NOT NULL DEFAULT '',
  entry_types_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE record_entries (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id           INTEGER NOT NULL REFERENCES record_books(id),
  seq               INTEGER NOT NULL,
  occurred_at_utc   TEXT NOT NULL,
  entry_type        TEXT NOT NULL,
  particulars_json  TEXT NOT NULL DEFAULT '{}',
  status            TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','submitted','verified','amended')),
  officer_id        INTEGER REFERENCES users(id),
  officer_signed_at TEXT,
  master_id         INTEGER REFERENCES users(id),
  master_verified_at TEXT,
  amends_entry_id   INTEGER REFERENCES record_entries(id),
  hash              TEXT NOT NULL,
  prev_hash         TEXT NOT NULL,
  created_at        TEXT NOT NULL
);
CREATE INDEX idx_entries_book ON record_entries(book_id, seq);

CREATE TABLE audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  at_utc      TEXT NOT NULL,
  user_id     INTEGER,
  username    TEXT NOT NULL DEFAULT '',
  action      TEXT NOT NULL,
  entity      TEXT NOT NULL DEFAULT '',
  entity_id   TEXT NOT NULL DEFAULT '',
  before_json TEXT,
  after_json  TEXT,
  ip          TEXT NOT NULL DEFAULT '',
  hash        TEXT NOT NULL,
  prev_hash   TEXT NOT NULL
);
CREATE INDEX idx_audit_at ON audit_log(at_utc);

CREATE TABLE attachments (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  entity      TEXT NOT NULL,
  entity_id   TEXT NOT NULL,
  path        TEXT NOT NULL,
  mime        TEXT NOT NULL DEFAULT '',
  size        INTEGER NOT NULL DEFAULT 0,
  sha256      TEXT NOT NULL DEFAULT '',
  uploaded_by INTEGER,
  uploaded_at TEXT NOT NULL
);
CREATE INDEX idx_att ON attachments(entity, entity_id);

CREATE TABLE settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT INTO vessel (id, name, updated_at) VALUES (1, '', strftime('%Y-%m-%dT%H:%M:%SZ','now'));

INSERT INTO settings (key, value) VALUES
  ('schema_version', '1'),
  ('due_warn_days', '30'),
  ('cert_warn_days', '60'),
  ('backup_keep', '30'),
  ('hours_warn', '100');

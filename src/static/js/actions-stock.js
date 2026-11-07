/* 库存单据交互：入库 / 出库 / 盘库 单据的新建、编辑、过账、取消；供应商管理 */
(function () {
  "use strict";
  const PMS = window.PMS;

  const TYPE_LABEL = { in: "入库", out: "出库", adjust: "盘库" };
  const PARTY_LABEL = { in: "供应商", out: "领用人 / 部门", adjust: "盘点范围" };
  const REF_LABEL = { in: "采购 / 送货单号", out: "用途 / 去向", adjust: "引用单号" };

  function jsonData(id) {
    const el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : [];
  }

  function partsOptions(docType, selectedId) {
    const parts = jsonData("partsData");
    let html = '<option value="">选择备件…</option>';
    parts.forEach(function (p) {
      const hint = docType === "adjust"
        ? "账面 " + p.on_hand + " " + p.unit
        : "可用 " + p.available + " " + p.unit;
      html += '<option value="' + p.id + '"' + (String(selectedId) === String(p.id) ? " selected" : "") +
        ">" + PMS.esc(p.code + " · " + p.name + "（" + hint + "）") + "</option>";
    });
    return html;
  }

  function lineRowHtml(docType, line) {
    line = line || {};
    const priceCell = docType === "adjust" ? "" :
      '<input type="number" name="unit_price" min="0" step="0.01" value="' + (line.unit_price || 0) +
      '" placeholder="单价" aria-label="单价">';
    return (
      '<div class="line-row">' +
      '<select name="part_id" aria-label="备件">' + partsOptions(docType, line.part_id) + "</select>" +
      '<input type="number" name="qty" min="0" step="0.1" value="' + (line.qty !== undefined ? line.qty : "") +
      '" placeholder="' + (docType === "adjust" ? "实盘数" : "数量") + '" aria-label="数量" required>' +
      priceCell +
      '<input type="text" name="note" value="' + PMS.esc(line.note || "") + '" placeholder="行备注' +
      (docType === "adjust" ? "（差异必填）" : "") + '" aria-label="行备注">' +
      '<button type="button" class="btn ghost sm line-del" data-line-del aria-label="删除本行">' +
      '<svg class="icon icon-sm"><use href="#i-x"/></svg></button>' +
      "</div>"
    );
  }

  function renderLines(host, docType, lines) {
    host.innerHTML = "";
    if (!lines || !lines.length) {
      host.innerHTML = '<div class="empty-rows">还没有明细行，点击下方「添加一行」。</div>';
      return;
    }
    lines.forEach(function (line) {
      host.insertAdjacentHTML("beforeend", lineRowHtml(docType, line));
    });
  }

  function collectLines(host) {
    const lines = [];
    host.querySelectorAll(".line-row").forEach(function (row) {
      const partId = row.querySelector("select[name=part_id]").value;
      const qty = row.querySelector("input[name=qty]").value;
      const price = row.querySelector("input[name=unit_price]");
      const note = row.querySelector("input[name=note]").value;
      if (!partId && qty === "" && !note) return;
      lines.push({
        part_id: Number(partId),
        qty: Number(qty),
        unit_price: price ? Number(price || 0) : 0,
        note: note,
      });
    });
    return lines;
  }

  function openDocModal(docType, doc) {
    doc = doc || null;
    const editing = !!doc;
    const linesHost = "docLines";
    PMS.modal(
      (editing ? "编辑" : "新建") + TYPE_LABEL[docType] + "单",
      '<div class="form-grid">' +
      '<div class="field"><label>业务日期</label><input type="date" name="doc_date" value="' +
      PMS.esc(doc ? doc.doc_date : PMS.today()) + '"></div>' +
      '<div class="field"><label>' + PARTY_LABEL[docType] + '</label><input type="text" name="party" value="' +
      PMS.esc(doc ? doc.party : "") + '" placeholder="' +
      (docType === "in" ? "供货商名称" : docType === "out" ? "领用部门或人员" : "如：全库 / A 区") + '"></div>' +
      '<div class="field"><label>' + REF_LABEL[docType] + '</label><input type="text" name="ref_no" value="' +
      PMS.esc(doc ? doc.ref_no : "") + '" placeholder="采购单号 / 送货单号等"></div>' +
      (docType === "out"
        ? '<div class="field"><label>关联工单</label><select name="wo_id">' +
          '<option value="">不关联</option>' +
          jsonData("openWosData").map(function (w) {
            return '<option value="' + w.id + '"' + (doc && doc.wo_id === w.id ? " selected" : "") +
              ">" + PMS.esc(w.no + " · " + w.title + "（" + (w.asset_name || "") + "）") + "</option>";
          }).join("") + "</select></div>"
        : "") +
      '<div class="field full"><label>单据备注</label><textarea name="note" placeholder="整体说明，可空">' +
      PMS.esc(doc ? doc.note : "") + "</textarea></div>" +
      '<div class="field full"><label>明细行' +
      (docType === "adjust" ? "（数量填实盘数）" : "") + '</label>' +
      '<div class="line-rows" id="' + linesHost + '"></div>' +
      '<button type="button" class="btn ghost sm" id="docLineAdd" style="margin-top:8px">' +
      '<svg class="icon icon-sm"><use href="#i-plus"/></svg>添加一行</button></div>' +
      "</div>",
      '<button class="btn" data-close>取消</button>' +
      '<button class="btn primary" id="docSave">保存草稿</button>',
      { wide: true }
    );
    renderLines(document.getElementById(linesHost), docType,
      doc ? doc.lines.map(function (l) {
        return { part_id: l.part_id, qty: l.qty, unit_price: l.unit_price, note: l.note };
      }) : [null]);
    document.getElementById("docLineAdd").onclick = function () {
      const host = document.getElementById(linesHost);
      const empty = host.querySelector(".empty-rows");
      if (empty) empty.remove();
      host.insertAdjacentHTML("beforeend", lineRowHtml(docType, null));
    };
    document.getElementById("docSave").onclick = async function () {
      const form = PMS.currentModal.querySelector(".modal-body");
      const data = PMS.formValues(form);
      const lines = collectLines(document.getElementById(linesHost));
      if (!lines.length) { PMS.toast("至少填写一行明细", "warn"); return; }
      for (const line of lines) {
        if (!line.part_id) { PMS.toast("有明细行未选择备件", "warn"); return; }
        if (line.qty === null || isNaN(line.qty) || line.qty < 0) {
          PMS.toast("数量必须为不小于 0 的数字", "warn"); return;
        }
      }
      data.lines = lines;
      const ok = await PMS.run(function () {
        return editing
          ? PMS.api("api/v1/stock-docs/" + doc.id, "PATCH", data)
          : PMS.api("api/v1/stock-docs", "POST", Object.assign({ type: docType }, data));
      }, editing ? "草稿已保存" : "单据已创建");
      if (ok) {
        PMS.closeModal();
        if (editing) PMS.reload();
        else location.href = PMS.url("stock-docs/" + (ok.id || ""));
      }
    };
  }

  const A = (PMS.actions = PMS.actions || {});

  A["doc-new"] = function (el) { openDocModal(el.dataset.type, null); };
  A["doc-edit"] = function (el) {
    openDocModal(jsonData("docData").type, jsonData("docData"));
  };

  A["doc-post"] = async function (el) {
    if (!confirm("确认过账 " + el.dataset.no + "？过账后将写入库存流水，不可撤销。")) return;
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/stock-docs/" + el.dataset.id + "/post", "POST", {});
    }, "已过账");
    if (ok) PMS.reload();
  };

  A["doc-cancel"] = async function (el) {
    if (!confirm("确认取消 " + el.dataset.no + "？取消后不产生库存变动。")) return;
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/stock-docs/" + el.dataset.id + "/cancel", "POST", {});
    }, "单据已取消");
    if (ok) PMS.reload();
  };

  A["stocktake-new"] = function () {
    PMS.modal("新建盘库单", '<div class="form-grid">' +
      '<div class="field full"><label>盘点范围</label><select name="scope">' +
      '<option value="all">全部备件</option>' +
      '<option value="location">按存放位置筛选</option></select></div>' +
      '<div class="field full" id="locField" style="display:none"><label>位置关键字</label>' +
      '<input type="text" name="location" placeholder="如：A 区 / 机舱 / 甲板库"></div>' +
      '<div class="field full"><span class="hint">系统按范围生成草稿，实盘数预填当前账面数；' +
      "只修改有差异的行，差异行过账时必须填写原因。</span></div>" +
      "</div>",
      '<button class="btn" data-close>取消</button>' +
      '<button class="btn primary" id="stocktakeGo">生成草稿</button>');
    const scope = PMS.currentModal.querySelector("select[name=scope]");
    scope.onchange = function () {
      PMS.currentModal.querySelector("#locField").style.display =
        scope.value === "location" ? "" : "none";
    };
    document.getElementById("stocktakeGo").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      const payload = data.scope === "location"
        ? { location: (data.location || "").trim() }
        : { all: true };
      if (payload.location === "") { PMS.toast("请填写位置关键字", "warn"); return; }
      const ok = await PMS.run(function () {
        return PMS.api("api/v1/stock-docs/stocktake-draft", "POST", payload);
      }, "盘点草稿已生成");
      if (ok && ok.id) location.href = PMS.url("stock-docs/" + ok.id);
    };
  };

  /* ---------- 供应商 ---------- */
  function supplierModal(supplier) {
    const s = supplier || {};
    PMS.modal(supplier ? "编辑供应商" : "新增供应商", '<div class="form-grid">' +
      '<div class="field"><label>名称 <span class="req">*</span></label>' +
      '<input type="text" name="name" value="' + PMS.esc(s.name || "") + '" required></div>' +
      '<div class="field"><label>联系人</label>' +
      '<input type="text" name="contact" value="' + PMS.esc(s.contact || "") + '"></div>' +
      '<div class="field"><label>电话</label>' +
      '<input type="text" name="phone" value="' + PMS.esc(s.phone || "") + '"></div>' +
      '<div class="field"><label>邮箱</label>' +
      '<input type="text" name="email" value="' + PMS.esc(s.email || "") + '"></div>' +
      '<div class="field full"><label>地址</label>' +
      '<input type="text" name="address" value="' + PMS.esc(s.address || "") + '"></div>' +
      '<div class="field full"><label>备注</label>' +
      '<textarea name="remarks">' + PMS.esc(s.remarks || "") + "</textarea></div>" +
      "</div>",
      '<button class="btn" data-close>取消</button>' +
      '<button class="btn primary" id="supplierSave">保存</button>');
    document.getElementById("supplierSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      if (!data.name || !data.name.trim()) { PMS.toast("请填写供应商名称", "warn"); return; }
      const ok = await PMS.run(function () {
        return supplier
          ? PMS.api("api/v1/suppliers/" + supplier.id, "PATCH", data)
          : PMS.api("api/v1/suppliers", "POST", data);
      }, supplier ? "供应商已更新" : "供应商已创建");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  }

  A["supplier-new"] = function () { supplierModal(null); };
  A["supplier-edit"] = function (el) {
    supplierModal(JSON.parse(el.dataset.supplier));
  };
  A["supplier-delete"] = async function (el) {
    const supplier = JSON.parse(el.dataset.supplier);
    if (!confirm("删除供应商「" + supplier.name + "」？被备件引用的供应商不能删除。")) return;
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/suppliers/" + supplier.id, "DELETE", {});
    }, "供应商已删除");
    if (ok) PMS.reload();
  };

  document.addEventListener("click", function (e) {
    const del = e.target.closest("[data-line-del]");
    if (del) {
      const host = del.closest(".line-rows");
      del.closest(".line-row").remove();
      if (host && !host.querySelector(".line-row")) {
        host.innerHTML = '<div class="empty-rows">还没有明细行，点击上方「添加一行」。</div>';
      }
      return;
    }
    const el = e.target.closest("[data-action]");
    if (!el) return;
    const fn = A[el.dataset.action];
    if (!fn) return;
    e.preventDefault();
    fn(el);
  });
})();

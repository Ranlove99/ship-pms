/* 备件台账域交互：新增 / 编辑 / 快捷库存操作 */
/* 依赖 PMS.field / PMS.select（由 actions-maintenance.js 提供），须在其后加载 */
(function () {
  "use strict";
  const PMS = window.PMS;

  function body(html) { return '<div class="form-grid">' + html + "</div>"; }
  function field(label, name, value, opts) { return PMS.field(label, name, value, opts); }
  function select(label, name, items, valueKey, labelKey, selected, full) {
    return PMS.select(label, name, items, valueKey, labelKey, selected, full);
  }
  function supplierOptions(picked) {
    const suppliers = [{ id: "", name: "— 不指定 —" }].concat(
      JSON.parse(document.getElementById("suppliersData").textContent));
    return select("常用供应商", "supplier_id", suppliers, "id", "name", picked || "", true);
  }

  const A = {};

  /* ---------- 备件台账 ---------- */
  A["part-new"] = function () {
    PMS.modal("新增备件", body(
      field("备件编码", "code", "", { required: true }) +
      field("名称", "name", "", { required: true }) +
      field("规格型号", "spec", "") +
      field("单位", "unit", "PCS") +
      field("最低库存", "min_qty", "0", { type: "number", step: "0.1" }) +
      field("初始在库", "on_hand", "0", { type: "number", step: "0.1" }) +
      field("单价", "unit_price", "0", { type: "number", step: "0.01" }) +
      field("存放位置", "location", "") +
      supplierOptions("") +
      field("保质期到期日", "expiry_date", "", { type: "date", hint: "润滑油、橡胶、滤芯类建议填写" }) +
      '<div class="field full"><label class="check"><input type="checkbox" name="critical"> 关键备件（缺货影响安全）</label></div>'
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="partSave">保存</button>', { wide: true });
    document.getElementById("partSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      const ok = await PMS.run(function () { return PMS.api("api/v1/parts", "POST", data); }, "备件已创建");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  A["part-edit"] = function (el) {
    const parts = JSON.parse(document.getElementById("partsData").textContent);
    const p = parts.find(function (item) { return item.id === Number(el.dataset.id); }) || {};
    PMS.modal("编辑备件 · " + (p.name || ""), body(
      field("备件编码", "code", p.code, { required: true }) +
      field("名称", "name", p.name, { required: true }) +
      field("规格型号", "spec", p.spec || "") +
      field("单位", "unit", p.unit || "PCS") +
      field("厂家件号", "maker_part_no", p.maker_part_no || "") +
      field("存放位置", "location", p.location || "") +
      field("最低库存", "min_qty", p.min_qty, { type: "number", step: "0.1" }) +
      field("单价", "unit_price", p.unit_price, { type: "number", step: "0.01" }) +
      supplierOptions(p.supplier_id || "") +
      field("保质期到期日", "expiry_date", p.expiry_date || "", { type: "date",
        hint: "润滑油、橡胶、滤芯类建议填写" }) +
      '<div class="field full"><label class="check"><input type="checkbox" name="critical"' +
      (p.critical ? " checked" : "") + "> 关键备件（缺货影响安全）</label></div>" +
      field("备注", "remarks", p.remarks || "", { type: "textarea", full: true })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="partEditSave">保存</button>',
      { wide: true });
    document.getElementById("partEditSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      if (!data.code || !data.code.trim() || !data.name || !data.name.trim()) {
        PMS.toast("备件编码与名称必填", "warn"); return;
      }
      const ok = await PMS.run(function () {
        return PMS.api("api/v1/parts/" + el.dataset.id, "PATCH", data);
      }, "备件已更新");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  /* ---------- 快捷库存操作（单据化之外的轻量通道） ---------- */
  A["part-move"] = function (el) {
    const type = el.dataset.type;
    const label = { in: "入库", out: "出库", adjust: "盘点" }[type] || "库存操作";
    PMS.modal(label + " · " + el.dataset.name, body(
      field("数量", "qty", type === "adjust" ? el.dataset.onhand : "", { type: "number", step: "0.1", required: true,
        hint: type === "adjust" ? "填写盘点后的实际在库数" : "" }) +
      field("单据号 / 来源", "ref_no", "") +
      field("备注", "note", "", { type: "textarea", full: true })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="moveSave">确认</button>');
    document.getElementById("moveSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      data.type = type;
      const ok = await PMS.run(function () {
        return PMS.api("api/v1/parts/" + el.dataset.id + "/moves", "POST", data);
      }, "库存已更新");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  document.addEventListener("click", function (e) {
    const el = e.target.closest("[data-action]");
    if (!el) return;
    const fn = A[el.dataset.action];
    if (!fn) return;
    e.preventDefault();
    fn(el);
  });

  PMS.actions = Object.assign(PMS.actions || {}, A);
})();

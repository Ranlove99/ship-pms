/* 维护域交互：工单、缺陷、计划、备件、资产 */
(function () {
  "use strict";
  const PMS = window.PMS;

  function body(html) { return '<div class="form-grid">' + html + "</div>"; }

  function field(label, name, value, opts) {
    opts = opts || {};
    const type = opts.type || "text";
    const req = opts.required ? ' <span class="req">*</span>' : "";
    if (type === "textarea") {
      return '<div class="field' + (opts.full ? " full" : "") + '"><label>' + label + req +
        '</label><textarea name="' + name + '" placeholder="' + (opts.ph || "") + '">' +
        PMS.esc(value || "") + "</textarea></div>";
    }
    return '<div class="field' + (opts.full ? " full" : "") + '"><label>' + label + req +
      '</label><input type="' + type + '" name="' + name + '" value="' + PMS.esc(value === undefined || value === null ? "" : value) +
      '" placeholder="' + (opts.ph || "") + '"' + (opts.step ? ' step="' + opts.step + '"' : "") + ">" +
      (opts.hint ? '<span class="hint">' + opts.hint + "</span>" : "") + "</div>";
  }

  PMS.field = field;

  function select(label, name, items, valueKey, labelKey, selected, full) {
    return '<div class="field' + (full ? " full" : "") + '"><label>' + label + '</label><select name="' +
      name + '">' + PMS.opt(items, valueKey, labelKey, selected) + "</select></div>";
  }

  PMS.select = select;

  const A = {};

  /* ---------- 工单 ---------- */
  A["wo-start"] = async function (el) {
    await PMS.run(function () { return PMS.api("api/v1/workorders/" + el.dataset.id + "/start", "POST", {}); }, "已开始执行");
    PMS.reload();
  };

  A["wo-complete"] = function (el) {
    const hours = el.dataset.hours || "";
    PMS.modal("提交完成", body(
      field("完成时运行小时", "running_hours_at_done", hours, { type: "number", step: "0.1", hint: "作为下次到期的小时基准" }) +
      field("工时（人·小时）", "man_hours", "", { type: "number", step: "0.5" }) +
      field("执行说明 / 发现的问题", "remarks", "", { type: "textarea", full: true })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="woCompleteSave">提交完成</button>');
    document.getElementById("woCompleteSave").onclick = async function () {
      const form = PMS.currentModal.querySelector(".modal-body");
      const data = PMS.formValues(form);
      const ok = await PMS.run(function () {
        return PMS.api("api/v1/workorders/" + el.dataset.id + "/complete", "POST", data);
      }, "已提交，等待验收");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  A["wo-verify"] = async function (el) {
    if (!confirm("确认验收该工单？验收后将写入设备历史并顺延维护计划，不可再修改。")) return;
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/workorders/" + el.dataset.id + "/verify", "POST", {});
    }, "已验收");
    if (ok) PMS.reload();
  };

  A["wo-cancel"] = function (el) {
    PMS.modal("取消工单", body(field("取消原因", "reason", "", { type: "textarea", full: true, required: true })),
      '<button class="btn" data-close>返回</button><button class="btn danger" id="woCancelSave">确认取消</button>');
    document.getElementById("woCancelSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      const ok = await PMS.run(function () {
        return PMS.api("api/v1/workorders/" + el.dataset.id + "/cancel", "POST", data);
      }, "工单已取消");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  A["check-toggle"] = async function (el) {
    const done = el.checked;
    const result = await PMS.run(function () {
      return PMS.api("api/v1/workorders/" + el.dataset.wo + "/checklist/" + el.dataset.item, "PATCH", { done: done });
    });
    if (result) {
      const row = el.closest(".check-row");
      if (row) row.classList.toggle("done", done);
      const bar = document.getElementById("checkProgress");
      if (bar) {
        const all = document.querySelectorAll(".check-row input[type=checkbox]");
        const n = document.querySelectorAll(".check-row input[type=checkbox]:checked").length;
        bar.style.width = (all.length ? (n / all.length) * 100 : 0) + "%";
        const txt = document.getElementById("checkProgressText");
        if (txt) txt.textContent = n + " / " + all.length;
      }
    } else {
      el.checked = !done;
    }
  };

  A["wo-add-spare"] = function (el) {
    const parts = JSON.parse(document.getElementById("partsData").textContent);
    PMS.modal("工单领料", body(
      '<div class="field full"><label>备件</label><select name="part_id">' +
      parts.map(function (p) {
        return '<option value="' + p.id + '">' + PMS.esc(p.code + " · " + p.name + "（可用 " + p.available + " " + p.unit + "）") + "</option>";
      }).join("") + "</select></div>" +
      field("数量", "qty", "1", { type: "number", step: "0.1", required: true })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="spareSave">确认领用</button>');
    document.getElementById("spareSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      const ok = await PMS.run(function () {
        return PMS.api("api/v1/workorders/" + el.dataset.id + "/spares", "POST", data);
      }, "已领用并扣减库存");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  /* ---------- 缺陷 ---------- */
  A["defect-new"] = function () {
    const assets = JSON.parse(document.getElementById("assetsData").textContent);
    PMS.modal("报告缺陷", body(
      select("关联设备", "asset_id", assets, "id", "label", "", true) +
      '<div class="field"><label>严重度</label><select name="severity">' +
      '<option value="minor">轻微</option><option value="major">重要</option>' +
      '<option value="critical">严重</option></select></div>' +
      field("缺陷描述", "description", "", { type: "textarea", full: true, required: true, ph: "现象、部位、发现时间" })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="defectSave">提交</button>');
    document.getElementById("defectSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      if (!data.asset_id) delete data.asset_id;
      const ok = await PMS.run(function () { return PMS.api("api/v1/defects", "POST", data); }, "缺陷已记录");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  A["defect-to-wo"] = async function (el) {
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/defects/" + el.dataset.id + "/to-workorder", "POST", {});
    }, "已生成工单");
    if (ok) PMS.reload();
  };

  A["defect-close"] = function (el) {
    PMS.modal("关闭缺陷", body(
      field("纠正措施", "corrective_action", "", { type: "textarea", full: true, required: true, ph: "做了什么、更换了什么、如何验证有效" })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="defectCloseSave">确认关闭</button>');
    document.getElementById("defectCloseSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      const ok = await PMS.run(function () {
        return PMS.api("api/v1/defects/" + el.dataset.id + "/close", "POST", data);
      }, "缺陷已关闭");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  /* ---------- 计划 ---------- */
  A["plan-new"] = function () {
    const assets = JSON.parse(document.getElementById("assetsData").textContent);
    PMS.modal("新建维护计划", body(
      select("设备", "asset_id", assets, "id", "label", "", true) +
      field("计划名称", "title", "", { required: true, ph: "例：主机 1000 小时检查" }) +
      field("日历间隔（天）", "interval_days", "", { type: "number" }) +
      field("运行小时间隔（h）", "interval_hours", "", { type: "number", step: "1" }) +
      field("预计工时", "est_hours", "", { type: "number", step: "0.5" }) +
      field("法规 / 手册依据", "regulation_ref", "", { ph: "例：SOLAS III/20" }) +
      field("检查项（每行一项）", "checklist", "", { type: "textarea", full: true })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="planSave">保存</button>', { wide: true });
    document.getElementById("planSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      data.checklist = (data.checklist || "").split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
      const ok = await PMS.run(function () { return PMS.api("api/v1/plans", "POST", data); }, "计划已创建");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  A["plan-toggle"] = async function (el) {
    const active = el.dataset.active === "1";
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/plans/" + el.dataset.id, "PATCH", { active: !active });
    }, active ? "已停用" : "已启用");
    if (ok) PMS.reload();
  };

  /* ---------- 到期派工 ---------- */
  A["due-generate"] = async function () {
    const ids = Array.from(document.querySelectorAll(".due-check:checked")).map(function (el) { return Number(el.value); });
    if (!ids.length) { PMS.toast("请先勾选到期项", "warn"); return; }
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/due/generate", "POST", { plan_ids: ids });
    }, "已生成工单");
    if (ok) PMS.reload();
  };

  A["due-generate-one"] = async function (el) {
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/due/generate", "POST", { plan_ids: [Number(el.dataset.id)] });
    }, "已生成工单");
    if (ok) PMS.reload();
  };

  /* ---------- 资产 ---------- */
  A["hours-update"] = function (el) {
    PMS.modal("更新运行小时 · " + el.dataset.name, body(
      field("当前运行小时", "running_hours", el.dataset.hours, { type: "number", step: "0.1", required: true })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="hoursSave">保存</button>');
    document.getElementById("hoursSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      const ok = await PMS.run(function () {
        return PMS.api("api/v1/assets/" + el.dataset.id + "/hours", "POST", data);
      }, "运行小时已更新");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  A["asset-new"] = function () {
    const assets = JSON.parse(document.getElementById("assetsData").textContent);
    PMS.modal("新增设备", body(
      field("设备编码", "code", "", { required: true, ph: "例：ME-07" }) +
      field("设备名称", "name", "", { required: true }) +
      select("上级设备", "parent_id", assets, "id", "label", "", false) +
      '<div class="field"><label>类别</label><select name="category">' +
      '<option value="machinery">轮机</option><option value="deck">甲板机械</option>' +
      '<option value="electrical">电气</option><option value="safety">安全与消防</option>' +
      '<option value="navigation">导航通信</option><option value="cargo">货物系统</option>' +
      '<option value="hull">船体结构</option><option value="other">其他</option></select></div>' +
      '<div class="field"><label>关键度</label><select name="criticality">' +
      '<option value="A">A 级 · 关键</option><option value="B" selected>B 级 · 重要</option>' +
      '<option value="C">C 级 · 一般</option></select></div>' +
      field("厂家", "maker", "") + field("型号", "model", "") +
      field("序列号", "serial_no", "") + field("位置", "location", "") +
      field("运行小时", "running_hours", "0", { type: "number", step: "0.1" })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="assetSave">保存</button>', { wide: true });
    document.getElementById("assetSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      if (!data.parent_id) delete data.parent_id;
      const ok = await PMS.run(function () { return PMS.api("api/v1/assets", "POST", data); }, "设备已创建");
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

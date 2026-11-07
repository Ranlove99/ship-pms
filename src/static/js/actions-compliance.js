/* 合规与系统交互：证书、电子记录簿、用户、设置、备份 */
(function () {
  "use strict";
  const PMS = window.PMS;
  const field = PMS.field;
  const select = PMS.select;

  function body(html) { return '<div class="form-grid">' + html + "</div>"; }

  /* 各记录簿按类型定义字段：[key, label, type, unit] */
  const BOOK_FIELDS = {
    "OIL-REC-I": {
      "燃油加装": [["fuel", "油品名称/牌号", "text"], ["qty", "数量", "number", "m³"], ["tank", "受油舱柜", "text"], ["place", "加油地点", "text"], ["supplier", "供应方", "text"]],
      "滑油加装": [["oil", "油品名称", "text"], ["qty", "数量", "number", "L"], ["tank", "舱柜", "text"], ["place", "地点", "text"]],
      "舱底水排放": [["qty", "排放量", "number", "m³"], ["position", "排放位置（经纬度）", "text"], ["speed", "航速", "number", "kn"], ["rate", "排放速率", "number", "m³/h"], ["method", "处理方式", "text"]],
      "油渣处理": [["qty", "数量", "number", "m³"], ["method", "处理方式", "text"], ["facility", "接收设施", "text"]],
      "含油污水排放": [["qty", "排放量", "number", "m³"], ["position", "位置", "text"], ["device", "处理装置状态", "text"]],
      "设备异常": [["device", "设备", "text"], ["phenomenon", "现象", "textarea"], ["action", "处置", "textarea"]]
    },
    "GARBAGE": {
      "食品废弃物排海": [["qty", "数量", "number", "m³"], ["position", "位置", "text"], ["distance", "距最近陆地", "number", "n mile"]],
      "塑料/生活废弃物": [["category", "类别", "text"], ["qty", "数量", "number", "m³"], ["store", "存放位置", "text"]],
      "焚烧": [["category", "类别", "text"], ["qty", "数量", "number", "kg"], ["duration", "焚烧时长", "number", "h"]],
      "排岸接收": [["category", "类别", "text"], ["qty", "数量", "number", "m³"], ["facility", "接收设施", "text"], ["receipt", "接收单号", "text"]],
      "货物残余": [["cargo", "货物名称", "text"], ["qty", "数量", "number", "m³"], ["position", "位置", "text"]]
    },
    "BALLAST": {
      "压载水吸入": [["tank", "舱柜", "text"], ["qty", "数量", "number", "m³"], ["position", "吸入位置", "text"], ["treated", "是否经处理", "text"]],
      "压载水排放": [["tank", "舱柜", "text"], ["qty", "数量", "number", "m³"], ["position", "排放位置", "text"], ["method", "处理方式", "text"]],
      "压载水置换": [["tank", "舱柜", "text"], ["method", "置换方法", "text"], ["qty", "置换量", "number", "m³"], ["position", "位置", "text"]],
      "处理系统异常": [["device", "设备", "text"], ["phenomenon", "现象", "textarea"], ["action", "处置", "textarea"]],
      "排岸接收": [["qty", "数量", "number", "m³"], ["facility", "接收设施", "text"]]
    },
    "ODS": {
      "制冷剂加装": [["device", "设备", "text"], ["type", "制冷剂类型", "text"], ["qty", "数量", "number", "kg"]],
      "制冷剂回收": [["device", "设备", "text"], ["type", "制冷剂类型", "text"], ["qty", "数量", "number", "kg"]],
      "设备检修": [["device", "设备", "text"], ["content", "检修内容", "textarea"]],
      "泄漏": [["device", "设备", "text"], ["type", "类型", "text"], ["qty", "估计泄漏量", "number", "kg"], ["action", "处置", "textarea"]]
    }
  };

  function fieldsFor(bookCode, entryType) {
    const defs = (BOOK_FIELDS[bookCode] || {})[entryType] || [["remark", "说明", "textarea"]];
    return defs.map(function (d) {
      const hint = d[3] ? "单位：" + d[3] : "";
      if (d[2] === "textarea") {
        return '<div class="field full"><label>' + d[1] + "</label><textarea name=\"p_" + d[0] + '"></textarea></div>';
      }
      return '<div class="field"><label>' + d[1] + '</label><input type="' + d[2] + '" name="p_' + d[0] + '"' +
        (d[2] === "number" ? ' step="0.01"' : "") + ">" + (hint ? '<span class="hint">' + hint + "</span>" : "") + "</div>";
    }).join("");
  }

  function collectParticulars(root) {
    const out = {};
    root.querySelectorAll("[name^='p_']").forEach(function (el) {
      const key = el.name.slice(2);
      if (el.value !== "") out[key] = el.type === "number" ? Number(el.value) : el.value;
    });
    return out;
  }

  const A = {};

  /* ---------- 证书 ---------- */
  A["cert-new"] = function () {
    PMS.modal("新增证书 / 检验", body(
      field("名称", "name", "", { required: true }) +
      '<div class="field"><label>类别</label><select name="category">' +
      '<option value="statutory">法定</option><option value="class">船级社</option>' +
      '<option value="other">其他</option></select></div>' +
      field("证书号", "cert_no", "") +
      field("签发机构", "issuer", "") +
      field("签发日期", "issued_at", "", { type: "date" }) +
      field("到期日期", "expires_at", "", { type: "date" }) +
      field("提前提醒（天）", "reminder_days", "60", { type: "number" })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="certSave">保存</button>');
    document.getElementById("certSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      const ok = await PMS.run(function () { return PMS.api("api/v1/certificates", "POST", data); }, "证书已保存");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  /* ---------- 记录簿 ---------- */
  A["record-add"] = function (el) {
    const bookCode = el.dataset.book;
    const types = JSON.parse(document.getElementById("bookTypes").textContent);
    const options = types.map(function (t) { return '<option value="' + PMS.esc(t) + '">' + PMS.esc(t) + "</option>"; }).join("");
    PMS.modal("新增记录", body(
      '<div class="field"><label>记录类型</label><select name="entry_type" id="entryType">' + options + "</select></div>" +
      '<div class="field"><label>发生时间（船时）</label><input type="datetime-local" name="occurred_local" value="' + PMS.nowLocal() + '"></div>' +
      '<div class="full" id="entryFields"></div>'
    ) + '<div id="entryExtra"></div>',
      '<button class="btn" data-close>取消</button><button class="btn primary" id="recordSave">保存为草稿</button>' +
      '<button class="btn" id="recordSaveSubmit">保存并提交核签</button>', { wide: true });

    const typeSel = document.getElementById("entryType");
    const host = document.getElementById("entryFields");
    function render() {
      host.innerHTML = '<div class="form-grid">' + fieldsFor(bookCode, typeSel.value) + "</div>";
    }
    typeSel.addEventListener("change", render);
    render();

    async function save(submit) {
      const root = PMS.currentModal.querySelector(".modal-body");
      const values = PMS.formValues(root);
      const payload = {
        entry_type: values.entry_type,
        occurred_local: values.occurred_local,
        particulars: collectParticulars(root)
      };
      if (!Object.keys(payload.particulars).length) { PMS.toast("请至少填写一项内容", "warn"); return; }
      const res = await PMS.run(function () {
        return PMS.api("api/v1/recordbooks/" + bookCode + "/entries", "POST", payload);
      }, "记录已保存");
      if (!res) return;
      if (submit && res.id) {
        await PMS.run(function () {
          return PMS.api("api/v1/recordbooks/entries/" + res.id + "/submit", "POST", {});
        }, "已提交，等待船长核签");
      }
      PMS.closeModal();
      PMS.reload();
    }

    document.getElementById("recordSave").onclick = function () { save(false); };
    document.getElementById("recordSaveSubmit").onclick = function () { save(true); };
  };

  A["record-submit"] = async function (el) {
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/recordbooks/entries/" + el.dataset.id + "/submit", "POST", {});
    }, "已提交核签");
    if (ok) PMS.reload();
  };

  A["record-verify"] = async function (el) {
    if (!confirm("确认核签该条记录？核签后内容锁定，只能通过更正流程修改。")) return;
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/recordbooks/entries/" + el.dataset.id + "/verify", "POST", {});
    }, "已核签并写入哈希链");
    if (ok) PMS.reload();
  };

  A["record-amend"] = function (el) {
    PMS.modal("更正记录", body(
      field("更正原因", "reason", "", { type: "textarea", full: true, required: true, ph: "说明为何更正，将一并留痕" }) +
      field("补充 / 修正内容（JSON 键值）", "extra", "", { type: "textarea", full: true, ph: '{"qty": 12.5}' })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="amendSave">生成更正条目</button>');
    document.getElementById("amendSave").onclick = async function () {
      const values = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      let particulars = {};
      if (values.extra) {
        try { particulars = JSON.parse(values.extra); } catch (e) { PMS.toast("内容不是合法 JSON", "error"); return; }
      }
      const ok = await PMS.run(function () {
        return PMS.api("api/v1/recordbooks/entries/" + el.dataset.id + "/amend", "POST",
          { reason: values.reason, particulars: particulars });
      }, "已生成更正条目");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  /* ---------- 系统 ---------- */
  A["user-new"] = function () {
    PMS.modal("新增用户", body(
      field("登录账号", "username", "", { required: true }) +
      field("显示姓名", "display_name", "") +
      '<div class="field"><label>角色</label><select name="role">' +
      '<option value="crew">普通船员</option><option value="officer">轮机员/驾驶员</option>' +
      '<option value="chief">轮机长</option><option value="master">船长</option>' +
      '<option value="admin">系统管理员</option></select></div>' +
      field("初始密码", "password", "", { type: "password", required: true, hint: "至少 8 位" })
    ), '<button class="btn" data-close>取消</button><button class="btn primary" id="userSave">创建</button>');
    document.getElementById("userSave").onclick = async function () {
      const data = PMS.formValues(PMS.currentModal.querySelector(".modal-body"));
      const ok = await PMS.run(function () { return PMS.api("api/v1/users", "POST", data); }, "用户已创建");
      if (ok) { PMS.closeModal(); PMS.reload(); }
    };
  };

  A["save-vessel"] = async function () {
    const form = document.getElementById("vesselForm");
    const values = PMS.formValues(form);
    values.gt = Number(values.gt || 0);
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/settings", "PUT", { vessel: values });
    }, "船舶信息已保存");
    if (ok) PMS.reload();
  };

  A["save-settings"] = async function () {
    const values = PMS.formValues(document.getElementById("thresholdForm"));
    const ok = await PMS.run(function () {
      return PMS.api("api/v1/settings", "PUT", { settings: values });
    }, "阈值已保存");
    if (ok) PMS.reload();
  };

  A["backup-run"] = async function () {
    const res = await PMS.run(function () { return PMS.api("api/v1/backup/run", "POST", {}); }, "备份完成");
    if (res) PMS.reload(600);
  };

  A["integrity-check"] = async function () {
    const res = await PMS.run(function () { return PMS.api("api/v1/integrity/verify", "POST", {}); });
    if (!res) return;
    const records = res.records.books.map(function (b) {
      return b.title + "：" + (b.ok ? "链完整（" + b.checked + " 条）" : "断链于第 " + b.first_bad_seq + " 条");
    }).join("\n");
    PMS.modal("完整性校验结果",
      '<div class="notice ' + (res.ok ? "" : "danger") + '"><b>' + (res.ok ? "全部通过" : "发现异常") + "</b>" +
      "数据库：" + (res.database.ok ? "完好" : "异常") +
      "；审计链：" + (res.audit.ok ? "完整（" + res.audit.checked + " 条）" : "断链") + "</div>" +
      '<pre style="background:var(--paper);color:var(--ink-700);border:1px solid var(--line);padding:12px;font-size:11.5px;white-space:pre-wrap">' +
      PMS.esc(records) + "</pre>",
      '<button class="btn" data-close>关闭</button>');
  };

  document.addEventListener("click", function (e) {
    const el = e.target.closest("[data-action]");
    if (!el) return;
    const fn = A[el.dataset.action];
    if (!fn) return;
    e.preventDefault();
    fn(el);
  });
})();

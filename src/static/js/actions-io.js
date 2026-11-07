/* 批量导入导出的交互：选文件 → 预检 → 确认 */
(function () {
  "use strict";
  const PMS = window.PMS;

  const ACTION_LABEL = {
    update: ["更新", "warn"],
    create: ["新增", "ok"],
    skip: ["跳过", "neutral"],
    unchanged: ["无变化", "neutral"],
    error: ["错误", "danger"]
  };

  async function upload(kind, file, dryRun, createMissing) {
    const form = new FormData();
    form.append("file", file);
    const url = PMS.url(
      "api/v1/io/import/" + kind +
      "?dry_run=" + (dryRun ? "1" : "0") +
      "&create_missing=" + (createMissing ? "1" : "0")
    );
    const res = await fetch(url, {
      method: "POST",
      body: form,
      credentials: "same-origin",
      headers: { "X-Requested-With": "fetch" }
    });
    const data = await res.json().catch(function () { return null; });
    if (!res.ok) throw new Error((data && data.message) || ("上传失败 " + res.status));
    return data;
  }

  function changeText(changes) {
    if (!changes || !changes.length) return "—";
    return changes.slice(0, 3).map(function (c) {
      if (c[0] === "检查项" && Array.isArray(c[1]) && Array.isArray(c[2])) {
        return "检查项: " + c[1].length + " 项 → " + c[2].length + " 项";
      }
      const from = c[1] === null || c[1] === "" ? "空" : c[1];
      const to = c[2] === null || c[2] === "" ? "空" : c[2];
      return c[0] + ": " + from + " → " + to;
    }).join("；") + (changes.length > 3 ? "（共 " + changes.length + " 项）" : "");
  }

  function renderPreview(data) {
    const s = data.summary;
    const rows = data.rows || [];
    const shown = rows.filter(function (r) { return r.action !== "unchanged"; });
    const head =
      '<div class="import-sum">' +
      '<span class="badge ok">更新 ' + s.update + "</span>" +
      '<span class="badge info">新增 ' + s.create + "</span>" +
      '<span class="badge neutral">跳过 ' + s.skip + "</span>" +
      '<span class="badge ' + (s.error ? "danger" : "neutral") + '">错误 ' + s.error + "</span>" +
      "</div>";

    if (!shown.length) {
      return head + '<div class="empty" style="margin-top:12px">没有需要变更的行</div>';
    }

    const limit = 60;
    const slice = shown.slice(0, limit);
    let html = head + '<div class="table-wrap" style="max-height:320px;overflow:auto;margin-top:12px">' +
      '<table class="tbl"><thead><tr><th style="width:52px">行</th><th style="width:140px">匹配键</th>' +
      '<th style="width:76px">动作</th><th>变更</th></tr></thead><tbody>';
    slice.forEach(function (r) {
      const meta = ACTION_LABEL[r.action] || [r.action, "neutral"];
      const detail = r.errors && r.errors.length
        ? '<span style="color:var(--danger)">' + PMS.esc(r.errors.join("；")) + "</span>"
        : PMS.esc(changeText(r.changes));
      html += "<tr><td class=\"mono\">" + r.line + "</td><td class=\"mono\">" + PMS.esc(r.key) +
        '</td><td><span class="badge ' + meta[1] + '">' + meta[0] + "</span></td><td>" + detail + "</td></tr>";
    });
    html += "</tbody></table></div>";
    if (shown.length > limit) {
      html += '<div class="hint" style="margin-top:8px">仅显示前 ' + limit + " 行，共 " + shown.length + " 行有变更</div>";
    }
    return html;
  }

  function openImport(el) {
    const kind = el.dataset.kind;
    const label = el.dataset.label;
    PMS.modal("导入 · " + label,
      '<div class="form-grid">' +
      '<div class="field full"><label>选择 CSV 文件</label>' +
      '<input type="file" id="ioFile" accept=".csv,text/csv">' +
      '<span class="hint">先用「导出」取得现有数据再改；或下载模板从空白开始。Excel 另存为「CSV UTF-8」。</span></div>' +
      '<div class="field full"><label class="check"><input type="checkbox" id="ioCreate"> 新增未匹配的记录</label></div>' +
      "</div><div id=\"ioPreview\"></div>",
      '<a class="btn" href="' + PMS.url("api/v1/io/template/" + kind + ".csv") + '">下载模板</a>' +
      '<button class="btn" data-close>取消</button>' +
      '<button class="btn" id="ioCheck">检查文件</button>' +
      '<button class="btn primary" id="ioCommit" disabled>确认导入</button>',
      { wide: true });

    const fileInput = document.getElementById("ioFile");
    const createBox = document.getElementById("ioCreate");
    const previewBox = document.getElementById("ioPreview");
    const commitBtn = document.getElementById("ioCommit");
    let staged = null;

    document.getElementById("ioCheck").onclick = async function () {
      const file = fileInput.files[0];
      if (!file) { PMS.toast("请先选择文件", "warn"); return; }
      previewBox.innerHTML = '<div class="empty" style="margin-top:12px">检查中…</div>';
      commitBtn.disabled = true;
      try {
        const data = await upload(kind, file, true, createBox.checked);
        staged = file;
        previewBox.innerHTML = renderPreview(data);
        const s = data.summary;
        commitBtn.disabled = (s.update + s.create) === 0;
        if (s.error) PMS.toast("有 " + s.error + " 行存在错误，这些行不会被写入", "warn");
      } catch (err) {
        previewBox.innerHTML = "";
        PMS.toast(err.message, "error");
      }
    };

    createBox.onchange = function () {
      if (!staged) return;
      document.getElementById("ioCheck").click();
    };

    commitBtn.onclick = async function () {
      if (!staged) return;
      commitBtn.disabled = true;
      commitBtn.textContent = "写入中…";
      try {
        const data = await upload(kind, staged, false, createBox.checked);
        PMS.toast("已写入 " + data.written + " 条记录");
        PMS.closeModal();
        setTimeout(function () { location.reload(); }, 500);
      } catch (err) {
        PMS.toast(err.message, "error");
        commitBtn.disabled = false;
        commitBtn.textContent = "确认导入";
      }
    };
  }

  document.addEventListener("click", function (e) {
    const el = e.target.closest("[data-action='io-import']");
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    openImport(el);
  });
})();

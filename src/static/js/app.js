/* 通用交互：请求、提示、弹层、表单、导航 */
(function () {
  "use strict";

  const PMS = window.PMS = window.PMS || {};

  PMS.base = (document.querySelector('meta[name="app-base"]') || {}).content || "/";

  /* 统一拼接带网关前缀的路径：base 在网关下为 /app/ship-pms/，直连时为 / */
  PMS.url = function (path) {
    const base = String(PMS.base || "/").replace(/\/+$/, "");
    return base + "/" + String(path || "").replace(/^\/+/, "");
  };

  PMS.api = async function (path, method, body) {
    const opts = {
      method: method || "GET",
      headers: { "Accept": "application/json", "X-Requested-With": "fetch" },
      credentials: "same-origin"
    };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(PMS.url(path), opts);
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      const msg = (data && (data.message || data.description)) || ("请求失败 " + res.status);
      if (res.status === 401) {
        location.href = PMS.url("login");
        throw new Error("未登录");
      }
      throw new Error(msg);
    }
    return data || { ok: true };
  };

  PMS.toast = function (message, type) {
    const box = document.getElementById("toasts");
    if (!box) return;
    const el = document.createElement("div");
    el.className = "toast" + (type ? " " + type : "");
    el.textContent = message;
    box.appendChild(el);
    setTimeout(function () {
      el.style.opacity = "0";
      el.style.transition = "opacity .2s";
      setTimeout(function () { el.remove(); }, 220);
    }, type === "error" ? 4200 : 2600);
  };

  PMS.run = async function (fn, okMessage) {
    try {
      const result = await fn();
      if (okMessage) PMS.toast(okMessage);
      return result;
    } catch (err) {
      PMS.toast(err.message || "操作失败", "error");
      return null;
    }
  };

  PMS.modal = function (title, bodyHtml, footHtml, opts) {
    opts = opts || {};
    const host = document.getElementById("modals");
    const mask = document.createElement("div");
    mask.className = "modal-mask open";
    mask.innerHTML =
      '<div class="modal' + (opts.wide ? " wide" : "") + '" role="dialog" aria-modal="true">' +
      '<div class="modal-head"><h3>' + PMS.esc(title) + '</h3>' +
      '<button class="btn ghost sm close" data-close aria-label="关闭">' +
      '<svg class="icon"><use href="#i-x"/></svg></button></div>' +
      '<div class="modal-body">' + bodyHtml + '</div>' +
      (footHtml ? '<div class="modal-foot">' + footHtml + '</div>' : "") +
      "</div>";
    host.appendChild(mask);
    mask.addEventListener("click", function (e) {
      if (e.target === mask || e.target.closest("[data-close]")) PMS.closeModal();
    });
    const first = mask.querySelector("input, select, textarea");
    if (first) setTimeout(function () { first.focus(); }, 40);
    PMS.currentModal = mask;
    return mask;
  };

  PMS.closeModal = function () {
    if (PMS.currentModal) {
      PMS.currentModal.remove();
      PMS.currentModal = null;
    }
    const host = document.getElementById("modals");
    if (host) host.innerHTML = "";
  };

  PMS.esc = function (value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  };

  PMS.formValues = function (root) {
    const out = {};
    root.querySelectorAll("[name]").forEach(function (el) {
      if (el.type === "checkbox") out[el.name] = el.checked;
      else if (el.type === "number") out[el.name] = el.value === "" ? null : Number(el.value);
      else out[el.name] = el.value;
    });
    return out;
  };

  PMS.opt = function (items, valueKey, labelKey, selected, placeholder) {
    let html = placeholder ? '<option value="">' + PMS.esc(placeholder) + "</option>" : "";
    items.forEach(function (item) {
      const value = item[valueKey];
      const label = item[labelKey];
      html += '<option value="' + PMS.esc(value) + '"' +
        (String(selected) === String(value) ? " selected" : "") + ">" + PMS.esc(label) + "</option>";
    });
    return html;
  };

  PMS.reload = function (delay) {
    setTimeout(function () { location.reload(); }, delay || 380);
  };

  PMS.today = function () {
    const d = new Date();
    const p = function (n) { return String(n).padStart(2, "0"); };
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
  };

  PMS.nowLocal = function () {
    const d = new Date();
    const p = function (n) { return String(n).padStart(2, "0"); };
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      "T" + p(d.getHours()) + ":" + p(d.getMinutes());
  };

  /* 顶部时钟（船时由服务端渲染的首屏时间推算，仅作提示） */
  function tick() {
    const el = document.getElementById("clock");
    if (!el) return;
    const d = new Date();
    const p = function (n) { return String(n).padStart(2, "0"); };
    el.textContent = d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  document.addEventListener("DOMContentLoaded", function () {
    tick();
    setInterval(tick, 30000);

    const toggle = document.getElementById("navToggle");
    const sidebar = document.getElementById("sidebar");
    if (toggle && sidebar) {
      toggle.addEventListener("click", function () { sidebar.classList.toggle("open"); });
      sidebar.addEventListener("click", function (e) {
        if (e.target.closest("a") && window.innerWidth <= 860) sidebar.classList.remove("open");
      });
    }

    const logout = document.getElementById("logoutBtn");
    if (logout) {
      logout.addEventListener("click", async function () {
        await PMS.api("api/v1/auth/logout", "POST", {});
        location.href = PMS.url("login");
      });
    }

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") PMS.closeModal();
    });
  });
})();

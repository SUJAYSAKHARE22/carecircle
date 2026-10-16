/* Shared helpers. No innerHTML anywhere: all dynamic text goes through textContent. */
(function () {
  "use strict";
  const params = new URLSearchParams(location.hash.slice(1));
  if (params.get("token")) {
    sessionStorage.setItem("cc_token", params.get("token"));
    history.replaceState(null, "", location.pathname + location.search);
  }

  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  async function api(path, options = {}) {
    const opts = { method: options.method || "GET", headers: { "X-Requested-With": "carecircle" } };
    const token = sessionStorage.getItem("cc_token");
    if (token) opts.headers.Authorization = "Bearer " + token;
    if (options.body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(options.body);
    }
    let response = await fetch(path, opts);
    if (response.status === 401 && !options._retried) {
      const entered = window.prompt("This CareCircle server needs an access token:");
      if (entered) {
        sessionStorage.setItem("cc_token", entered.trim());
        return api(path, { ...options, _retried: true });
      }
    }
    let data = null;
    try { data = await response.json(); } catch (_) { /* non-JSON error body */ }
    if (!response.ok) {
      const err = new Error((data && data.error) || "Request failed (" + response.status + ")");
      err.status = response.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function toast(message, kind) {
    let box = document.getElementById("toasts");
    if (!box) { box = el("div", { id: "toasts", role: "status", "aria-live": "polite" }); document.body.append(box); }
    const node = el("div", { class: "toast " + (kind || ""), text: message });
    box.append(node);
    setTimeout(() => node.remove(), kind === "error" ? 6000 : 3500);
  }

  function pill(text, kind) { return el("span", { class: "pill " + (kind || ""), text }); }
  function pretty(value) { return JSON.stringify(value, null, 2); }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function empty(text) { return el("div", { class: "empty", text }); }

  window.CC = { el, api, toast, pill, pretty, clear, empty };
})();

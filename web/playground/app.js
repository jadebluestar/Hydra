(() => {
  "use strict";

  const API_BASE = "/api/v1";
  const TOKEN_KEY = "hydra_playground_token";
  const HISTORY_KEY = "hydra_playground_history";
  const HISTORY_LIMIT = 50;

  // ── State ─────────────────────────────────────────────────────────────────

  let paramsRows = [{ enabled: true, key: "", value: "" }];
  let headersRows = [{ enabled: true, key: "", value: "" }];
  let lastResponse = null;

  // ── Elements ──────────────────────────────────────────────────────────────

  const el = {
    tokenInput: document.getElementById("token-input"),
    authStatus: document.getElementById("auth-status"),
    loginToggleBtn: document.getElementById("login-toggle-btn"),
    loginPanel: document.getElementById("login-panel"),
    loginEmail: document.getElementById("login-email"),
    loginPassword: document.getElementById("login-password"),
    loginSubmitBtn: document.getElementById("login-submit-btn"),
    loginError: document.getElementById("login-error"),
    methodSelect: document.getElementById("method-select"),
    urlInput: document.getElementById("url-input"),
    sendBtn: document.getElementById("send-btn"),
    paramsTable: document.getElementById("params-table"),
    headersTable: document.getElementById("headers-table"),
    bodyTextarea: document.getElementById("body-textarea"),
    beautifyBtn: document.getElementById("beautify-btn"),
    responseMeta: document.getElementById("response-meta"),
    responseBody: document.getElementById("response-body"),
    responseHeadersTable: document.getElementById("response-headers-table"),
    historyList: document.getElementById("history-list"),
    newRequestBtn: document.getElementById("new-request-btn"),
  };

  // ── Helpers ───────────────────────────────────────────────────────────────

  function getToken() {
    return localStorage.getItem(TOKEN_KEY) || "";
  }

  function setToken(token) {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  }

  function loadHistory() {
    try {
      return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    } catch {
      return [];
    }
  }

  function saveHistory(history) {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, HISTORY_LIMIT)));
  }

  function rowsToObject(rows) {
    const obj = {};
    for (const row of rows) {
      if (row.enabled && row.key.trim() !== "") obj[row.key] = row.value;
    }
    return obj;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // ── Key/value table rendering ────────────────────────────────────────────

  function renderKvTable(tableEl, rows, onChange) {
    tableEl.innerHTML = "";
    rows.forEach((row, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="width:28px"><input type="checkbox" ${row.enabled ? "checked" : ""} data-field="enabled" /></td>
        <td><input type="text" placeholder="key" value="${escapeHtml(row.key)}" data-field="key" /></td>
        <td><input type="text" placeholder="value" value="${escapeHtml(row.value)}" data-field="value" /></td>
        <td style="width:32px"><button class="kv-row-delete" title="Remove">×</button></td>
      `;
      tr.querySelectorAll("input").forEach((input) => {
        input.addEventListener("input", () => {
          const field = input.dataset.field;
          row[field] = field === "enabled" ? input.checked : input.value;
          onChange();
        });
      });
      tr.querySelector(".kv-row-delete").addEventListener("click", () => {
        rows.splice(i, 1);
        if (rows.length === 0) rows.push({ enabled: true, key: "", value: "" });
        renderKvTable(tableEl, rows, onChange);
      });
      tableEl.appendChild(tr);
    });
  }

  function renderParams() {
    renderKvTable(el.paramsTable, paramsRows, () => {});
  }

  function renderHeaders() {
    renderKvTable(el.headersTable, headersRows, () => {});
  }

  document.querySelectorAll(".btn-add").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.target;
      if (target === "params") {
        paramsRows.push({ enabled: true, key: "", value: "" });
        renderParams();
      } else {
        headersRows.push({ enabled: true, key: "", value: "" });
        renderHeaders();
      }
    });
  });

  // ── Tab switching (request editor) ───────────────────────────────────────

  document.querySelectorAll(".editor .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".editor .tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const target = tab.dataset.tab;
      document.querySelectorAll(".editor .tab-panel").forEach((p) => {
        p.classList.toggle("hidden", p.dataset.panel !== target);
      });
    });
  });

  // ── Tab switching (response) ─────────────────────────────────────────────

  document.querySelectorAll("#response-tabs .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("#response-tabs .tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const target = tab.dataset.rtab;
      document.querySelectorAll(".response .tab-panel").forEach((p) => {
        p.classList.toggle("hidden", p.dataset.rpanel !== target);
      });
    });
  });

  // ── Body type switching ──────────────────────────────────────────────────

  document.querySelectorAll('input[name="body-type"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const type = document.querySelector('input[name="body-type"]:checked').value;
      el.bodyTextarea.classList.toggle("hidden", type === "none");
      el.beautifyBtn.classList.toggle("hidden", type !== "json");
    });
  });

  el.beautifyBtn.addEventListener("click", () => {
    try {
      const parsed = JSON.parse(el.bodyTextarea.value);
      el.bodyTextarea.value = JSON.stringify(parsed, null, 2);
    } catch {
      // leave content untouched if it isn't valid JSON yet
    }
  });

  // ── Auth ──────────────────────────────────────────────────────────────────

  function updateAuthStatus() {
    const token = getToken();
    if (!token) {
      el.authStatus.textContent = "not signed in";
      el.authStatus.className = "auth-status";
      return;
    }
    fetch(`${API_BASE}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((user) => {
        el.authStatus.textContent = `signed in as ${user.email}`;
        el.authStatus.className = "auth-status ok";
      })
      .catch(() => {
        el.authStatus.textContent = "token invalid or expired";
        el.authStatus.className = "auth-status err";
      });
  }

  el.tokenInput.value = getToken();
  el.tokenInput.addEventListener("change", () => {
    setToken(el.tokenInput.value.trim());
    updateAuthStatus();
  });

  el.loginToggleBtn.addEventListener("click", () => {
    el.loginPanel.classList.toggle("hidden");
  });

  el.loginSubmitBtn.addEventListener("click", async () => {
    el.loginError.textContent = "";
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: el.loginEmail.value, password: el.loginPassword.value }),
      });
      const data = await res.json();
      if (!res.ok) {
        el.loginError.textContent = data.message || "Login failed";
        return;
      }
      setToken(data.access_token);
      el.tokenInput.value = data.access_token;
      el.loginPanel.classList.add("hidden");
      updateAuthStatus();
    } catch (err) {
      el.loginError.textContent = String(err);
    }
  });

  // ── Send ──────────────────────────────────────────────────────────────────

  function statusClass(status) {
    if (status >= 200 && status < 300) return "status-2xx";
    if (status >= 300 && status < 400) return "status-3xx";
    if (status >= 400 && status < 500) return "status-4xx";
    if (status >= 500) return "status-5xx";
    return "status-err";
  }

  function renderResponse(status, meta, bodyText, headers) {
    el.responseMeta.innerHTML = `
      <span class="status-pill ${statusClass(status)}">${status}</span>
      <span>${meta}</span>
    `;
    el.responseBody.textContent = bodyText;
    el.responseHeadersTable.innerHTML = "";
    Object.entries(headers || {}).forEach(([k, v]) => {
      const tr = document.createElement("tr");
      const keyCell = document.createElement("td");
      keyCell.textContent = k;
      const valCell = document.createElement("td");
      valCell.textContent = v;
      tr.appendChild(keyCell);
      tr.appendChild(valCell);
      el.responseHeadersTable.appendChild(tr);
    });
  }

  function prettyBody(text) {
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return text;
    }
  }

  function currentBodyType() {
    return document.querySelector('input[name="body-type"]:checked').value;
  }

  async function send() {
    const method = el.methodSelect.value;
    const url = el.urlInput.value.trim();
    if (!url) return;

    const bodyType = currentBodyType();
    const headers = rowsToObject(headersRows);
    if (bodyType === "json" && !Object.keys(headers).some((h) => h.toLowerCase() === "content-type")) {
      headers["Content-Type"] = "application/json";
    }

    const payload = {
      method,
      url,
      headers,
      query_params: rowsToObject(paramsRows),
      body: bodyType === "none" ? null : el.bodyTextarea.value,
    };

    el.sendBtn.disabled = true;
    el.sendBtn.textContent = "Sending…";
    const token = getToken();

    try {
      const res = await fetch(`${API_BASE}/playground/execute`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(payload),
      });
      const data = await res.json();

      if (!res.ok) {
        renderResponse(res.status, "request failed", data.message || JSON.stringify(data), {});
        addHistoryEntry(method, url, payload, { status: res.status, elapsed_ms: null });
        return;
      }

      const meta = `${data.elapsed_ms} ms · ${data.size_bytes} B`;
      renderResponse(data.status_code, meta, prettyBody(data.body), data.headers);
      addHistoryEntry(method, url, payload, { status: data.status_code, elapsed_ms: data.elapsed_ms });
    } catch (err) {
      renderResponse(0, "network error", String(err), {});
    } finally {
      el.sendBtn.disabled = false;
      el.sendBtn.textContent = "Send";
    }
  }

  el.sendBtn.addEventListener("click", send);
  el.urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") send();
  });

  // ── History ───────────────────────────────────────────────────────────────

  function addHistoryEntry(method, url, payload, result) {
    const history = loadHistory();
    history.unshift({
      id: crypto.randomUUID(),
      method,
      url,
      payload,
      result,
      timestamp: Date.now(),
    });
    saveHistory(history);
    renderHistory();
  }

  function renderHistory() {
    const history = loadHistory();
    el.historyList.innerHTML = "";
    if (history.length === 0) {
      el.historyList.innerHTML = '<div class="history-empty">No requests sent yet</div>';
      return;
    }
    history.forEach((entry) => {
      const div = document.createElement("div");
      div.className = "history-item";
      div.innerHTML = `
        <span class="history-method m-${entry.method}">${entry.method}</span>
        <span class="history-url">${escapeHtml(entry.url)}</span>
      `;
      div.addEventListener("click", () => loadFromHistory(entry));
      el.historyList.appendChild(div);
    });
  }

  function loadFromHistory(entry) {
    el.methodSelect.value = entry.method;
    el.urlInput.value = entry.url;

    paramsRows = Object.entries(entry.payload.query_params || {}).map(([key, value]) => ({
      enabled: true, key, value,
    }));
    if (paramsRows.length === 0) paramsRows = [{ enabled: true, key: "", value: "" }];
    renderParams();

    headersRows = Object.entries(entry.payload.headers || {}).map(([key, value]) => ({
      enabled: true, key, value,
    }));
    if (headersRows.length === 0) headersRows = [{ enabled: true, key: "", value: "" }];
    renderHeaders();

    const bodyType = entry.payload.body ? "json" : "none";
    document.querySelector(`input[name="body-type"][value="${bodyType}"]`).checked = true;
    el.bodyTextarea.classList.toggle("hidden", bodyType === "none");
    el.beautifyBtn.classList.toggle("hidden", bodyType !== "json");
    el.bodyTextarea.value = entry.payload.body || "";
  }

  el.newRequestBtn.addEventListener("click", () => {
    el.methodSelect.value = "GET";
    el.urlInput.value = "";
    paramsRows = [{ enabled: true, key: "", value: "" }];
    headersRows = [{ enabled: true, key: "", value: "" }];
    renderParams();
    renderHeaders();
    document.querySelector('input[name="body-type"][value="none"]').checked = true;
    el.bodyTextarea.classList.add("hidden");
    el.beautifyBtn.classList.add("hidden");
    el.bodyTextarea.value = "";
    el.responseMeta.innerHTML = '<span class="placeholder-text">Response will appear here</span>';
    el.responseBody.textContent = "";
    el.responseHeadersTable.innerHTML = "";
    el.urlInput.focus();
  });

  // ── Init ──────────────────────────────────────────────────────────────────

  renderParams();
  renderHeaders();
  renderHistory();
  updateAuthStatus();
})();

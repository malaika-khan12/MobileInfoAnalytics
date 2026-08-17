(() => {
  const overlay = document.getElementById("loadingOverlay");
  const reloadBtn = document.getElementById("reloadBtn");

  const tablesWrap = document.getElementById("tablesWrap");
  const tablesError = document.getElementById("tablesError");

  const tableName = document.body.getAttribute("data-table-name");

  function showLoading() {
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
  }
  function hideLoading() {
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
  }

  function escapeHtml(str) {
    return String(str ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  async function fetchJSON(url) {
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(txt || `Request failed: ${res.status}`);
    }
    return res.json();
  }

  function renderSingleTable(tablePayload) {
    tablesWrap.innerHTML = "";

    const t = tablePayload.table;
    if (!t) {
      tablesWrap.innerHTML = `<div class="error">No table payload returned.</div>`;
      return;
    }

    const name = t.name;
    const columns = t.columns || [];
    const rows = t.rows || [];
    const rowCount = t.row_count ?? rows.length;

    const headCells = columns.map(c => `<th>${escapeHtml(c)}</th>`).join("");
    const bodyRows = rows.map(r => {
      const cells = columns.map(c => `<td>${escapeHtml(r[c])}</td>`).join("");
      return `<tr>${cells}</tr>`;
    }).join("");

    const block = document.createElement("div");
    block.className = "table-block";
    block.innerHTML = `
      <div class="tbl-head">
        <div class="tbl-name">${escapeHtml(name)}</div>
        <div class="tbl-meta">${escapeHtml(rowCount)} rows</div>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr>${headCells}</tr></thead>
          <tbody>${bodyRows || `<tr><td colspan="${columns.length}">No rows.</td></tr>`}</tbody>
        </table>
      </div>
    `;
    tablesWrap.appendChild(block);
  }

  async function load() {
    if (!tableName) {
      tablesError.textContent = "Missing data-table-name on <body>.";
      tablesError.classList.remove("hidden");
      return;
    }

    showLoading();
    tablesError.classList.add("hidden");

    try {
      const payload = await fetchJSON(`/api/db/table/${encodeURIComponent(tableName)}?limit=200`);
      renderSingleTable(payload);
    } catch (e) {
      const msg = e?.message || "Unknown error";
      tablesError.textContent = msg;
      tablesError.classList.remove("hidden");
    } finally {
      hideLoading();
    }
  }

  reloadBtn.addEventListener("click", load);
  document.addEventListener("DOMContentLoaded", load);
})();

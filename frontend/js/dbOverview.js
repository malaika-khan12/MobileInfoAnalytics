(() => {
  const overlay = document.getElementById("loadingOverlay");
  const reloadBtn = document.getElementById("reloadBtn");

  const tablesWrap = document.getElementById("tablesWrap");
  const tablesError = document.getElementById("tablesError");

  const chartError = document.getElementById("chartError");
  const monthLabel = document.getElementById("monthLabel");

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

  // ===== charts (same logic as your existing databaseView.js) =====
  function drawBarChart(data) {
    const el = document.getElementById("barChart");
    el.innerHTML = "";

    const margin = { top: 12, right: 12, bottom: 36, left: 46 };
    const width = Math.max(520, el.clientWidth || 520);
    const height = 300;

    const svg = d3.select(el).append("svg")
      .attr("width", "100%")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("preserveAspectRatio", "xMinYMin meet");

    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    const x0 = d3.scaleBand()
      .domain(data.map(d => d.day))
      .range([0, innerW])
      .padding(0.15);

    const x1 = d3.scaleBand()
      .domain(["input_words", "output_words"])
      .range([0, x0.bandwidth()])
      .padding(0.10);

    const maxY = d3.max(data, d => Math.max(d.input_words, d.output_words)) || 0;

    const y = d3.scaleLinear()
      .domain([0, maxY]).nice()
      .range([innerH, 0]);

    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x0).tickValues(data.map(d => d.day).filter((_, i) => i % 2 === 0)))
      .selectAll("text")
      .style("font-weight", 800)
      .style("opacity", 0.85);

    g.append("g")
      .call(d3.axisLeft(y).ticks(5))
      .selectAll("text")
      .style("font-weight", 800)
      .style("opacity", 0.85);

    const color = {
      input_words: "rgba(92,139,192,0.85)",
      output_words: "rgba(9,133,91,0.80)"
    };

    const groups = g.selectAll(".day-group")
      .data(data)
      .enter()
      .append("g")
      .attr("transform", d => `translate(${x0(d.day)},0)`);

    groups.selectAll("rect")
      .data(d => ([
        { key: "input_words", value: d.input_words },
        { key: "output_words", value: d.output_words }
      ]))
      .enter()
      .append("rect")
      .attr("x", d => x1(d.key))
      .attr("y", d => y(d.value))
      .attr("width", x1.bandwidth())
      .attr("height", d => innerH - y(d.value))
      .attr("rx", 6)
      .attr("fill", d => color[d.key]);
  }

  function drawLineChart(data) {
    const el = document.getElementById("lineChart");
    el.innerHTML = "";

    const margin = { top: 12, right: 12, bottom: 36, left: 46 };
    const width = Math.max(420, el.clientWidth || 420);
    const height = 300;

    const svg = d3.select(el).append("svg")
      .attr("width", "100%")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("preserveAspectRatio", "xMinYMin meet");

    const innerW = width - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;

    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    let running = 0;
    const series = data.map(d => {
      running += (d.output_words || 0);
      return { day: d.day, cumulative: running };
    });

    const x = d3.scalePoint()
      .domain(series.map(d => d.day))
      .range([0, innerW]);

    const maxY = d3.max(series, d => d.cumulative) || 0;

    const y = d3.scaleLinear()
      .domain([0, maxY]).nice()
      .range([innerH, 0]);

    g.append("g")
      .attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).tickValues(series.map(d => d.day).filter((_, i) => i % 2 === 0)))
      .selectAll("text")
      .style("font-weight", 800)
      .style("opacity", 0.85);

    g.append("g")
      .call(d3.axisLeft(y).ticks(5))
      .selectAll("text")
      .style("font-weight", 800)
      .style("opacity", 0.85);

    const line = d3.line()
      .x(d => x(d.day))
      .y(d => y(d.cumulative))
      .curve(d3.curveMonotoneX);

    g.append("path")
      .datum(series)
      .attr("fill", "none")
      .attr("stroke", "rgba(46,27,65,0.78)")
      .attr("stroke-width", 3)
      .attr("d", line);

    g.selectAll("circle")
      .data(series)
      .enter()
      .append("circle")
      .attr("cx", d => x(d.day))
      .attr("cy", d => y(d.cumulative))
      .attr("r", 4)
      .attr("fill", "rgba(46,27,65,0.78)");
  }

  async function loadAll() {
    showLoading();
    tablesError.classList.add("hidden");
    chartError.classList.add("hidden");

    try {
      const tablePayload = await fetchJSON("/api/db/table/BlogData?limit=200");
      renderSingleTable(tablePayload);

      const stats = await fetchJSON("/api/stats/tokens/month");
      monthLabel.textContent = stats.month_label || "This Month";
      const series = stats.daily || [];
      drawBarChart(series);
      drawLineChart(series);

    } catch (e) {
      const msg = e?.message || "Unknown error";
      tablesError.textContent = msg;
      tablesError.classList.remove("hidden");
      chartError.textContent = msg;
      chartError.classList.remove("hidden");
    } finally {
      hideLoading();
    }
  }

  reloadBtn.addEventListener("click", loadAll);
  document.addEventListener("DOMContentLoaded", loadAll);
})();

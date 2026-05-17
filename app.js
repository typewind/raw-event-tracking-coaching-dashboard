const number = (value, digits = 0) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
};

const pct = (value) => (value === null || value === undefined ? "—" : `${number(value, 1)}%`);

const state = {
  data: null,
  teams: [],
  metric: "width",
  query: "",
};

function metricValue(team, key) {
  return state.data.teams[team]?.[key] ?? 0;
}

function renderKpis() {
  const audit = state.data.audit;
  const totalHsr = state.data.players.reduce((sum, p) => sum + Number(p.hsr_distance_m || 0), 0);
  const totalSprint = state.data.players.reduce((sum, p) => sum + Number(p.sprint_distance_m || 0), 0);
  const kpis = [
    ["原始事件", audit.event_count, "Opta F24 events"],
    ["Tracking 帧", audit.raw_frames_processed, "Tracab raw frames"],
    ["结构采样", audit.sampled_shape_frames, "1 Hz shape frames"],
    ["HSR 距离", `${number(totalHsr / 1000, 2)} km`, `>= ${audit.hsr_threshold_m_s} m/s`],
    ["Sprint 距离", `${number(totalSprint / 1000, 2)} km`, `>= ${audit.sprint_threshold_m_s} m/s`],
  ];
  document.getElementById("kpiGrid").innerHTML = kpis
    .map(([label, value, note]) => `<div class="kpi"><div class="label">${label}</div><div class="value">${value}</div><div class="note">${note}</div></div>`)
    .join("");
}

function renderTeams() {
  const metrics = [
    ["传球", "passes", 0],
    ["传球成功率", "pass_success_pct", 1],
    ["推进传球", "progressive_passes", 0],
    ["Final third entries", "final_third_entries", 0],
    ["Box entries", "box_entries", 0],
    ["射门", "shots", 0],
    ["平均宽度", "avg_width_m", 1],
    ["平均纵深", "avg_depth_m", 1],
    ["防线高度", "avg_def_line_height_m", 1],
    ["8m 压迫占比", "pressure_8m_pct", 1],
  ];
  const rows = metrics.map(([name, key, digits]) => {
    const values = state.teams.map((team) => Number(metricValue(team, key) || 0));
    const max = Math.max(...values, 1);
    const bars = state.teams
      .map((team) => {
        const value = Number(metricValue(team, key) || 0);
        const width = Math.max(2, (value / max) * 100);
        const suffix = key.includes("pct") ? "%" : key.includes("_m") ? "m" : "";
        return `<div class="bar-line"><span>${team}</span><div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div><strong>${number(value, digits)}${suffix}</strong></div>`;
      })
      .join("");
    return `<div class="metric-row"><div class="name">${name}</div><div class="bar-pair">${bars}</div></div>`;
  });
  document.getElementById("teamCompare").innerHTML = rows.join("");
}

function renderConcepts() {
  document.getElementById("conceptChecks").innerHTML = state.data.concept_checks
    .map(
      (c) => `<article class="concept"><div class="title"><span>${c.concept}</span><span class="status">${c.status}</span></div><p>${c.football_question}</p><p>${typeof c.metric === "string" ? c.metric : JSON.stringify(c.metric)}</p></article>`,
    )
    .join("");
}

function renderIntentBars() {
  const counts = {};
  for (const bout of state.data.hsr_bouts) counts[bout.intent_proxy] = (counts[bout.intent_proxy] || 0) + 1;
  const max = Math.max(...Object.values(counts), 1);
  document.getElementById("intentBars").innerHTML = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => `<div class="intent-row"><span>${label}</span><div class="bar-track"><div class="bar-fill" style="width:${(value / max) * 100}%"></div></div><strong>${value}</strong></div>`)
    .join("");
}

function renderPlayers() {
  const q = state.query.trim().toLowerCase();
  const rows = state.data.players
    .filter((p) => {
      if (!q) return true;
      return [p.player, p.team, p.role].join(" ").toLowerCase().includes(q);
    })
    .sort((a, b) => Number(b.hsr_distance_m || 0) - Number(a.hsr_distance_m || 0))
    .map(
      (p) => `<tr>
        <td><strong>${p.player || `#${p.jersey}`}</strong></td>
        <td>${p.team || ""}</td>
        <td>${p.role || ""}</td>
        <td class="num">${number(p.passes || 0)}</td>
        <td class="num">${pct(p.pass_success_pct)}</td>
        <td class="num">${number(p.progressive_passes || 0)}</td>
        <td class="num">${number(p.shots || 0)}</td>
        <td class="num">${number(p.recoveries || 0)}</td>
        <td class="num">${number(p.hsr_distance_m || 0, 1)}</td>
        <td class="num">${number(p.sprint_distance_m || 0, 1)}</td>
        <td class="num">${number(p.hsr_bouts || 0)}</td>
      </tr>`,
    )
    .join("");
  document.getElementById("playerTable").innerHTML = rows;
}

function renderTimeline() {
  const svg = document.getElementById("timelineChart");
  const width = 900;
  const height = 260;
  const pad = { left: 44, right: 20, top: 18, bottom: 32 };
  const keySuffix = state.metric;
  const series = state.teams.map((team) => ({
    team,
    values: state.data.minute_series
      .map((row) => ({ minute: row.minute, value: row[`${team}_${keySuffix}`] }))
      .filter((d) => d.value !== null && d.value !== undefined),
  }));
  const all = series.flatMap((s) => s.values);
  const minX = Math.min(...all.map((d) => d.minute), 0);
  const maxX = Math.max(...all.map((d) => d.minute), 90);
  const maxY = Math.max(...all.map((d) => Number(d.value)), 1);
  const minY = Math.min(0, ...all.map((d) => Number(d.value)));
  const sx = (x) => pad.left + ((x - minX) / Math.max(1, maxX - minX)) * (width - pad.left - pad.right);
  const sy = (y) => height - pad.bottom - ((y - minY) / Math.max(1, maxY - minY)) * (height - pad.top - pad.bottom);
  const colors = ["#006b68", "#c7472f"];
  const grid = [0, 0.25, 0.5, 0.75, 1]
    .map((t) => {
      const y = pad.top + t * (height - pad.top - pad.bottom);
      return `<line x1="${pad.left}" x2="${width - pad.right}" y1="${y}" y2="${y}" stroke="#dbe3e5"/><text x="8" y="${y + 4}" fill="#66777c" font-size="11">${number(maxY - t * (maxY - minY), 1)}</text>`;
    })
    .join("");
  const paths = series
    .map((s, idx) => {
      const d = s.values.map((v, i) => `${i === 0 ? "M" : "L"}${sx(v.minute)},${sy(Number(v.value))}`).join(" ");
      return `<path d="${d}" fill="none" stroke="${colors[idx]}" stroke-width="3"/><text x="${pad.left + idx * 220}" y="18" fill="${colors[idx]}" font-size="13" font-weight="800">${s.team}</text>`;
    })
    .join("");
  const axis = `<line x1="${pad.left}" x2="${width - pad.right}" y1="${height - pad.bottom}" y2="${height - pad.bottom}" stroke="#aab7bb"/><text x="${width / 2 - 24}" y="${height - 6}" fill="#66777c" font-size="12">minute</text>`;
  svg.innerHTML = `${grid}${axis}${paths}`;
}

function renderAll() {
  renderKpis();
  renderTeams();
  renderConcepts();
  renderIntentBars();
  renderPlayers();
  renderTimeline();
}

async function main() {
  const response = await fetch("./data/dashboard-data.json");
  state.data = await response.json();
  state.teams = Object.keys(state.data.teams);
  document.getElementById("subtitle").textContent = `${state.data.meta.match_label} · ${state.data.meta.method}`;
  document.getElementById("timelineMetric").addEventListener("change", (event) => {
    state.metric = event.target.value;
    renderTimeline();
  });
  document.getElementById("playerSearch").addEventListener("input", (event) => {
    state.query = event.target.value;
    renderPlayers();
  });
  renderAll();
}

main().catch((error) => {
  document.getElementById("subtitle").textContent = `Failed to load dashboard data: ${error.message}`;
});

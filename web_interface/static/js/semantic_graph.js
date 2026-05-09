async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function renderList(nodeId, rows, mapper) {
  const node = document.getElementById(nodeId);
  node.innerHTML = rows.map(mapper).join("");
}

function renderGraph(payload) {
  const canvas = document.getElementById("graphCanvas");
  const nodes = payload.nodes || [];
  const edges = payload.edges || [];
  if (!nodes.length) {
    canvas.innerHTML = "<p>No graph data.</p>";
    return;
  }
  const width = 900;
  const height = 400;
  const step = width / (nodes.length + 1);
  const positions = new Map(nodes.map((node, index) => [node.id, { x: step * (index + 1), y: 80 + (index % 4) * 70 }]));
  const edgeSvg = edges.map((edge) => {
    const a = positions.get(edge.source);
    const b = positions.get(edge.target);
    if (!a || !b) return "";
    return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="rgba(16,185,129,0.45)" stroke-width="1.5" />`;
  }).join("");
  const nodeSvg = nodes.map((node) => {
    const pos = positions.get(node.id);
    return `
      <g>
        <circle cx="${pos.x}" cy="${pos.y}" r="18" fill="${node.type === "dataset" ? "#0f766e" : node.type === "chunk" ? "#10b981" : "#6ee7b7"}"></circle>
        <text x="${pos.x}" y="${pos.y + 34}" text-anchor="middle" fill="#d1fae5" font-size="12">${node.label}</text>
      </g>
    `;
  }).join("");
  canvas.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img">${edgeSvg}${nodeSvg}</svg>`;
}

async function loadAnalytics() {
  const overview = await fetchJson("/api/ingestion/analytics/overview");
  const data = overview.data || {};
  renderList("leaderboard", data.leaderboard || [], (row) => `<article class="job-card"><strong>${row.dataset_uuid || "unknown"}</strong><span>${row.retrieval_count || 0} retrievals</span><small>avg ${(row.avg_score || 0).toFixed(2)}</small></article>`);
  renderList("lowQuality", (data.retrieval?.low_quality_events) || [], (row) => `<article class="chunk-card"><strong>${row.dataset_uuid}</strong><p>${row.retrieval_source} score ${(row.retrieval_score || 0).toFixed(2)}</p></article>`);
  renderList("orphans", data.orphans || [], (row) => `<article class="chunk-card"><strong>${row.dataset_uuid}</strong><p>Chunk ${row.chunk_index}: ${row.preview_text || ""}</p></article>`);
  document.getElementById("chromaHealth").innerHTML = `<pre>${JSON.stringify(data.collection_health || {}, null, 2)}</pre>`;
}

document.getElementById("loadGraphBtn").addEventListener("click", async () => {
  const datasetUuid = document.getElementById("graphDatasetUuid").value.trim();
  if (!datasetUuid) return;
  const payload = await fetchJson(`/api/ingestion/graph/${datasetUuid}`);
  renderGraph(payload.data || {});
});

loadAnalytics().catch((error) => console.error(error));

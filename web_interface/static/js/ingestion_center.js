const state = {
  datasets: [],
  jobs: [],
  orphanFiles: [],
  selectedDataset: null,
  pollTimer: null,
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function renderSummary(totals = {}) {
  const node = document.getElementById("summaryCards");
  const statusCounts = totals.status_counts || {};
  node.innerHTML = `
    <div class="summary-card"><strong>${totals.dataset_count || 0}</strong><span>Datasets</span></div>
    <div class="summary-card"><strong>${totals.chunk_count || 0}</strong><span>Chunks</span></div>
    <div class="summary-card"><strong>${totals.embedding_count || 0}</strong><span>Embeddings</span></div>
    <div class="summary-card"><strong>${Object.keys(statusCounts).length}</strong><span>Status Buckets</span></div>
  `;
}

function datasetActionButtons(dataset) {
  return `
    <button data-action="view" data-id="${dataset.dataset_uuid}">View</button>
    <button data-action="reindex" data-id="${dataset.dataset_uuid}">Reindex</button>
    <button data-action="archive" data-id="${dataset.dataset_uuid}">Archive</button>
    <button data-action="delete" data-id="${dataset.dataset_uuid}">Delete</button>
  `;
}

function renderDatasets(rows) {
  const tbody = document.getElementById("datasetTableBody");
  tbody.innerHTML = rows.map((dataset) => `
    <tr>
      <td>${escapeHtml(dataset.dataset_name)}</td>
      <td><span class="status-pill status-${escapeHtml(dataset.ingestion_status)}">${escapeHtml(dataset.ingestion_status)}</span></td>
      <td>${escapeHtml(dataset.category || "")}</td>
      <td>${dataset.chunk_count || 0}</td>
      <td>${dataset.embedding_count || 0}</td>
      <td>${datasetActionButtons(dataset)}</td>
    </tr>
  `).join("");
}

function parseLogs(job) {
  try {
    return JSON.parse(job.logs_json || "[]");
  } catch (_error) {
    return [];
  }
}

function renderJobs(rows) {
  const node = document.getElementById("jobList");
  if (!rows.length) {
    node.innerHTML = `<p class="muted">No ingestion jobs yet.</p>`;
    return;
  }
  node.innerHTML = rows.map((job) => {
    const dataset = state.datasets.find((item) => item.dataset_uuid === job.dataset_uuid);
    const logs = parseLogs(job).slice(-2);
    return `
      <article class="job-card">
        <div class="job-meta">
          <strong>${escapeHtml(job.job_type)}</strong>
          <span class="status-pill status-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
        </div>
        <small>${escapeHtml(dataset?.dataset_name || job.dataset_uuid || "-")}</small>
        <div class="progress-bar"><span style="width: ${Math.max(0, Math.min(100, job.progress_percent || 0))}%"></span></div>
        <small>${job.progress_percent || 0}% complete</small>
        ${logs.length ? `<ul class="job-log">${logs.map((log) => `<li>${escapeHtml(log.message)}</li>`).join("")}</ul>` : ""}
      </article>
    `;
  }).join("");
}

function renderDetail(payload) {
  document.getElementById("datasetDetail").innerHTML = `
    <h3>${escapeHtml(payload.dataset.dataset_name)}</h3>
    <p>Status: ${escapeHtml(payload.dataset.ingestion_status)}</p>
    <p>File: ${escapeHtml(payload.dataset.original_filename || "-")}</p>
    <p>Collection: ${escapeHtml(payload.vector_health.collection_name || "-")}</p>
    <p>Orphans: ${payload.vector_health.orphan_count || 0}</p>
  `;
  document.getElementById("chunkExplorer").innerHTML = payload.chunks.map((chunk) => `
    <article class="chunk-card">
      <strong>Chunk ${chunk.chunk_index}</strong>
      <p>${escapeHtml(chunk.preview_text || "")}</p>
    </article>
  `).join("");
}

function hasActiveJobs() {
  return state.jobs.some((job) => ["queued", "processing"].includes(job.status));
}

function renderActiveProgress() {
  const shell = document.getElementById("activeJobProgress");
  const activeJob = state.jobs.find((job) => ["processing", "queued"].includes(job.status));
  if (!activeJob) {
    shell.classList.add("hidden");
    return;
  }
  const dataset = state.datasets.find((item) => item.dataset_uuid === activeJob.dataset_uuid);
  document.getElementById("activeJobLabel").textContent = `${activeJob.job_type} • ${dataset?.dataset_name || activeJob.dataset_uuid || "dataset"}`;
  document.getElementById("activeJobPercent").textContent = `${activeJob.progress_percent || 0}%`;
  document.getElementById("activeJobBar").style.width = `${Math.max(0, Math.min(100, activeJob.progress_percent || 0))}%`;
  shell.classList.remove("hidden");
}

function schedulePolling() {
  if (state.pollTimer) {
    clearTimeout(state.pollTimer);
  }
  const nextDelay = hasActiveJobs() ? 1500 : 8000;
  state.pollTimer = setTimeout(async () => {
    try {
      await loadDashboard();
      if (state.selectedDataset?.dataset?.dataset_uuid) {
        await loadDataset(state.selectedDataset.dataset.dataset_uuid);
      }
    } catch (error) {
      console.error(error);
    } finally {
      schedulePolling();
    }
  }, nextDelay);
}

function renderOrphanFiles(files) {
  const node = document.getElementById("orphanList");
  if (!files.length) {
    node.innerHTML = `<p class="muted">No orphan source files detected.</p>`;
    return;
  }
  node.innerHTML = files.map((file) => `
    <article class="orphan-card">
      <strong>${escapeHtml(file.filename)}</strong>
      <small>${escapeHtml(file.source_type)} • ${file.size_bytes} bytes</small>
      <small>${escapeHtml(file.file_path)}</small>
      <div class="orphan-actions">
        <button type="button" data-orphan-action="reingest" data-filename="${escapeHtml(file.filename)}">Re-ingest</button>
      </div>
    </article>
  `).join("");
}

async function loadOrphanSources() {
  const payload = await fetchJson("/api/ingestion/orphan-sources");
  state.orphanFiles = payload.data.files || [];
  document.getElementById("orphanStatus").textContent = `Found ${payload.data.orphan_count || 0} orphan source file(s) in ${payload.data.source_dir}.`;
  renderOrphanFiles(state.orphanFiles);
}

async function reingestOrphans(filenames = []) {
  const statusNode = document.getElementById("orphanStatus");
  statusNode.textContent = filenames.length ? `Queueing ${filenames.length} orphan file(s)...` : "Queueing all orphan files...";
  const payload = await fetchJson("/api/ingestion/orphan-sources/reingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filenames }),
  });
  statusNode.textContent = `Queued ${payload.data.recovered_count || 0} recovered dataset(s).`;
  await Promise.all([loadDashboard(), loadOrphanSources()]);
}

async function loadDashboard() {
  const payload = await fetchJson("/api/ingestion/datasets");
  state.datasets = payload.data.datasets || [];
  state.jobs = payload.data.jobs || [];
  renderSummary(payload.data.totals || {});
  renderDatasets(state.datasets);
  renderJobs(state.jobs);
  renderActiveProgress();
}

async function loadDataset(datasetUuid) {
  const payload = await fetchJson(`/api/ingestion/datasets/${datasetUuid}`);
  state.selectedDataset = payload.data;
  renderDetail(payload.data);
}

async function mutateDataset(datasetUuid, action) {
  const response = await fetchJson(`/api/ingestion/datasets/${datasetUuid}/${action}`, { method: "POST" });
  const statusNode = document.getElementById("uploadStatus");
  if (action === "reindex") {
    statusNode.textContent = `Reindex job queued for ${datasetUuid}.`;
  }
  await loadDashboard();
  await loadDataset(datasetUuid);
  return response;
}

async function performSearch(query) {
  if (!query.trim()) {
    renderDatasets(state.datasets);
    return;
  }
  const payload = await fetchJson(`/api/ingestion/search?q=${encodeURIComponent(query)}`);
  renderDatasets(payload.data || []);
}

function bindEvents() {
  document.getElementById("datasetTableBody").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const datasetUuid = button.dataset.id;
    const action = button.dataset.action;
    if (action === "view") {
      await loadDataset(datasetUuid);
      return;
    }
    await mutateDataset(datasetUuid, action);
  });

  document.getElementById("searchInput").addEventListener("input", (event) => {
    performSearch(event.target.value).catch((error) => console.error(error));
  });

  document.getElementById("uploadForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(event.target);
    const statusNode = document.getElementById("uploadStatus");
    statusNode.textContent = "Uploading source file and queueing ingestion...";
    try {
      const payload = await fetchJson("/api/ingestion/upload", { method: "POST", body: formData });
      const dataset = payload.data?.dataset;
      const job = payload.data?.job;
      if (payload.data?.duplicate) {
        statusNode.textContent = `Duplicate source detected for ${dataset?.dataset_name || "dataset"}.`;
      } else {
        statusNode.textContent = `Queued job #${job?.id || "-"} for ${dataset?.dataset_name || "dataset"}.`;
      }
      event.target.reset();
      await loadDashboard();
      await loadOrphanSources();
    } catch (error) {
      statusNode.textContent = `Upload failed: ${error.message}`;
    }
  });

  document.getElementById("scanOrphansButton").addEventListener("click", () => {
    loadOrphanSources().catch((error) => {
      document.getElementById("orphanStatus").textContent = `Scan failed: ${error.message}`;
    });
  });

  document.getElementById("recoverAllOrphansButton").addEventListener("click", () => {
    reingestOrphans().catch((error) => {
      document.getElementById("orphanStatus").textContent = `Recovery failed: ${error.message}`;
    });
  });

  document.getElementById("orphanList").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-orphan-action='reingest']");
    if (!button) return;
    reingestOrphans([button.dataset.filename]).catch((error) => {
      document.getElementById("orphanStatus").textContent = `Recovery failed: ${error.message}`;
    });
  });
}

Promise.all([loadDashboard(), loadOrphanSources()])
  .then(() => {
    bindEvents();
    schedulePolling();
  })
  .catch((error) => {
    console.error(error);
  });

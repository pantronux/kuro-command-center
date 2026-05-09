const PAGE_SIZE = 10;

const state = {
  datasets: [],
  datasetViewRows: [],
  jobs: [],
  orphanFiles: [],
  selectedDataset: null,
  pollTimer: null,
  search: {
    datasets: "",
    jobs: "",
    detail: "",
    chunks: "",
  },
  filters: {
    status: "non_archived",
    category: "all",
  },
  pagination: {
    datasets: 1,
  },
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
  const status = String(dataset.ingestion_status || "").toLowerCase();
  if (status === "deleted") {
    return `
      <button data-action="view" data-id="${dataset.dataset_uuid}">View</button>
      <button data-action="archive" data-id="${dataset.dataset_uuid}">Archive</button>
    `;
  }
  return `
    <button data-action="view" data-id="${dataset.dataset_uuid}">View</button>
    <button data-action="reindex" data-id="${dataset.dataset_uuid}">Reindex</button>
    <button data-action="archive" data-id="${dataset.dataset_uuid}">Archive</button>
    <button data-action="delete" data-id="${dataset.dataset_uuid}">Delete</button>
  `;
}

function paginateRows(rows, pageKey) {
  const totalItems = rows.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
  const safePage = Math.min(Math.max(1, state.pagination[pageKey] || 1), totalPages);
  state.pagination[pageKey] = safePage;
  const start = (safePage - 1) * PAGE_SIZE;
  return {
    rows: rows.slice(start, start + PAGE_SIZE),
    totalItems,
    totalPages,
    currentPage: safePage,
    startIndex: totalItems ? start + 1 : 0,
    endIndex: Math.min(start + PAGE_SIZE, totalItems),
  };
}

function renderPagination(nodeId, pageKey, pageInfo) {
  const node = document.getElementById(nodeId);
  if (!node) return;
  const prevDisabled = pageInfo.currentPage <= 1 ? "disabled" : "";
  const nextDisabled = pageInfo.currentPage >= pageInfo.totalPages ? "disabled" : "";
  node.innerHTML = `
    <div class="pagination-controls">
      <button type="button" data-page-target="${pageKey}" data-page-dir="-1" ${prevDisabled}>Prev</button>
      <span class="pagination-meta">Page ${pageInfo.currentPage}/${pageInfo.totalPages} • ${pageInfo.startIndex}-${pageInfo.endIndex} of ${pageInfo.totalItems}</span>
      <button type="button" data-page-target="${pageKey}" data-page-dir="1" ${nextDisabled}>Next</button>
    </div>
  `;
}

function renderDatasets(rows) {
  const tableBody = document.getElementById("datasetTableBody");
  const page = paginateRows(rows, "datasets");
  tableBody.innerHTML = page.rows.map((dataset) => `
    <tr>
      <td>${escapeHtml(dataset.dataset_name)}</td>
      <td><span class="status-pill status-${escapeHtml(dataset.ingestion_status)}">${escapeHtml(dataset.ingestion_status)}</span></td>
      <td>${escapeHtml(dataset.category || "")}</td>
      <td>${dataset.chunk_count || 0}</td>
      <td>${dataset.embedding_count || 0}</td>
      <td>${datasetActionButtons(dataset)}</td>
    </tr>
  `).join("");
  renderPagination("datasetPagination", "datasets", page);
}

function renderDatasetFilterOptions() {
  const statusNode = document.getElementById("statusFilter");
  const categoryNode = document.getElementById("categoryFilter");
  const statusSet = new Set(state.datasets.map((item) => item.ingestion_status).filter(Boolean));
  const categorySet = new Set(state.datasets.map((item) => item.category).filter(Boolean));
  const statusOptions = [
    { value: "non_archived", label: "Status: Active" },
    { value: "all", label: "Status: All" },
    ...Array.from(statusSet).sort().map((value) => ({
      value: `status:${value}`,
      label: `Status: ${value}`,
    })),
  ];
  const categoryOptions = [
    { value: "all", label: "Category: All" },
    ...Array.from(categorySet).sort().map((value) => ({
      value,
      label: `Category: ${value}`,
    })),
  ];
  statusNode.innerHTML = statusOptions.map((option) => `
    <option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>
  `).join("");
  categoryNode.innerHTML = categoryOptions.map((option) => `
    <option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>
  `).join("");
  statusNode.value = statusOptions.some((item) => item.value === state.filters.status)
    ? state.filters.status
    : "non_archived";
  categoryNode.value = categoryOptions.some((item) => item.value === state.filters.category)
    ? state.filters.category
    : "all";
  state.filters.status = statusNode.value;
  state.filters.category = categoryNode.value;
}

function applyDatasetFilters(preservePage = false) {
  if (!preservePage) {
    state.pagination.datasets = 1;
  }
  const query = state.search.datasets.trim().toLowerCase();
  const statusFilter = state.filters.status;
  const categoryFilter = state.filters.category;
  const rows = state.datasets.filter((dataset) => {
    const status = String(dataset.ingestion_status || "");
    const category = String(dataset.category || "");
    if (statusFilter === "non_archived" && status.toLowerCase() === "archived") {
      return false;
    }
    if (statusFilter.startsWith("status:")) {
      const expected = statusFilter.slice("status:".length);
      if (status !== expected) {
        return false;
      }
    }
    if (categoryFilter !== "all" && category !== categoryFilter) {
      return false;
    }
    if (!query) {
      return true;
    }
    return [
      dataset.dataset_name,
      dataset.original_filename,
      dataset.ingestion_status,
      dataset.category,
      dataset.dataset_uuid,
    ].some((value) => includesQuery(value, query));
  });
  state.datasetViewRows = rows;
  renderDatasets(rows);
}

function parseLogs(job) {
  try {
    return JSON.parse(job.logs_json || "[]");
  } catch (_error) {
    return [];
  }
}

function includesQuery(value, query) {
  return String(value ?? "").toLowerCase().includes(query);
}

function filterJobs(rows) {
  const query = state.search.jobs.trim().toLowerCase();
  if (!query) return rows;
  return rows.filter((job) => {
    const dataset = state.datasets.find((item) => item.dataset_uuid === job.dataset_uuid);
    const logs = parseLogs(job).map((item) => item.message || "").join(" ");
    return [
      job.job_type,
      job.status,
      job.dataset_uuid,
      dataset?.dataset_name || "",
      job.error_message,
      logs,
    ].some((value) => includesQuery(value, query));
  });
}

function renderJobs(rows) {
  const node = document.getElementById("jobList");
  const filteredRows = filterJobs(rows);
  if (!filteredRows.length) {
    node.innerHTML = `<p class="muted">No ingestion jobs yet.</p>`;
    return;
  }
  node.innerHTML = filteredRows.map((job) => {
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
  const detailNode = document.getElementById("datasetDetail");
  const chunkNode = document.getElementById("chunkExplorer");
  const detailQuery = state.search.detail.trim().toLowerCase();
  const chunkQuery = state.search.chunks.trim().toLowerCase();
  const lineageRows = (payload.lineage || []).filter((item) => {
    if (!detailQuery) return true;
    return [
      item.operation_type,
      item.metadata_json,
      item.created_at,
      item.parent_dataset_uuid,
    ].some((value) => includesQuery(value, detailQuery));
  });
  const chunks = (payload.chunks || []).filter((chunk) => {
    if (!chunkQuery) return true;
    return [
      chunk.chunk_index,
      chunk.preview_text,
      chunk.chunk_text,
      chunk.metadata_json,
    ].some((value) => includesQuery(value, chunkQuery));
  });

  const lineageHtml = lineageRows.length
    ? lineageRows.map((item) => `
      <article class="chunk-card">
        <strong>${escapeHtml(item.operation_type || "event")}</strong>
        <small>${escapeHtml(item.created_at || "-")}</small>
        <p>${escapeHtml(item.metadata_json || "{}")}</p>
      </article>
    `).join("")
    : `<p class="muted">No lineage events.</p>`;

  detailNode.innerHTML = `
    <h3>${escapeHtml(payload.dataset.dataset_name)}</h3>
    <p>Status: ${escapeHtml(payload.dataset.ingestion_status)}</p>
    <p>File: ${escapeHtml(payload.dataset.original_filename || "-")}</p>
    <p>Collection: ${escapeHtml(payload.vector_health.collection_name || "-")}</p>
    <p>Orphans: ${payload.vector_health.orphan_count || 0}</p>
    <hr>
    <h4>Lineage</h4>
    <div class="chunk-list">${lineageHtml}</div>
  `;
  chunkNode.innerHTML = chunks.map((chunk) => `
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
        await loadDataset(state.selectedDataset.dataset.dataset_uuid, true);
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
  renderDatasetFilterOptions();
  applyDatasetFilters(true);
  renderJobs(state.jobs);
  renderActiveProgress();
}

async function loadDataset(datasetUuid, preservePage = false) {
  const payload = await fetchJson(`/api/ingestion/datasets/${datasetUuid}`);
  state.selectedDataset = payload.data;
  renderDetail(payload.data);
}

async function mutateDataset(datasetUuid, action) {
  const response = await fetchJson(`/api/ingestion/datasets/${datasetUuid}/${action}`, { method: "POST" });
  const statusNode = document.getElementById("uploadStatus");
  if (action === "reindex") {
    statusNode.textContent = `Reindex job queued for ${datasetUuid}.`;
  } else if (action === "archive") {
    statusNode.textContent = `Dataset ${datasetUuid} archived.`;
  }
  await loadDashboard();
  if (action !== "delete") {
    await loadDataset(datasetUuid);
  }
  return response;
}

async function performSearch(query, preservePage = false) {
  state.search.datasets = query;
  applyDatasetFilters(preservePage);
}

function onPagerClick(event) {
  const button = event.target.closest("button[data-page-target]");
  if (!button) return;
  const target = button.dataset.pageTarget;
  const dir = Number(button.dataset.pageDir || "0");
  if (!target || !dir) return;
  state.pagination[target] = Math.max(1, (state.pagination[target] || 1) + dir);
  if (target === "datasets") {
    renderDatasets(state.datasetViewRows);
    return;
  }
  if (target === "jobs") {
    return;
  }
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

  document.getElementById("datasetPagination").addEventListener("click", onPagerClick);

  document.getElementById("searchInput").addEventListener("input", (event) => {
    performSearch(event.target.value).catch((error) => console.error(error));
  });
  document.getElementById("statusFilter").addEventListener("change", (event) => {
    state.filters.status = event.target.value;
    applyDatasetFilters(false);
  });
  document.getElementById("categoryFilter").addEventListener("change", (event) => {
    state.filters.category = event.target.value;
    applyDatasetFilters(false);
  });
  document.getElementById("jobSearchInput").addEventListener("input", (event) => {
    state.search.jobs = event.target.value;
    renderJobs(state.jobs);
  });
  document.getElementById("detailSearchInput").addEventListener("input", (event) => {
    state.search.detail = event.target.value;
    if (state.selectedDataset) {
      renderDetail(state.selectedDataset);
    }
  });
  document.getElementById("chunkSearchInput").addEventListener("input", (event) => {
    state.search.chunks = event.target.value;
    if (state.selectedDataset) {
      renderDetail(state.selectedDataset);
    }
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

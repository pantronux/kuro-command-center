async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function renderCollection(nodeId, rows, renderItem, emptyText) {
  const node = document.getElementById(nodeId);
  if (!rows.length) {
    node.innerHTML = `<p class="muted">${emptyText}</p>`;
    return;
  }
  node.innerHTML = rows.map(renderItem).join("");
}

function formatDatasetLabel(row) {
  return escapeHtml(row.dataset_name || row.dataset_uuid || "-");
}

async function loadLogs() {
  const payload = await fetchJson("/api/ingestion/logs");
  const data = payload.data || {};

  renderCollection(
    "failedJobs",
    data.failed_jobs || [],
    (job) => `
      <article class="job-card">
        <div class="job-meta">
          <strong>${escapeHtml(job.job_type || "ingest")}</strong>
          <span class="status-pill status-failed">${escapeHtml(job.status || "failed")}</span>
        </div>
        <small>${formatDatasetLabel(job)}</small>
        <small>${escapeHtml(job.created_at || "-")}</small>
        <p class="muted">${escapeHtml(job.error_message || "No error message captured.")}</p>
      </article>
    `,
    "No failed jobs."
  );

  renderCollection(
    "failedDatasets",
    data.failed_datasets || [],
    (dataset) => `
      <article class="chunk-card">
        <strong>${escapeHtml(dataset.dataset_name || dataset.dataset_uuid)}</strong>
        <p>Status: <span class="status-pill status-failed">${escapeHtml(dataset.ingestion_status || "failed")}</span></p>
        <p class="muted">${escapeHtml(dataset.last_error || "No dataset-level error message.")}</p>
      </article>
    `,
    "No failed datasets."
  );

  renderCollection(
    "duplicateDatasets",
    data.duplicates || [],
    (duplicate) => `
      <article class="chunk-card">
        <strong>${escapeHtml(duplicate.dataset_name || "-")}</strong>
        <p>Entries: ${duplicate.dataset_count || 0}</p>
        <p class="muted">Last updated: ${escapeHtml(duplicate.last_updated || "-")}</p>
        <p class="muted">Statuses: ${escapeHtml((duplicate.statuses || []).join(", "))}</p>
        <p class="muted">UUIDs: ${escapeHtml((duplicate.dataset_uuids || []).join(", "))}</p>
      </article>
    `,
    "No duplicate dataset names detected."
  );

  renderCollection(
    "recentJobs",
    data.recent_jobs || [],
    (job) => `
      <article class="job-card">
        <div class="job-meta">
          <strong>${escapeHtml(job.job_type || "ingest")}</strong>
          <span class="status-pill status-${escapeHtml(job.status || "queued")}">${escapeHtml(job.status || "queued")}</span>
        </div>
        <small>${formatDatasetLabel(job)}</small>
        <small>${escapeHtml(job.created_at || "-")} • ${job.progress_percent || 0}%</small>
      </article>
    `,
    "No job history available."
  );
}

loadLogs().catch((error) => {
  const failedJobsNode = document.getElementById("failedJobs");
  if (failedJobsNode) {
    failedJobsNode.innerHTML = `<p class="muted">Failed to load logs: ${escapeHtml(error.message)}</p>`;
  }
});

const jsonHeaders = { 'Content-Type': 'application/json', Accept: 'application/json' };

async function read(res) {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || body.detail || `HTTP ${res.status}`);
  return body;
}

async function labFetch(path, options) {
  let res;
  try {
    res = await fetch(path, { cache: 'no-store', ...options });
  } catch (err) {
    throw new Error('Lab API is not running on :8199. Start it with ./labctl up');
  }
  return read(res);
}

export async function fetchStatus() {
  return labFetch('/api/lab/status');
}

export async function fetchEngines() {
  return labFetch('/api/engines');
}

export async function fetchLinks() {
  return labFetch('/api/links');
}

export async function fetchRuns() {
  return labFetch('/api/runs');
}

export async function fetchRun(id) {
  return labFetch(`/api/runs/${encodeURIComponent(id)}`);
}

export async function fetchRunLog(id, tail = 400) {
  return labFetch(`/api/runs/${encodeURIComponent(id)}/log?tail=${tail}`);
}

export async function fetchObserve(id) {
  return labFetch(`/api/runs/${encodeURIComponent(id)}/observe`);
}

export async function fetchCompare(leftId, rightId) {
  return labFetch(`/api/runs/${encodeURIComponent(leftId)}/compare/${encodeURIComponent(rightId)}`);
}

export async function generate(payload) {
  return labFetch('/api/generate', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) });
}

export async function cancelRun(id) {
  return labFetch(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST', headers: jsonHeaders, body: '{}' });
}

export async function pinRun(id, label) {
  return labFetch(`/api/runs/${encodeURIComponent(id)}/pin`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ label }),
  });
}

export async function fetchReferences() {
  return labFetch('/api/references');
}

export async function fetchActions() {
  return labFetch('/api/actions');
}

export async function startAction(id, confirm = false) {
  return labFetch(`/api/actions/${encodeURIComponent(id)}`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ confirm }),
  });
}

export async function fetchOmlx() {
  return labFetch('/api/omlx');
}

export async function fetchComfy() {
  return labFetch('/api/comfy');
}

export async function fetchOmlxSnapshot(prompt, model) {
  const params = new URLSearchParams();
  if (prompt) params.set('prompt', prompt);
  if (model) params.set('model', model);
  const query = params.toString();
  return labFetch(`/api/omlx/snapshot${query ? `?${query}` : ''}`);
}

export async function rewritePrompt(prompt, model) {
  return labFetch('/api/omlx/rewrite', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ prompt, model }),
  });
}

export async function fetchJobs() {
  return labFetch('/api/jobs');
}

export async function fetchStorage() {
  return labFetch('/api/storage');
}

export async function deleteRun(id) {
  return labFetch(`/api/runs/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function deleteReference(id) {
  return labFetch(`/api/references/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function reclaimStorage({ keep = 5, keepPinned = true } = {}) {
  return labFetch('/api/storage/reclaim', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ keep, keep_pinned: keepPinned }),
  });
}

export function videoUrl(runId) {
  return `/api/runs/${encodeURIComponent(runId)}/video`;
}

export function referenceVideoUrl(pinId) {
  return `/api/references/${encodeURIComponent(pinId)}/video`;
}

export function formatBytes(n) {
  if (n == null || n === '') return '—';
  const value = Number(n);
  if (!Number.isFinite(value)) return '—';
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)} GB`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)} MB`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)} KB`;
  return `${value} B`;
}

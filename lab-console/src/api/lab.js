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

export async function rewritePrompt(prompt, model) {
  return labFetch('/api/omlx/rewrite', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ prompt, model }),
  });
}

export function videoUrl(runId) {
  return `/api/runs/${encodeURIComponent(runId)}/video`;
}

export function referenceVideoUrl(pinId) {
  return `/api/references/${encodeURIComponent(pinId)}/video`;
}

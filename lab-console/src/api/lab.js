const jsonHeaders = { 'Content-Type': 'application/json', Accept: 'application/json' };

async function read(res) {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || body.detail || `HTTP ${res.status}`);
  return body;
}

export async function fetchStatus() {
  const res = await fetch('/api/lab/status', { cache: 'no-store' });
  return read(res);
}

export async function fetchEngines() {
  const res = await fetch('/api/engines', { cache: 'no-store' });
  return read(res);
}

export async function fetchLinks() {
  const res = await fetch('/api/links', { cache: 'no-store' });
  return read(res);
}

export async function fetchRuns() {
  const res = await fetch('/api/runs', { cache: 'no-store' });
  return read(res);
}

export async function fetchRun(id) {
  const res = await fetch(`/api/runs/${encodeURIComponent(id)}`, { cache: 'no-store' });
  return read(res);
}

export async function fetchRunLog(id, tail = 400) {
  const res = await fetch(`/api/runs/${encodeURIComponent(id)}/log?tail=${tail}`, { cache: 'no-store' });
  return read(res);
}

export async function fetchObserve(id) {
  const res = await fetch(`/api/runs/${encodeURIComponent(id)}/observe`, { cache: 'no-store' });
  return read(res);
}

export async function generate(payload) {
  const res = await fetch('/api/generate', { method: 'POST', headers: jsonHeaders, body: JSON.stringify(payload) });
  return read(res);
}

export async function cancelRun(id) {
  const res = await fetch(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST', headers: jsonHeaders, body: '{}' });
  return read(res);
}

export async function pinRun(id, label) {
  const res = await fetch(`/api/runs/${encodeURIComponent(id)}/pin`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ label }),
  });
  return read(res);
}

export async function fetchReferences() {
  const res = await fetch('/api/references', { cache: 'no-store' });
  return read(res);
}

export async function fetchActions() {
  const res = await fetch('/api/actions', { cache: 'no-store' });
  return read(res);
}

export async function startAction(id, confirm = false) {
  const res = await fetch(`/api/actions/${encodeURIComponent(id)}`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ confirm }),
  });
  return read(res);
}

export function videoUrl(runId) {
  return `/api/runs/${encodeURIComponent(runId)}/video`;
}

export function referenceVideoUrl(pinId) {
  return `/api/references/${encodeURIComponent(pinId)}/video`;
}

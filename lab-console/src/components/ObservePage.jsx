import { useEffect, useState } from 'react';
import { Button, Dropdown, InlineNotification, Tag, Tile, CodeSnippet } from '@carbon/react';
import { deleteRun, fetchCompare, fetchObserve, fetchRuns, formatBytes, videoUrl } from '../api/lab';
import { BarChart, LineChart } from './RunCharts';

function fmtBytes(n) {
  return formatBytes(n);
}

function fmtTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString();
}

function fmtDuration(s) {
  if (s == null) return '—';
  if (s >= 60) return `${Math.floor(s / 60)}m ${(s % 60).toFixed(0)}s`;
  return `${Number(s).toFixed(1)}s`;
}

function fmtDelta(value) {
  if (value == null || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  const sign = n > 0 ? '+' : '';
  return `${sign}${n}`;
}

function winnerLabel(winner) {
  if (winner === 'left') return 'A faster';
  if (winner === 'right') return 'B faster';
  return 'tie';
}

function Details({ title, rows }) {
  const filled = rows.filter((row) => row[1] != null && row[1] !== '');
  return (
    <Tile className="panel">
      <div className="resource-card__kind">{title}</div>
      {filled.length === 0 ? (
        <p className="empty-state">Not captured for this run.</p>
      ) : (
        <dl className="observe-dl">
          {filled.map(([label, value]) => (
            <div key={label} className="observe-dl__row">
              <dt>{label}</dt>
              <dd>{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </Tile>
  );
}

export default function ObservePage({ runId, onSelectRun }) {
  const [runs, setRuns] = useState([]);
  const [pack, setPack] = useState(null);
  const [error, setError] = useState(null);
  const [vsId, setVsId] = useState(null);
  const [compare, setCompare] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetchRuns()
        .then((data) => {
          if (cancelled) return;
          const list = data.runs || [];
          setRuns(list);
          setError(null);
        })
        .catch((err) => {
          if (!cancelled) setError(err.message);
        });
    };
    load();
    const id = setInterval(load, 4000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!runId && runs.length) onSelectRun(runs[0].id);
  }, [runId, runs, onSelectRun]);

  useEffect(() => {
    if (!runId) {
      setPack(null);
      return undefined;
    }
    let cancelled = false;
    const load = () => {
      fetchObserve(runId)
        .then((data) => {
          if (!cancelled) {
            setPack(data);
            setError(null);
          }
        })
        .catch((err) => {
          if (!cancelled) setError(err.message);
        });
    };
    load();
    const id = setInterval(load, 4000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [runId]);

  useEffect(() => {
    if (!runId || !vsId || vsId === runId) {
      setCompare(null);
      return undefined;
    }
    let cancelled = false;
    fetchCompare(runId, vsId)
      .then((data) => {
        if (!cancelled) setCompare(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, vsId]);

  const selected = runs.find((item) => item.id === runId) || pack?.run;
  const job = pack?.job || {};
  const hardware = pack?.hardware || {};
  const software = pack?.software || {};
  const cache = pack?.cache || {};
  const probe = cache.probe || {};
  const stages = pack?.charts?.stages || selected?.trace?.stages || [];
  const links = pack?.links || {};
  const comfy = pack?.comfy || {};
  const params = pack?.params || {};
  const comfyTrace = pack?.comfy_trace || comfy.trace || {};
  const nodeTimings = comfyTrace.nodes || [];
  const running = selected?.state === 'running' || selected?.state === 'queued';
  const vsRun = runs.find((item) => item.id === vsId) || null;
  const compareItems = runs.filter((item) => item.id !== runId);

  return (
    <section className="lab-console__section">
      <div className="section-heading-row">
        <div>
          <h1 className="hero-title">Run report</h1>
          <p className="hero-copy">
            Load a generation to review the clip, prompt, host, MLflow, and charts. Pick a second session to A/B
            parameters and wall time.
          </p>
        </div>
        <div className="config-actions">
          <Dropdown
            id="run"
            titleText="Session A"
            label="Select a run"
            items={runs}
            itemToString={(item) => (item ? `${item.id} (${item.state})` : '')}
            selectedItem={selected}
            onChange={({ selectedItem }) => selectedItem && onSelectRun(selectedItem.id)}
          />
          <Dropdown
            id="run-vs"
            titleText="Compare B"
            label="None"
            items={[{ id: '', state: 'none' }, ...compareItems]}
            itemToString={(item) => (item?.id ? `${item.id} (${item.state})` : 'None')}
            selectedItem={vsRun || { id: '', state: 'none' }}
            onChange={({ selectedItem }) => setVsId(selectedItem?.id || null)}
          />
        </div>
      </div>
      {error && <InlineNotification kind="error" title="Report failed" subtitle={error} lowContrast />}
      {!runId && runs.length === 0 && (
        <p className="hero-copy">
          No lab sessions yet. Queue from Generate, or Queue Prompt in ComfyUI — finished Comfy clips are imported
          into this list automatically.
        </p>
      )}
      {!runId && runs.length > 0 && <p className="hero-copy">Select a session to open its report.</p>}
      {selected && (
        <>
          <div className="observe-meta">
            <Tag type={selected.state === 'succeeded' ? 'green' : selected.state === 'failed' ? 'red' : 'blue'}>
              {selected.state}
            </Tag>
            <span>{pack?.identity?.run_id || selected.id}</span>
            <span>{pack?.identity?.load}</span>
            <span>{pack?.identity?.spec}</span>
            <span>{pack?.identity?.engine}</span>
            <div className="observe-rail">
              {selected.state !== 'running' && selected.state !== 'queued' && (
                <Button
                  kind="danger--ghost"
                  size="sm"
                  onClick={async () => {
                    try {
                      await deleteRun(selected.id);
                      const data = await fetchRuns();
                      const list = data.runs || [];
                      setRuns(list);
                      onSelectRun(list[0]?.id || null);
                    } catch (err) {
                      setError(err.message);
                    }
                  }}
                >
                  Delete run
                </Button>
              )}
              {links.comfy && (
                <Button kind="ghost" size="sm" onClick={() => window.open(comfy.url || links.comfy, '_blank', 'noopener')}>
                  ComfyUI
                </Button>
              )}
              {links.grafana_run && (
                <Button kind="ghost" size="sm" onClick={() => window.open(links.grafana_run, '_blank', 'noopener')}>
                  Grafana
                </Button>
              )}
              {links.mlflow_run && (
                <Button kind="ghost" size="sm" onClick={() => window.open(links.mlflow_run, '_blank', 'noopener')}>
                  MLflow
                </Button>
              )}
              {links.prometheus_run && (
                <Button kind="ghost" size="sm" onClick={() => window.open(links.prometheus_run, '_blank', 'noopener')}>
                  Prometheus
                </Button>
              )}
            </div>
          </div>
          <div className="observe-hero">
            <Tile className="panel">
              <div className="resource-card__kind">Output</div>
              {selected.state === 'succeeded' ? (
                <video className="ltx-video" src={videoUrl(selected.id)} controls />
              ) : (
                <p className="empty-state">{running ? 'Generation still running.' : 'No video for this session.'}</p>
              )}
            </Tile>
            <Tile className="panel">
              <div className="resource-card__kind">Description</div>
              <h3>Prompt</h3>
              <p className="observe-prompt">{job.prompt || selected.request?.prompt || '—'}</p>
              {cache.source_prompt && cache.source_prompt !== (job.prompt || selected.request?.prompt) && (
                <>
                  <h3>Source before oMLX</h3>
                  <p className="observe-prompt">{cache.source_prompt}</p>
                </>
              )}
              {job.error && <InlineNotification kind="error" title="Run error" subtitle={job.error} lowContrast />}
            </Tile>
          </div>
          {compare && (
            <Tile className="panel compare-board">
              <div className="observe-board__intro">
                <div>
                  <h3>A/B compare</h3>
                  <p>
                    Session A `{compare.left?.id}` vs B `{compare.right?.id}`. {winnerLabel(compare.faster)} on wall
                    time. Same join key as Grafana/MLflow (`run_id`).
                  </p>
                </div>
                {links.mlflow && (
                  <Button kind="tertiary" size="sm" onClick={() => window.open(links.mlflow, '_blank', 'noopener')}>
                    Open MLflow
                  </Button>
                )}
              </div>
              <div className="compare-sets__grid">
                <div className="compare-set">
                  <span>A · {compare.left?.id}</span>
                  {compare.left?.job?.state === 'succeeded' ? (
                    <video className="ltx-video" src={videoUrl(compare.left.id)} controls />
                  ) : (
                    <p className="empty-state">No video</p>
                  )}
                </div>
                <div className="compare-set">
                  <span>B · {compare.right?.id}</span>
                  {compare.right?.job?.state === 'succeeded' ? (
                    <video className="ltx-video" src={videoUrl(compare.right.id)} controls />
                  ) : (
                    <p className="empty-state">No video</p>
                  )}
                </div>
              </div>
              <div className="compare-kpis">
                {(compare.metrics || [])
                  .filter((row) => ['duration_s', 'size_bytes', 'comfy_exec_s', 'stage_generate_s'].includes(row.key))
                  .map((row) => (
                    <div key={row.key} className="compare-kpi">
                      <span>{row.key}</span>
                      <strong>{row.winner === 'left' ? 'A' : row.winner === 'right' ? 'B' : '—'}</strong>
                      <dl>
                        <div>
                          <dt>A</dt>
                          <dd>{row.key === 'size_bytes' ? fmtBytes(row.left) : fmtDuration(row.left)}</dd>
                        </div>
                        <div>
                          <dt>B</dt>
                          <dd>{row.key === 'size_bytes' ? fmtBytes(row.right) : fmtDuration(row.right)}</dd>
                        </div>
                      </dl>
                      <small>Δ {fmtDelta(row.delta)}</small>
                    </div>
                  ))}
              </div>
              <h3>Changed parameters</h3>
              <div className="compare-table-wrap">
                <table className="compare-table">
                  <thead>
                    <tr>
                      <th>Parameter</th>
                      <th>A</th>
                      <th>B</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(compare.params_changed || []).length === 0 ? (
                      <tr>
                        <td colSpan={3}>No parameter differences.</td>
                      </tr>
                    ) : (
                      (compare.params_changed || []).map((row) => (
                        <tr key={row.key} className="compare-table__changed">
                          <td>{row.key}</td>
                          <td>{row.left == null || row.left === '' ? '—' : String(row.left)}</td>
                          <td>{row.right == null || row.right === '' ? '—' : String(row.right)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </Tile>
          )}
          <div className="resource-grid">
            <Details
              title="Job"
              rows={[
                ['Run', job.run_id],
                ['Engine', job.engine],
                ['Load', job.load],
                ['Spec', job.height ? `${job.height}×${job.width}×${job.frames} @ ${job.fps} fps` : null],
                ['Seed', job.seed],
                ['Offload', job.offload],
                ['Workflow', job.workflow],
                ['Started', fmtTime(job.started_at)],
                ['Finished', fmtTime(job.finished_at)],
                ['Duration', fmtDuration(job.duration_s)],
                ['Comfy exec', job.comfy_exec_s != null ? fmtDuration(job.comfy_exec_s) : null],
                ['Video', job.video],
                ['Size', job.size_bytes != null ? fmtBytes(job.size_bytes) : null],
                ['SHA-256', job.sha256],
                ['MLflow', job.mlflow_run_id],
              ]}
            />
            <Details
              title="Hardware"
              rows={[
                ['Host', hardware.hostname],
                ['Model', hardware.hw_model],
                ['CPU', hardware.processor],
                ['Arch', hardware.arch],
                ['Cores', hardware.cpu_count],
                ['Unified memory', hardware.memory_bytes != null ? fmtBytes(hardware.memory_bytes) : null],
                ['MPS', hardware.mps == null ? null : hardware.mps ? 'available' : 'no'],
                ['MPS recommended', hardware.mps_recommended != null ? fmtBytes(hardware.mps_recommended) : null],
              ]}
            />
            <Details
              title="Software"
              rows={[
                ['OS', software.os],
                ['Python', software.python],
                ['PyTorch', software.torch],
                ['Engine', software.engine],
                ['Load', software.load],
                ['Offload', software.offload],
                ['LTX tree', software.ltx_tree],
                ['Comfy', software.comfy_version],
                ['Comfy Python', software.comfy_python],
                ['Comfy PyTorch', software.comfy_pytorch],
              ]}
            />
            <Details
              title="ComfyUI"
              rows={[
                ['URL', comfy.url],
                ['Workflow', comfy.workflow],
                ['Prompt id', comfy.prompt_id],
                ['Prefix', comfy.prefix],
                ['Artifact', comfy.artifact?.filename],
                ['Bytes', comfy.bytes != null ? fmtBytes(comfy.bytes) : null],
                ['Version', comfy.comfy_version],
                ['Exec', comfy.trace?.duration_s != null ? fmtDuration(comfy.trace.duration_s) : null],
                ['Nodes', comfy.trace?.node_count],
                ['Cached nodes', Array.isArray(comfy.trace?.cached_nodes) ? comfy.trace.cached_nodes.length : null],
              ]}
            />
            <Details
              title="Graph parameters"
              rows={Object.entries(params).slice(0, 48)}
            />
            <Details
              title="Comfy node timings"
              rows={nodeTimings.slice(0, 24).map((node) => [node.node, fmtDuration(node.duration_s)])}
            />
            <Details
              title="oMLX cache"
              rows={[
                ['Model', cache.model],
                ['Default', cache.default_model],
                ['Admin', cache.admin],
                ['Models dir', cache.models_dir],
                ['SSD cache', cache.ssd_dir],
                ['SSD max', cache.ssd_max],
                ['SSD files', cache.ssd_files],
                ['SSD bytes', cache.ssd_bytes != null ? fmtBytes(cache.ssd_bytes) : null],
                ['Response state', cache.response_state_dir],
                ['oMLX root', cache.base_path],
                ['Settings', cache.settings_path],
                ['Hot RAM cap', cache.hot_cache_max_size],
                ['Hot bytes', cache.hot_bytes != null ? fmtBytes(cache.hot_bytes) : null],
                ['Hot only', cache.hot_cache_only == null ? null : cache.hot_cache_only ? 'yes' : 'no'],
                ['Cached tokens', cache.cached_tokens != null ? `${cache.cached_tokens}/${cache.prompt_tokens}` : null],
                ['Cache hit', cache.cache_hit == null ? null : cache.cache_hit ? 'yes' : 'cold prefix'],
                ['TTFT', cache.ttft_ms != null ? `${cache.ttft_ms} ms` : null],
                ['Block size', cache.block_size],
                ['Indexed blocks', cache.indexed_blocks],
                ['Probe hot', probe.total_blocks != null ? `${probe.blocks_hot}/${probe.total_blocks}` : null],
                ['Probe SSD', probe.blocks_ssd],
                ['Probe cold', probe.blocks_cold],
                ['SSD hit tokens', probe.ssd_hit_tokens],
                ['Hits / misses', cache.hits != null ? `${cache.hits} / ${cache.misses}` : null],
              ]}
            />
          </div>
          <div className="observe-charts">
            <BarChart title="Stage duration" stages={stages} />
            <LineChart
              title="Memory"
              series={pack?.charts?.memory}
              keys={['rss', 'unified', 'mps_allocated']}
              labels={['RSS', 'Unified', 'MPS allocated']}
              formatValue={fmtBytes}
            />
            <LineChart
              title="CPU"
              series={pack?.charts?.cpu}
              keys={['v']}
              labels={['Process CPU']}
              formatValue={(v) => (v == null ? '—' : `${Number(v).toFixed(1)}%`)}
            />
          </div>
          {pack?.grafana_up && (pack.embeds || []).length > 0 && (
            <Tile className="panel observe-board">
              <div className="observe-board__intro">
                <div>
                  <h3>Grafana window</h3>
                  <p>Same run, live Prometheus/Loki panels for the generation interval.</p>
                </div>
                <Button kind="tertiary" size="sm" onClick={() => window.open(links.grafana_run, '_blank', 'noopener')}>
                  Open dashboard
                </Button>
              </div>
              <div className="observe-embeds">
                {pack.embeds.map((embed) => (
                  <figure key={embed.id} className="observe-embed">
                    <figcaption>{embed.title}</figcaption>
                    <iframe title={embed.title} src={embed.url} loading="lazy" referrerPolicy="no-referrer" />
                  </figure>
                ))}
              </div>
            </Tile>
          )}
          <Tile className="panel">
            <h3>Worker log</h3>
            <CodeSnippet type="multi" hideCopyButton>
              {pack?.log || 'No log yet.'}
            </CodeSnippet>
          </Tile>
        </>
      )}
    </section>
  );
}

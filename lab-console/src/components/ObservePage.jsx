import { useEffect, useState } from 'react';
import { Button, Dropdown, InlineNotification, Tag, Tile, CodeSnippet } from '@carbon/react';
import { deleteRun, fetchObserve, fetchRuns, formatBytes, videoUrl } from '../api/lab';
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

  useEffect(() => {
    let cancelled = false;
    fetchRuns()
      .then((data) => {
        if (cancelled) return;
        const list = data.runs || [];
        setRuns(list);
        setError(null);
        if (!runId && list.length) onSelectRun(list[0].id);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
    // Pick the latest session once when opening Report with no hash id.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const selected = runs.find((item) => item.id === runId) || pack?.run;
  const job = pack?.job || {};
  const hardware = pack?.hardware || {};
  const software = pack?.software || {};
  const cache = pack?.cache || {};
  const probe = cache.probe || {};
  const stages = pack?.charts?.stages || selected?.trace?.stages || [];
  const links = pack?.links || {};
  const comfy = pack?.comfy || {};
  const running = selected?.state === 'running' || selected?.state === 'queued';

  return (
    <section className="lab-console__section">
      <div className="section-heading-row">
        <div>
          <h1 className="hero-title">Run report</h1>
          <p className="hero-copy">Load a generation to review the clip, prompt, job, host, and charts for that session.</p>
        </div>
        <div className="config-actions">
          <Dropdown
            id="run"
            titleText="Session"
            label="Select a run"
            items={runs}
            itemToString={(item) => (item ? `${item.id} (${item.state})` : '')}
            selectedItem={selected}
            onChange={({ selectedItem }) => selectedItem && onSelectRun(selectedItem.id)}
          />
        </div>
      </div>
      {error && <InlineNotification kind="error" title="Report failed" subtitle={error} lowContrast />}
      {!runId && <p className="hero-copy">Select a session to open its report.</p>}
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
              ]}
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

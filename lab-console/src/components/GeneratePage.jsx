import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Button,
  Dropdown,
  InlineLoading,
  InlineNotification,
  NumberInput,
  ProgressIndicator,
  ProgressStep,
  Slider,
  Tag,
  TextArea,
  Tile,
} from '@carbon/react';
import { Pin, StopOutline, VideoPlayer } from '@carbon/icons-react';
import { cancelRun, fetchEngines, fetchOmlx, fetchRun, fetchRunLog, fetchRuns, generate, pinRun, rewritePrompt, videoUrl } from '../api/lab';

const DEFAULT_PROMPT =
  'A red hatchback dropped from a helicopter onto a windy coastal runway, cinematic lighting, shallow depth of field, 24fps';

export default function GeneratePage({ onOpenObserve }) {
  const [engines, setEngines] = useState([]);
  const [engine, setEngine] = useState(null);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [height, setHeight] = useState(256);
  const [width, setWidth] = useState(384);
  const [frames, setFrames] = useState(9);
  const [seed, setSeed] = useState(42);
  const [run, setRun] = useState(null);
  const [log, setLog] = useState('');
  const [error, setError] = useState(null);
  const [apiError, setApiError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [omlx, setOmlx] = useState(null);
  const [rewriteBusy, setRewriteBusy] = useState(false);
  const [rewriteInfo, setRewriteInfo] = useState(null);
  const runIdRef = useRef(null);

  const refreshRun = useCallback(async (id) => {
    const next = await fetchRun(id);
    setRun(next);
    const logBody = await fetchRunLog(id);
    setLog(logBody.log || '');
    return next;
  }, []);

  const loadMeta = useCallback(async () => {
    try {
      const data = await fetchEngines();
      const list = data.engines || [];
      setEngines(list.filter((item) => item.modality === 'video'));
      setEngine((current) => {
        if (current) return list.find((item) => item.id === current.id) || current;
        const ready = list.find((item) => item.ready && item.modality === 'video') || list[0];
        if (ready?.default_spec) {
          setHeight(ready.default_spec.height);
          setWidth(ready.default_spec.width);
          setFrames(ready.default_spec.frames);
          setSeed(ready.default_spec.seed);
        }
        return ready || null;
      });
      setApiError(null);
    } catch (err) {
      setApiError(err.message);
    }
    fetchOmlx()
      .then(setOmlx)
      .catch(() => setOmlx(null));
    try {
      const data = await fetchRuns();
      const list = data.runs || [];
      const active = list.find((item) => item.state === 'running' || item.state === 'queued');
      if (active) {
        runIdRef.current = active.id;
        refreshRun(active.id).catch(() => {});
      } else if (!runIdRef.current) {
        const latest = list.find((item) => item.state === 'succeeded') || list[0];
        if (latest) {
          runIdRef.current = latest.id;
          refreshRun(latest.id).catch(() => {});
        }
      }
    } catch {
      /* keep last known run while the API is down */
    }
  }, [refreshRun]);

  useEffect(() => {
    runIdRef.current = run?.id || runIdRef.current;
  }, [run?.id]);

  useEffect(() => {
    loadMeta();
    if (engines.length > 0 && !apiError) return undefined;
    const id = setInterval(loadMeta, 3000);
    return () => clearInterval(id);
  }, [engines.length, apiError, loadMeta]);

  useEffect(() => {
    if (!run?.id || ['succeeded', 'failed', 'cancelled'].includes(run.state)) return undefined;
    const id = setInterval(() => {
      refreshRun(run.id).catch(() => {});
    }, 2000);
    return () => clearInterval(id);
  }, [run?.id, run?.state, refreshRun]);

  const onRewrite = async () => {
    setError(null);
    setRewriteBusy(true);
    try {
      const result = await rewritePrompt(prompt);
      setRewriteInfo(result);
      if (result.prompt) setPrompt(result.prompt);
    } catch (err) {
      setError(err.message);
    } finally {
      setRewriteBusy(false);
    }
  };

  const onGenerate = async () => {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const accepted = await generate({
        prompt,
        engine: engine.id,
        spec: { height, width, frames, fps: 24, seed, offload: engine?.default_spec?.offload || 'disk' },
      });
      setRun(accepted);
      runIdRef.current = accepted.id;
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const bounds = engine?.bounds;
  const stages = run?.trace?.stages || [];
  const current = stages.findIndex((s) => s.status === 'running');
  const currentIndex = current >= 0 ? current : stages.filter((s) => s.status === 'succeeded').length;

  return (
    <section className="lab-console__section">
      <div className="section-heading-row">
        <div>
          <h1 className="hero-title">Generate video</h1>
          <p className="hero-copy">
            Write a prompt, set resolution and length, and run one generation at a time.
          </p>
        </div>
        <div className="toolbar">
          {run?.id && (
            <Button kind="tertiary" size="md" onClick={() => onOpenObserve(run.id)}>
              Open report
            </Button>
          )}
        </div>
      </div>
      {apiError && <InlineNotification kind="error" title="Lab API unreachable" subtitle={apiError} lowContrast />}
      {error && <InlineNotification kind="error" title="Generation blocked" subtitle={error} lowContrast />}
      {notice && <InlineNotification kind="success" title="Saved" subtitle={notice} lowContrast />}
      <div className="generate-layout">
        <Tile className="panel">
          <TextArea
            id="prompt"
            labelText="Prompt"
            value={prompt}
            rows={6}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <div className="omlx-assist">
            <div className="omlx-assist__copy">
              <strong>oMLX rewrite</strong>
              <p>
                Optional. Sends this prompt to the local oMLX LLM on :8000 with a fixed system prefix so KV
                blocks can stay cached. LTX-2 still generates the video.
              </p>
              {omlx?.ready ? (
                <p className="omlx-assist__meta">
                  {omlx.default_model || 'model ready'} · SSD cache {omlx.cache?.ssd_dir || 'on'}
                  {omlx.how?.admin && (
                    <>
                      {' · '}
                      <a href={omlx.how.admin} target="_blank" rel="noreferrer">
                        oMLX admin
                      </a>
                    </>
                  )}
                </p>
              ) : (
                <p className="omlx-assist__meta">
                  {omlx?.error || 'oMLX is not running.'} Start it with <code>omlx start</code> or open oMLX.app,
                  then refresh. Do not generate video while a large oMLX model is loaded if memory is tight.
                </p>
              )}
              {rewriteInfo && (
                <p className="omlx-assist__meta">
                  Last rewrite: {rewriteInfo.model}
                  {rewriteInfo.usage?.cached_tokens != null && (
                    <> · cached {rewriteInfo.usage.cached_tokens}/{rewriteInfo.usage.prompt_tokens} tokens</>
                  )}
                  {rewriteInfo.usage?.ttft_ms != null && <> · TTFT {rewriteInfo.usage.ttft_ms} ms</>}
                  {rewriteInfo.cache_hit ? ' · cache hit' : ' · cold prefix'}
                </p>
              )}
            </div>
            <Button kind="tertiary" size="md" onClick={onRewrite} disabled={rewriteBusy || !omlx?.ready || busy}>
              {rewriteBusy ? 'Rewriting…' : 'Rewrite with oMLX'}
            </Button>
          </div>
          <div className="form-grid" style={{ marginTop: '1rem' }}>
            <Dropdown
              id="engine"
              titleText="Engine"
              items={engines}
              itemToString={(item) => (item ? `${item.label}${item.ready ? '' : ' — unavailable'}` : '')}
              selectedItem={engine}
              onChange={({ selectedItem }) => setEngine(selectedItem)}
            />
            <NumberInput
              id="seed"
              label="Seed"
              value={seed}
              onChange={(_, { value }) => setSeed(Number(value) || 0)}
            />
          </div>
          {bounds && (
            <>
              <Slider
                labelText={`Height (${height})`}
                min={bounds.height.min}
                max={bounds.height.max}
                step={bounds.height.step}
                value={height}
                onChange={({ value }) => setHeight(value)}
              />
              <Slider
                labelText={`Width (${width})`}
                min={bounds.width.min}
                max={bounds.width.max}
                step={bounds.width.step}
                value={width}
                onChange={({ value }) => setWidth(value)}
              />
              <Slider
                labelText={`Frames (${frames}, ${(frames / 24).toFixed(1)}s @ 24fps, 8k+1)`}
                min={bounds.frames.min}
                max={bounds.frames.max}
                step={8}
                value={frames}
                onChange={({ value }) => setFrames(value)}
              />
            </>
          )}
          <div className="toolbar" style={{ marginTop: '1rem' }}>
            <Button
              kind="primary"
              size="md"
              renderIcon={VideoPlayer}
              onClick={onGenerate}
              disabled={busy || !engine?.ready || run?.state === 'running' || run?.state === 'queued'}
            >
              Generate
            </Button>
            {(run?.state === 'running' || run?.state === 'queued') && (
              <Button kind="danger--tertiary" size="md" renderIcon={StopOutline} onClick={() => cancelRun(run.id).then(setRun)}>
                Cancel
              </Button>
            )}
            {run?.state === 'succeeded' && (
              <Button
                kind="secondary"
                size="md"
                renderIcon={Pin}
                onClick={async () => {
                  const pin = await pinRun(run.id, 'ui-reference');
                  setNotice(`Pinned as ${pin.id}`);
                }}
              >
                Pin as reference
              </Button>
            )}
          </div>
        </Tile>
        <Tile className="panel">
          <div className="resource-card__top">
            <h3>Live run</h3>
            {run && <Tag type={run.state === 'succeeded' ? 'green' : run.state === 'failed' ? 'red' : 'blue'}>{run.state}</Tag>}
          </div>
          {!run && <p className="hero-copy">Progress and the finished clip appear here.</p>}
          {busy && <InlineLoading description="Queueing…" />}
          {stages.length > 0 && (
            <ProgressIndicator currentIndex={Math.min(currentIndex, Math.max(stages.length - 1, 0))} spaceEqually>
              {stages.map((stage) => (
                <ProgressStep
                  key={stage.name}
                  label={stage.label}
                  secondaryLabel={stage.duration_label || stage.status}
                  invalid={stage.status === 'failed'}
                  complete={stage.status === 'succeeded'}
                />
              ))}
            </ProgressIndicator>
          )}
          {run?.state === 'succeeded' && (
            <video className="ltx-video" src={videoUrl(run.id)} controls />
          )}
          {run?.error && <InlineNotification kind="error" title="Worker failed" subtitle={run.error} lowContrast />}
          <pre className="ltx-log">{log || 'Worker log will appear here.'}</pre>
        </Tile>
      </div>
    </section>
  );
}

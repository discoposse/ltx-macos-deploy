import { useCallback, useEffect, useState } from 'react';
import { Button, InlineLoading, InlineNotification, Tag, Tile } from '@carbon/react';
import { Play, Renew, Settings, Launch } from '@carbon/icons-react';
import { fetchComfy, fetchOmlx, fetchStatus } from '../api/lab';

export default function StatusPage({ onOpenGenerate, onOpenControls }) {
  const [status, setStatus] = useState(null);
  const [omlx, setOmlx] = useState(null);
  const [comfy, setComfy] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await fetchStatus());
      try {
        setOmlx(await fetchOmlx());
      } catch {
        setOmlx(null);
      }
      try {
        setComfy(await fetchComfy());
      } catch {
        setComfy(null);
      }
      setError(null);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <section className="lab-console__section health-overview">
      <div className="section-heading-row">
        <div>
          <h1 className="hero-title">Lab status</h1>
          <p className="hero-copy">
            Video generation is local on this Mac. Dashboards are optional — if Wi-Fi drops, the console,
            API, and worker keep running on 127.0.0.1.
          </p>
        </div>
        <div className="toolbar">
          <Button kind="tertiary" size="md" renderIcon={Renew} onClick={load} disabled={loading}>
            Refresh
          </Button>
          <Button kind="tertiary" size="md" renderIcon={Launch} onClick={() => window.open(comfy?.ui || status?.links?.comfy || 'http://127.0.0.1:8189', '_blank', 'noopener')}>
            ComfyUI
          </Button>
          <Button kind="primary" size="md" renderIcon={Play} onClick={onOpenGenerate}>
            Generate
          </Button>
          <Button kind="secondary" size="md" renderIcon={Settings} onClick={onOpenControls}>
            Operations
          </Button>
        </div>
      </div>
      {error && <InlineNotification kind="error" title="Cannot load readiness" subtitle={error} lowContrast />}
      {loading && !status && <InlineLoading description="Checking required services…" />}
      {status && (
        <>
          <div className="readiness-banner">
            <div>
              <span className={`readiness-dot ${status.state === 'ready' ? 'readiness-dot--healthy' : ''}`} />
              <strong>{status.state === 'ready' ? 'Ready to generate locally' : 'Lab blocked'}</strong>
            </div>
            <div className="readiness-banner__summary">
              <Tag type={status.state === 'ready' ? 'green' : 'magenta'}>
                {status.summary.up} of {status.summary.total} available
              </Tag>
              <Tag type={status.summary.required_down ? 'red' : 'green'}>
                {status.summary.required_down} blocker{status.summary.required_down === 1 ? '' : 's'}
              </Tag>
            </div>
          </div>
          <div className="resource-grid">
            {status.components.map((item) => (
              <Tile key={item.id} className={`resource-card resource-card--${item.state}`}>
                <div className="resource-card__top">
                  <div>
                    <div className="resource-card__kind">{item.kind}</div>
                    <h3>{item.label}</h3>
                  </div>
                  <Tag type={item.state === 'up' ? 'green' : 'red'}>{item.state}</Tag>
                </div>
                <p>{item.detail}</p>
                {item.state !== 'up' && <p className="resource-card__kind">{item.remediation}</p>}
              </Tile>
            ))}
          </div>
          <h2 className="lab-console__section-title" style={{ marginTop: '2rem' }}>Engines</h2>
          <div className="resource-grid">
            {(status.engines || []).map((engine) => (
              <Tile key={engine.id} className={`resource-card resource-card--${engine.ready ? 'up' : 'down'}`}>
                <div className="resource-card__top">
                  <h3>{engine.label}</h3>
                  <Tag type={engine.ready ? 'green' : 'gray'}>{engine.ready ? 'ready' : 'blocked'}</Tag>
                </div>
                <p>{engine.blocked_reason || `${engine.modality} engine`}</p>
                {engine.id === 'omlx' && (
                  <p className="resource-card__kind">
                    Rewrites prompts only. Load the model and set SSD/hot cache in oMLX admin. Video stays on LTX-2.
                    {omlx?.how?.admin && (
                      <>
                        {' '}
                        <a href={omlx.how.admin} target="_blank" rel="noreferrer">
                          Open admin
                        </a>
                      </>
                    )}
                  </p>
                )}
                {engine.id === 'comfyui' && (
                  <p className="resource-card__kind">
                    Queues an exported API graph against a running ComfyUI. Keep Comfy on :8189 — this lab already owns :8188.
                    {comfy?.ui && (
                      <>
                        {' '}
                        <a href={comfy.ui} target="_blank" rel="noreferrer">
                          Open ComfyUI
                        </a>
                      </>
                    )}
                  </p>
                )}
              </Tile>
            ))}
          </div>
          {comfy && (
            <>
              <h2 className="lab-console__section-title" style={{ marginTop: '2rem' }}>ComfyUI neighbor</h2>
              <div className="resource-grid">
                <Tile className={`resource-card resource-card--${comfy.ready ? 'up' : 'down'}`}>
                  <div className="resource-card__top">
                    <h3>Graph editor + queue</h3>
                    <Tag type={comfy.ready ? 'green' : 'gray'}>{comfy.ready ? 'ready' : 'down'}</Tag>
                  </div>
                  <p>{comfy.error || comfy.how || comfy.url}</p>
                  <p className="resource-card__kind">Listen {comfy.url || 'http://127.0.0.1:8189'}</p>
                  <p className="resource-card__kind">
                    Workflows {(comfy.workflows || []).length}
                    {(comfy.workflows || []).length > 0 ? ` · ${(comfy.workflows || []).map((item) => item.id).join(', ')}` : ' · export File → Export (API) into workflows/comfy'}
                  </p>
                  {comfy.queue && (
                    <p className="resource-card__kind">
                      Queue running {comfy.queue.running} · pending {comfy.queue.pending}
                    </p>
                  )}
                  {comfy.model_hint && <p className="resource-card__kind">LTX model {comfy.model_hint}</p>}
                  {comfy.ui && (
                    <p className="resource-card__kind">
                      <a href={comfy.ui} target="_blank" rel="noreferrer">
                        Open ComfyUI
                      </a>
                    </p>
                  )}
                </Tile>
              </div>
            </>
          )}
          {omlx && (
            <>
              <h2 className="lab-console__section-title" style={{ marginTop: '2rem' }}>oMLX backend</h2>
              <div className="resource-grid">
                <Tile className={`resource-card resource-card--${omlx.ready ? 'up' : 'down'}`}>
                  <div className="resource-card__top">
                    <h3>Model and cache</h3>
                    <Tag type={omlx.ready ? 'green' : 'gray'}>{omlx.ready ? 'ready' : 'down'}</Tag>
                  </div>
                  <p>{omlx.default_model || omlx.error || 'No default model'}</p>
                  <p className="resource-card__kind">Models {omlx.cache?.models_dir}</p>
                  <p className="resource-card__kind">SSD {omlx.cache?.ssd_dir}{omlx.cache?.ssd_max ? ` · ${omlx.cache.ssd_max}` : ''}</p>
                  <p className="resource-card__kind">Hot RAM cap {omlx.cache?.hot_cache_max_size || '0'}</p>
                  {omlx.how?.admin && (
                    <p className="resource-card__kind">
                      <a href={omlx.how.admin} target="_blank" rel="noreferrer">
                        Configure in oMLX admin
                      </a>
                    </p>
                  )}
                </Tile>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}

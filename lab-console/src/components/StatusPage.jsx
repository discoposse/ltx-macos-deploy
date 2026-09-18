import { useCallback, useEffect, useState } from 'react';
import { Button, InlineLoading, InlineNotification, Tag, Tile } from '@carbon/react';
import { Play, Renew, Settings } from '@carbon/icons-react';
import { fetchStatus } from '../api/lab';

export default function StatusPage({ onOpenGenerate, onOpenControls }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await fetchStatus());
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
            Readiness of generation, tracing, and dashboards before you start a run.
          </p>
        </div>
        <div className="toolbar">
          <Button kind="tertiary" size="md" renderIcon={Renew} onClick={load} disabled={loading}>
            Refresh
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
              <strong>{status.state === 'ready' ? 'Ready to generate' : 'Lab blocked'}</strong>
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
              </Tile>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

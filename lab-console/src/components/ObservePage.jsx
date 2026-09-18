import { useEffect, useState } from 'react';
import { Dropdown, InlineNotification, Tag, Tile, CodeSnippet } from '@carbon/react';
import { fetchObserve, fetchRuns, videoUrl } from '../api/lab';

export default function ObservePage({ runId, onSelectRun }) {
  const [runs, setRuns] = useState([]);
  const [pack, setPack] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchRuns()
      .then((data) => {
        setRuns(data.runs || []);
        setError(null);
      })
      .catch((err) => setError(err.message));
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
    const id = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [runId]);

  const selected = runs.find((item) => item.id === runId) || pack?.run;
  const stages = selected?.trace?.stages || [];

  return (
    <section className="lab-console__section">
      <div className="section-heading-row">
        <div>
          <h1 className="hero-title">Observe</h1>
          <p className="hero-copy">Follow a run from prompt through each stage to the finished video.</p>
        </div>
        <Dropdown
          id="run"
          titleText="Run"
          label="Select a run"
          items={runs}
          itemToString={(item) => (item ? `${item.id} (${item.state})` : '')}
          selectedItem={selected}
          onChange={({ selectedItem }) => selectedItem && onSelectRun(selectedItem.id)}
        />
      </div>
      {error && <InlineNotification kind="error" title="Observe failed" subtitle={error} lowContrast />}
      {!runId && <p className="hero-copy">Select a run to inspect its stages and output.</p>}
      {selected && (
        <>
          <div className="resource-grid">
            {(pack?.layers || []).map((layer) => (
              <Tile key={layer.id} className="panel">
                <div className="resource-card__kind">{layer.id}</div>
                <h3>{layer.title}</h3>
                <p>{layer.why}</p>
                <p className="hero-copy">{layer.note}</p>
              </Tile>
            ))}
          </div>
          <Tile className="panel" style={{ marginTop: '1rem' }}>
            <div className="resource-card__top">
              <h3>{selected.id}</h3>
              <Tag type={selected.state === 'succeeded' ? 'green' : selected.state === 'failed' ? 'red' : 'blue'}>
                {selected.state}
              </Tag>
            </div>
            <div className="result-metrics">
              {stages.map((stage) => (
                <div className="result-metric" key={stage.name}>
                  <span>{stage.label}</span>
                  <strong>{stage.duration_label || stage.status}</strong>
                </div>
              ))}
            </div>
            {selected.state === 'succeeded' && <video className="ltx-video" src={videoUrl(selected.id)} controls />}
            <CodeSnippet type="multi" hideCopyButton>
              {pack?.log || 'No log yet.'}
            </CodeSnippet>
          </Tile>
        </>
      )}
    </section>
  );
}

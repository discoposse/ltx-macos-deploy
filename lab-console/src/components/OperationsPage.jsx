import { useCallback, useEffect, useState } from 'react';
import { Button, InlineNotification, Modal, NumberInput, Tile, CodeSnippet, Tag } from '@carbon/react';
import { fetchActions, fetchStorage, reclaimStorage, startAction, deleteRun, formatBytes } from '../api/lab';

const GROUPS = {
  lab: 'Lab',
  observability: 'Observability',
  storage: 'Disk',
  omlx: 'oMLX',
  comfy: 'ComfyUI',
};

export default function OperationsPage() {
  const [actions, setActions] = useState([]);
  const [storage, setStorage] = useState(null);
  const [keep, setKeep] = useState(5);
  const [log, setLog] = useState('');
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [pending, setPending] = useState(null);
  const [reclaimOpen, setReclaimOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const [actionData, storageData] = await Promise.all([fetchActions(), fetchStorage()]);
      setActions(actionData.actions || []);
      setStorage(storageData);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const run = async (action, confirm = false) => {
    if (action.confirm && !confirm) {
      setPending(action);
      return;
    }
    setPending(null);
    try {
      const result = await startAction(action.id, confirm);
      setLog(result.log || '');
      setError(null);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const onReclaim = async () => {
    setReclaimOpen(false);
    try {
      const result = await reclaimStorage({ keep, keepPinned: true });
      setLog(JSON.stringify(result, null, 2));
      setNotice(`Freed ${formatBytes(result.freed_bytes)} across ${result.deleted_count} run${result.deleted_count === 1 ? '' : 's'}.`);
      setError(null);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const total = storage?.total_bytes || 0;
  const meter = Math.min(100, total > 0 ? Math.max(8, Math.min(100, (total / (8 * 1e9)) * 100)) : 0);

  return (
    <section className="lab-console__section">
      <h1 className="hero-title">Operations</h1>
      <p className="hero-copy">
        The lab itself stays on this Mac. Observability is optional. Reclaim disk from old runs without
        touching pinned references or a job that is still rendering.
      </p>
      {error && <InlineNotification kind="error" title="Action failed" subtitle={error} lowContrast />}
      {notice && <InlineNotification kind="success" title="Disk reclaimed" subtitle={notice} lowContrast />}
      <Tile className="panel" style={{ marginBottom: '1.5rem' }}>
        <div className="resource-card__top">
          <div>
            <div className="resource-card__kind">Local storage</div>
            <h3>{formatBytes(total)} on disk</h3>
          </div>
          <Tag type="blue">{storage?.run_count || 0} runs</Tag>
        </div>
        <div className="storage-meter" aria-hidden="true">
          <div className="storage-meter__fill" style={{ width: `${meter}%` }} />
        </div>
        <p className="hero-copy">
          Runs {formatBytes(storage?.runs_bytes)} · References {formatBytes(storage?.references_bytes)}. Keep the newest
          unpinned clips; older directories are deleted from <code>runs/</code>.
        </p>
        <div className="form-grid" style={{ marginTop: '1rem' }}>
          <NumberInput
            id="keep-runs"
            label="Keep newest unpinned runs"
            min={0}
            max={50}
            value={keep}
            onChange={(_, { value }) => setKeep(Number(value) || 0)}
          />
        </div>
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <Button kind="danger--tertiary" size="md" onClick={() => setReclaimOpen(true)}>
            Reclaim disk
          </Button>
        </div>
        {storage?.runs?.length > 0 && (
          <table className="storage-table" style={{ marginTop: '1rem' }}>
            <thead>
              <tr>
                <th>Run</th>
                <th>State</th>
                <th>Prompt</th>
                <th>Size</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {storage.runs.map((item) => (
                <tr key={item.id}>
                  <td>
                    <code>{item.id}</code>
                    {item.pinned ? ' · pinned' : ''}
                  </td>
                  <td>{item.state}</td>
                  <td>{item.prompt}</td>
                  <td>{formatBytes(item.bytes)}</td>
                  <td>
                    {item.state !== 'running' && item.state !== 'queued' && (
                      <Button
                        kind="ghost"
                        size="sm"
                        onClick={async () => {
                          try {
                            await deleteRun(item.id);
                            await load();
                          } catch (err) {
                            setError(err.message);
                          }
                        }}
                      >
                        Delete
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Tile>
      {Object.entries(GROUPS).map(([group, label]) => (
        <div key={group} style={{ marginBottom: '1.5rem' }}>
          <h2 className="lab-console__section-title">{label}</h2>
          <div className="toolbar">
            {actions
              .filter((action) => action.group === group)
              .map((action) => (
                <Button
                  key={action.id}
                  kind={action.confirm ? 'danger--tertiary' : 'tertiary'}
                  size="md"
                  onClick={() => run(action)}
                >
                  {action.title}
                </Button>
              ))}
          </div>
        </div>
      ))}
      <Tile className="panel">
        <div className="resource-card__top">
          <h3>Last action output</h3>
        </div>
        <CodeSnippet type="multi" hideCopyButton>
          {log || 'No action output yet.'}
        </CodeSnippet>
      </Tile>
      <Modal
        open={!!pending}
        danger
        modalHeading={pending?.title}
        primaryButtonText="Confirm"
        secondaryButtonText="Cancel"
        onRequestClose={() => setPending(null)}
        onRequestSubmit={() => run(pending, true)}
      >
        <p>{pending?.warning}</p>
      </Modal>
      <Modal
        open={reclaimOpen}
        danger
        modalHeading="Reclaim disk from old runs"
        primaryButtonText="Delete old runs"
        secondaryButtonText="Cancel"
        onRequestClose={() => setReclaimOpen(false)}
        onRequestSubmit={onReclaim}
      >
        <p>
          Keeps the newest {keep} unpinned run{keep === 1 ? '' : 's'} and every pinned reference. Active
          generations are never deleted.
        </p>
      </Modal>
    </section>
  );
}

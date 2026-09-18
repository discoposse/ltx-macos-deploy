import { useCallback, useEffect, useState } from 'react';
import { Button, InlineNotification, Modal, Tile, CodeSnippet } from '@carbon/react';
import { fetchActions, startAction } from '../api/lab';

const GROUPS = {
  lab: 'Lab',
  observability: 'Observability',
};

export default function OperationsPage() {
  const [actions, setActions] = useState([]);
  const [log, setLog] = useState('');
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchActions();
      setActions(data.actions || []);
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
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section className="lab-console__section">
      <h1 className="hero-title">Operations</h1>
      <p className="hero-copy">Start, stop, and recover lab services. Create videos from Generate.</p>
      {error && <InlineNotification kind="error" title="Action failed" subtitle={error} lowContrast />}
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
    </section>
  );
}

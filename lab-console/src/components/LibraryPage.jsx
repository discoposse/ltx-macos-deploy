import { useCallback, useEffect, useState } from 'react';
import { Button, InlineNotification, Tag, Tile } from '@carbon/react';
import { deleteReference, fetchReferences, formatBytes, referenceVideoUrl } from '../api/lab';

export default function LibraryPage() {
  const [pins, setPins] = useState([]);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(() => {
    fetchReferences()
      .then((data) => {
        setPins(data.references || []);
        setError(null);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <section className="lab-console__section">
      <h1 className="hero-title">Library</h1>
      <p className="hero-copy">
        Pinned generations kept as references. These survive disk reclaim of old runs. Delete a pin here
        if you need the space back.
      </p>
      {error && <InlineNotification kind="error" title="Cannot load references" subtitle={error} lowContrast />}
      {notice && <InlineNotification kind="success" title="Removed" subtitle={notice} lowContrast />}
      {pins.length === 0 && <p className="hero-copy">Pin a finished run from Generate to save it here.</p>}
      <div className="resource-grid">
        {pins.map((pin) => (
          <Tile key={pin.id} className="panel">
            <div className="resource-card__top">
              <h3>{pin.label}</h3>
              <Tag type="blue">{pin.run_id}</Tag>
            </div>
            <p>{pin.request?.prompt}</p>
            <p className="resource-card__kind">{formatBytes(pin.bytes)}</p>
            <video className="ltx-video" src={referenceVideoUrl(pin.id)} controls />
            <Button
              kind="danger--ghost"
              size="sm"
              onClick={async () => {
                try {
                  const result = await deleteReference(pin.id);
                  setNotice(`Removed ${pin.label} (${formatBytes(result.bytes)})`);
                  load();
                } catch (err) {
                  setError(err.message);
                }
              }}
            >
              Delete pin
            </Button>
          </Tile>
        ))}
      </div>
    </section>
  );
}

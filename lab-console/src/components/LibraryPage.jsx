import { useEffect, useState } from 'react';
import { InlineNotification, Tag, Tile } from '@carbon/react';
import { fetchReferences, referenceVideoUrl } from '../api/lab';

export default function LibraryPage() {
  const [pins, setPins] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchReferences()
      .then((data) => setPins(data.references || []))
      .catch((err) => setError(err.message));
  }, []);

  return (
    <section className="lab-console__section">
      <h1 className="hero-title">Library</h1>
      <p className="hero-copy">Pinned generations kept as references for later review.</p>
      {error && <InlineNotification kind="error" title="Cannot load references" subtitle={error} lowContrast />}
      {pins.length === 0 && <p className="hero-copy">Pin a finished run from Generate to save it here.</p>}
      <div className="resource-grid">
        {pins.map((pin) => (
          <Tile key={pin.id} className="panel">
            <div className="resource-card__top">
              <h3>{pin.label}</h3>
              <Tag type="blue">{pin.run_id}</Tag>
            </div>
            <p>{pin.request?.prompt}</p>
            <video className="ltx-video" src={referenceVideoUrl(pin.id)} controls />
          </Tile>
        ))}
      </div>
    </section>
  );
}

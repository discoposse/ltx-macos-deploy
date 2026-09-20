import { useMemo, useState } from 'react';

const PALETTE = ['#0f62fe', '#24a148', '#8a3ffc', '#1192e8', '#fa4d56'];

function extent(values, fallback = 1) {
  const nums = values.filter((v) => typeof v === 'number' && Number.isFinite(v));
  if (!nums.length) return { min: 0, max: fallback };
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  if (min === max) return { min: Math.min(0, min), max: max === 0 ? fallback : max };
  return { min, max };
}

export function LineChart({ title, series, keys, labels, colors = PALETTE, formatValue }) {
  const [hover, setHover] = useState(null);
  const layout = useMemo(() => {
    const rows = (series || []).filter((row) => typeof row.t === 'number');
    const w = 640;
    const h = 180;
    const pad = { l: 52, r: 12, t: 12, b: 28 };
    const innerW = w - pad.l - pad.r;
    const innerH = h - pad.t - pad.b;
    const ts = rows.map((row) => row.t);
    const tExt = extent(ts, 1);
    const vs = rows.flatMap((row) => keys.map((key) => row[key]));
    const vExt = extent(vs, 1);
    const x = (t) => pad.l + ((t - tExt.min) / (tExt.max - tExt.min || 1)) * innerW;
    const y = (v) => pad.t + (1 - (v - vExt.min) / (vExt.max - vExt.min || 1)) * innerH;
    const paths = keys.map((key) => {
      const pts = rows
        .filter((row) => typeof row[key] === 'number')
        .map((row) => `${x(row.t).toFixed(1)},${y(row[key]).toFixed(1)}`);
      return pts.length ? `M ${pts.join(' L ')}` : '';
    });
    return { rows, w, h, pad, x, y, paths, vExt, tExt };
  }, [series, keys]);

  if (!layout.rows.length) {
    return (
      <div className="observe-chart-card">
        <h3>{title}</h3>
        <p className="empty-state">No samples recorded for this run. Charts fill in on the next generation.</p>
      </div>
    );
  }

  const onMove = (event) => {
    const svg = event.currentTarget;
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * layout.w;
    let best = layout.rows[0];
    let bestDist = Infinity;
    layout.rows.forEach((row) => {
      const dist = Math.abs(layout.x(row.t) - px);
      if (dist < bestDist) {
        best = row;
        bestDist = dist;
      }
    });
    setHover(best);
  };

  const fmt = formatValue || ((v) => (v == null ? '—' : String(v)));

  return (
    <div className="observe-chart-card">
      <div className="observe-chart-card__head">
        <h3>{title}</h3>
        {hover && (
          <span className="observe-chart-card__hover">
            {new Date(hover.t * 1000).toLocaleTimeString()} ·{' '}
            {keys.map((key, i) => `${labels[i] || key} ${fmt(hover[key])}`).join(' · ')}
          </span>
        )}
      </div>
      <svg
        className="observe-chart"
        viewBox={`0 0 ${layout.w} ${layout.h}`}
        role="img"
        aria-label={title}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <line
          x1={layout.pad.l}
          x2={layout.w - layout.pad.r}
          y1={layout.h - layout.pad.b}
          y2={layout.h - layout.pad.b}
          className="observe-chart__axis"
        />
        <text x={8} y={layout.pad.t + 8} className="observe-chart__tick">
          {fmt(layout.vExt.max)}
        </text>
        <text x={8} y={layout.h - layout.pad.b} className="observe-chart__tick">
          {fmt(layout.vExt.min)}
        </text>
        {layout.paths.map((d, i) =>
          d ? <path key={keys[i]} d={d} fill="none" stroke={colors[i % colors.length]} strokeWidth="2" /> : null
        )}
        {hover && (
          <line
            x1={layout.x(hover.t)}
            x2={layout.x(hover.t)}
            y1={layout.pad.t}
            y2={layout.h - layout.pad.b}
            className="observe-chart__cursor"
          />
        )}
      </svg>
      <div className="observe-chart-card__legend">
        {keys.map((key, i) => (
          <span key={key}>
            <i style={{ background: colors[i % colors.length] }} />
            {labels[i] || key}
          </span>
        ))}
      </div>
    </div>
  );
}

export function BarChart({ title, stages }) {
  const rows = (stages || []).filter((stage) => typeof stage.duration_s === 'number');
  if (!rows.length) {
    return (
      <div className="observe-chart-card">
        <h3>{title}</h3>
        <p className="empty-state">Stage timings appear as the worker completes each step.</p>
      </div>
    );
  }
  const max = Math.max(...rows.map((row) => row.duration_s), 1);
  return (
    <div className="observe-chart-card">
      <h3>{title}</h3>
      <div className="observe-bars">
        {rows.map((stage) => (
          <div className="observe-bar" key={stage.name}>
            <span>{stage.label || stage.name}</span>
            <div className="observe-bar__track">
              <div
                className={`observe-bar__fill observe-bar__fill--${stage.status || 'pending'}`}
                style={{ width: `${Math.max(4, (stage.duration_s / max) * 100)}%` }}
              />
            </div>
            <strong>{stage.duration_label || `${stage.duration_s.toFixed(1)}s`}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

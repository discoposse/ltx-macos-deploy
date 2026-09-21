import { Button, Tag } from '@carbon/react';
import { StopOutline } from '@carbon/icons-react';
import { cancelRun, formatBytes } from '../api/lab';

function stageLabel(run) {
  const stages = run?.trace?.stages || [];
  const current = stages.find((stage) => stage.status === 'running');
  if (current) return current.label;
  const last = [...stages].reverse().find((stage) => stage.status === 'succeeded');
  return last?.label || run?.state || 'queued';
}

export default function JobDock({ jobs, onOpenGenerate, onOpenStorage }) {
  const running = jobs?.running;
  const queued = jobs?.queued || [];
  const storage = jobs?.storage;
  const disk = formatBytes(storage?.total_bytes);
  const queuedCount = queued.length;

  return (
    <div className="job-dock" role="status">
      <div className="job-dock__live">
        <span className={`job-dock__pulse ${running ? 'job-dock__pulse--live' : ''}`} />
        {running ? (
          <div className="job-dock__copy">
            <strong>Background worker</strong>
            <span>
              {running.id} · {stageLabel(running)} · stays running if Wi-Fi drops
            </span>
          </div>
        ) : queuedCount ? (
          <div className="job-dock__copy">
            <strong>Queue armed</strong>
            <span>Next clip starts as soon as the worker is free</span>
          </div>
        ) : (
          <div className="job-dock__copy">
            <strong>Worker idle</strong>
            <span>Generate a clip. It runs in the background on this Mac.</span>
          </div>
        )}
      </div>
      <div className="job-dock__meta">
        <Tag type={running ? 'blue' : 'gray'}>{running ? 'running' : 'idle'}</Tag>
        <Tag type={queuedCount ? 'purple' : 'gray'}>{queuedCount} queued</Tag>
        <button type="button" className="job-dock__disk" onClick={onOpenStorage}>
          Disk {disk}
        </button>
        <span className="job-dock__local">127.0.0.1 · offline-safe</span>
        {running && (
          <Button
            kind="danger--ghost"
            size="sm"
            renderIcon={StopOutline}
            onClick={() => cancelRun(running.id).catch(() => {})}
          >
            Cancel
          </Button>
        )}
        <Button kind="ghost" size="sm" onClick={onOpenGenerate}>
          Generate
        </Button>
      </div>
    </div>
  );
}

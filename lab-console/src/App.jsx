import { useCallback, useEffect, useState } from 'react';
import {
  Header,
  HeaderName,
  HeaderNavigation,
  HeaderMenuItem,
  HeaderGlobalBar,
  HeaderGlobalAction,
  Content,
  Theme,
  SkipToContent,
} from '@carbon/react';
import { ChartLine, Dashboard, Activity, Launch } from '@carbon/icons-react';
import StatusPage from './components/StatusPage';
import GeneratePage from './components/GeneratePage';
import ObservePage from './components/ObservePage';
import LibraryPage from './components/LibraryPage';
import OperationsPage from './components/OperationsPage';
import { fetchLinks } from './api/lab';

const NAV = [
  { id: 'overview', label: 'Status' },
  { id: 'generate', label: 'Generate' },
  { id: 'observe', label: 'Observe' },
  { id: 'library', label: 'Library' },
  { id: 'controls', label: 'Operations' },
];

function parseRoute() {
  const raw = (typeof window !== 'undefined' && window.location.hash.slice(1)) || '';
  if (raw.startsWith('observe=')) {
    return { tab: 'observe', runId: decodeURIComponent(raw.slice('observe='.length)) };
  }
  const tab = raw.split('&')[0].split('=')[0];
  if (NAV.some((n) => n.id === tab)) return { tab, runId: null };
  return { tab: 'overview', runId: null };
}

export default function App() {
  const [{ tab, runId }, setRoute] = useState(() => parseRoute());
  const [links, setLinks] = useState(null);

  const go = useCallback((nextTab, { runId: nextRun, replace } = {}) => {
    let hash = nextTab;
    if (nextTab === 'observe' && nextRun) hash = `observe=${encodeURIComponent(nextRun)}`;
    const url = `#${hash}`;
    if (replace) window.history.replaceState(null, '', url);
    else window.history.pushState(null, '', url);
    setRoute({ tab: nextTab, runId: nextRun || null });
  }, []);

  useEffect(() => {
    const onHash = () => setRoute(parseRoute());
    window.addEventListener('hashchange', onHash);
    window.addEventListener('popstate', onHash);
    if (!window.location.hash) window.history.replaceState(null, '', '#overview');
    fetchLinks().then(setLinks).catch(() => setLinks(null));
    return () => {
      window.removeEventListener('hashchange', onHash);
      window.removeEventListener('popstate', onHash);
    };
  }, []);

  return (
    <Theme theme="g100" className="lab-theme">
      <div className="lab-console">
        <Header aria-label="LTX Lab Console">
          <SkipToContent />
          <HeaderName
            href="#overview"
            prefix=""
            onClick={(e) => {
              e.preventDefault();
              go('overview');
            }}
          >
            <span className="lab-header__brand">
              <span className="lab-header__mark">LTX</span>
              <span className="lab-header__product">Video Lab</span>
            </span>
          </HeaderName>
          <HeaderNavigation aria-label="Lab sections">
            {NAV.map((item) => (
              <HeaderMenuItem
                key={item.id}
                href={`#${item.id}`}
                isActive={tab === item.id}
                onClick={(e) => {
                  e.preventDefault();
                  go(item.id);
                }}
              >
                {item.label}
              </HeaderMenuItem>
            ))}
          </HeaderNavigation>
          <HeaderGlobalBar>
            <HeaderGlobalAction
              aria-label="Grafana"
              tooltipAlignment="end"
              onClick={() => window.open(links?.grafana || 'http://127.0.0.1:3300', '_blank', 'noopener')}
            >
              <Dashboard size={20} />
            </HeaderGlobalAction>
            <HeaderGlobalAction
              aria-label="Prometheus"
              tooltipAlignment="end"
              onClick={() => window.open(links?.prometheus || 'http://127.0.0.1:9190', '_blank', 'noopener')}
            >
              <ChartLine size={20} />
            </HeaderGlobalAction>
            <HeaderGlobalAction
              aria-label="MLflow"
              tooltipAlignment="end"
              onClick={() => window.open(links?.mlflow || 'http://127.0.0.1:5001', '_blank', 'noopener')}
            >
              <Activity size={20} />
            </HeaderGlobalAction>
            <HeaderGlobalAction
              aria-label="Open generate"
              tooltipAlignment="end"
              onClick={() => go('generate')}
            >
              <Launch size={20} />
            </HeaderGlobalAction>
          </HeaderGlobalBar>
        </Header>
        <Content className={`lab-console__main lab-console__main--${tab}`} id="main-content">
          {tab === 'overview' && <StatusPage onOpenGenerate={() => go('generate')} onOpenControls={() => go('controls')} />}
          {tab === 'generate' && <GeneratePage onOpenObserve={(id) => go('observe', { runId: id })} />}
          {tab === 'observe' && <ObservePage runId={runId} onSelectRun={(id) => go('observe', { runId: id, replace: true })} />}
          {tab === 'library' && <LibraryPage />}
          {tab === 'controls' && <OperationsPage />}
        </Content>
      </div>
    </Theme>
  );
}

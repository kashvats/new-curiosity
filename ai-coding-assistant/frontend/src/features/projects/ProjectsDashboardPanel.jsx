import React, { useState, useEffect } from 'react';
import { apiClient } from '../../api/client';
import ProjectGenerator from './ProjectGenerator';

// ─── helpers ───────────────────────────────────────────────────────────────
const LANG_META = {
  'Node.js':  { icon: '🟢', color: '#3fb950' },
  'Python':   { icon: '🐍', color: '#58a6ff' },
  'Unknown':  { icon: '📦', color: '#7d8590' },
};

const STATUS_META = {
  none:     { label: 'No Report',  color: '#7d8590', bg: 'rgba(0,0,0,0.1)' },
  ok:       { label: 'OK',         color: '#3fb950', bg: 'rgba(0,0,0,0.1)' },
  clean:    { label: 'Clean',      color: '#3fb950', bg: 'rgba(0,0,0,0.1)' },
  indexed:  { label: 'Indexed',    color: '#3fb950', bg: 'rgba(0,0,0,0.1)' },
  warning:  { label: 'Warning',    color: '#d29922', bg: 'rgba(0,0,0,0.1)' },
  critical: { label: 'Critical',   color: '#f85149', bg: 'rgba(0,0,0,0.1)' },
  error:    { label: 'Error',      color: '#f85149', bg: 'rgba(0,0,0,0.1)' },
  unknown:  { label: 'Unknown',    color: '#7d8590', bg: 'rgba(0,0,0,0.1)' },
  available:{ label: 'Available',  color: '#3fb950', bg: 'rgba(0,0,0,0.1)' },
  missing:  { label: 'Missing',    color: '#7d8590', bg: 'rgba(0,0,0,0.1)' },
};

function Badge({ value }) {
  const m = STATUS_META[String(value).toLowerCase()] || STATUS_META.unknown;
  return (
    <span style={{fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 20,
      display: 'inline-block'}}>{m.label}</span>
  );
}

function StatRow({ label, value, badge }) {
  return (
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 0'}}>
      <span style={{fontSize: 12}}>{label}</span>
      {badge ? <Badge value={value} /> : <span style={{fontSize: 12, fontWeight: 600}}>{value ?? '—'}</span>}
    </div>
  );
}

// ─── Project Card ───────────────────────────────────────────────────────────
function ProjectCard({ project, summary, docker, isActive, onOpen, onAnalyze }) {
  const lang = LANG_META[project.detected_type] || LANG_META.Unknown;

  return (
    <div style={{borderRadius: 12,
      padding: 20,
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
      transition: 'box-shadow .2s'}}>

      {/* Header */}
      <div style={{display: 'flex', alignItems: 'flex-start', gap: 12}}>
        <div style={{width: 44, height: 44, borderRadius: 10,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 22, flexShrink: 0}}>{lang.icon}</div>

        <div style={{flex: 1, minWidth: 0}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
            <h3 style={{margin: 0, fontSize: 15, fontWeight: 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>
              {project.name}
            </h3>
            {isActive && (
              <span style={{fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 20}}>
                ACTIVE
              </span>
            )}
          </div>
          <div style={{fontSize: 11, marginTop: 3, fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
            {project.path}
          </div>
        </div>
      </div>

      {/* Stats */}
      <div style={{borderRadius: 8, padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 2}}>
        <StatRow label="Language"     value={project.detected_type} />
        <StatRow label="Files"        value={summary?.files ?? '…'} />
        <StatRow label="Audit"        value={summary?.audit_status ?? 'unknown'} badge />
        <StatRow label="Architecture" value={summary?.architecture_status ?? 'unknown'} badge />
        <StatRow label="Docker"       value={docker?.docker_status ?? 'unknown'} badge />
        <StatRow label="Discovered"   value={project.created_at ? new Date(project.created_at).toLocaleDateString() : '—'} />
      </div>

      {/* Actions */}
      <div style={{display: 'flex', flexWrap: 'wrap', gap: 8}}>
        <button
          onClick={() => onOpen(project.id)}
          disabled={isActive}
          style={{flex: '1 1 100%', padding: '10px 0', borderRadius: 7, cursor: isActive ? 'default' : 'pointer',
            fontWeight: 700, fontSize: 13, backgroundColor: isActive ? '#238636' : '#1f6feb', color: '#fff', border: 'none'}}
        >{isActive ? '✓ Active Workspace' : '▶ Enter Workspace'}</button>
      </div>
    </div>
  );
}

// ─── Empty State ────────────────────────────────────────────────────────────
function EmptyState({ onScan, scanning }) {
  return (
    <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '80px 20px', gap: 20}}>
      <div style={{fontSize: 64}}>📁</div>
      <div style={{textAlign: 'center'}}>
        <h2 style={{margin: '0 0 8px', fontSize: 20}}>No Projects Found</h2>
        <p style={{margin: '0 0 24px', fontSize: 14, maxWidth: 400}}>
          Drop your project folders into <code >/workspace/projects</code> inside the Docker container, then click Scan to discover them.
        </p>
        <button
          onClick={onScan}
          disabled={scanning}
          style={{padding: '10px 28px', borderRadius: 8, cursor: 'pointer',
            fontWeight: 700, fontSize: 14}}
        >{scanning ? '⟳ Scanning…' : '⟳ Scan for Projects'}</button>
      </div>
    </div>
  );
}

// ─── Main Page ──────────────────────────────────────────────────────────────
export default function ProjectsDashboardPanel({ onOpenProject, activeProjectId }) {
  const [projects, setProjects]         = useState([]);
  const [summaries, setSummaries]       = useState({});
  const [dockerStatuses, setDocker]     = useState({});
  const [scanning, setScanning]         = useState(false);
  const [error, setError]               = useState(null);
  const [filter, setFilter]             = useState('');
  const [techStack, setTechStack]       = useState('');
  const [showGenerator, setShowGenerator] = useState(false);

  const loadProjects = async () => {
    setScanning(true);
    setError(null);
    try {
      const data = await apiClient.getJson('/projects/available');

      // The backend returns an array of string project names. Map them to objects for the UI.
      const list = (data.projects || []).map(name => ({
        id: name,
        name: name,
        path: `/workspace/projects/${name}`,
        detected_type: 'Unknown' // No backend support for language detection yet
      }));
      setProjects(list);

      // Restore active session from localStorage
      const saved = localStorage.getItem('active_project_id');
      if (saved && list.find(p => p.id === saved)) {
        // Just keeping the visual active state without calling non-existent setActiveId
      }
    } catch (err) {
      setError(err.message);
    }
    setScanning(false);
  };

  const fetchSummary = async (pid) => {
    try {
      const data = await apiClient.getJson(`/projects/${pid}/summary`);
      setSummaries(prev => ({ ...prev, [pid]: data }));
    } catch { /* ignore */ }
  };

  const fetchDocker = async (pid) => {
    try {
      const data = await apiClient.getJson(`/projects/${pid}/docker-status`);
      setDocker(prev => ({ ...prev, [pid]: data }));
    } catch { /* ignore */ }
  };

  const openProject = async (pid) => {
    // There is no /projects/open endpoint, we just transition the UI locally
    localStorage.setItem('active_project_id', pid);
    if (onOpenProject) {
      // Find the project object to pass up
      const p = projects.find(proj => proj.id === pid);
      if (p) onOpenProject(p);
    }
  };

  const runAnalysis = async (pid, action) => {
    try {
      const payload = {
        run_architecture: action === 'architecture',
        run_audit: action === 'audit',
        run_debug: action === 'debug',
        run_regression: action === 'regression',
        run_codebase_indexing: action === 'indexing',
      };
      await apiClient.postJson(`/projects/${pid}/run-analysis`, payload);
      setTimeout(() => fetchSummary(pid), 3000);
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => { loadProjects(false); }, []);

  const filtered = projects.filter(p => {
    const matchName = !filter || p.name.toLowerCase().includes(filter.toLowerCase());
    const matchTech = !techStack || p.detected_type === techStack;
    return matchName && matchTech;
  });

  const uniqueTechStacks = [...new Set(projects.map(p => p.detected_type).filter(Boolean))];

  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: 20}}>

      {/* Toolbar */}
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <input
          type="text"
          placeholder="Filter projects…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{flex: '1 1 200px', padding: '8px 14px', borderRadius: 8,
            fontSize: 13, outline: 'none', backgroundColor: '#0d1117', border: '1px solid #30363d', color: '#c9d1d9'}}
        />

        <select
          value={techStack}
          onChange={e => setTechStack(e.target.value)}
          style={{padding: '8px 14px', borderRadius: 8, fontSize: 13, outline: 'none', backgroundColor: '#0d1117', border: '1px solid #30363d', color: '#c9d1d9'}}
        >
          <option value="">All Tech Stacks</option>
          {uniqueTechStacks.map(tech => (
            <option key={tech} value={tech}>{tech}</option>
          ))}
        </select>

        <button
          onClick={() => loadProjects(false)}
          style={{padding: '8px 18px', borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer'}}
        >⟳ Refresh</button>

        <button
          onClick={() => setShowGenerator(!showGenerator)}
          style={{padding: '8px 18px', borderRadius: 8, cursor: 'pointer',
            fontWeight: 700, fontSize: 13, backgroundColor: '#238636', color: '#fff', border: '1px solid rgba(240, 246, 252, 0.1)'}}
        >✨ New Project</button>

        <button
          onClick={() => loadProjects()}
          disabled={scanning}
          style={{padding: '8px 18px', borderRadius: 8, cursor: scanning ? 'wait' : 'pointer',
            fontWeight: 700, fontSize: 13}}
        >{scanning ? '⟳ Scanning…' : '⟳ Scan Workspace'}</button>

        <div style={{marginLeft: 'auto', fontSize: 12}}>
          {filtered.length} project{filtered.length !== 1 ? 's' : ''}
          {activeProjectId && <> · <span >1 active</span></>}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{padding: '12px 16px', borderRadius: 8, fontSize: 13}}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Generator UI */}
      {showGenerator && (
        <ProjectGenerator 
          onCancel={() => setShowGenerator(false)} 
          onComplete={() => {
            setShowGenerator(false);
            loadProjects(true); // Rescan to find the new project
          }} 
        />
      )}

      {/* Grid or empty */}
      {filtered.length === 0 && !scanning
        ? <EmptyState onScan={() => loadProjects()} scanning={scanning} />
        : (
          <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 20}}>
            {filtered.map(p => (
              <ProjectCard
                key={p.id}
                project={p}
                summary={{}} // Mocked since /projects/{id}/summary doesn't exist
                docker={{}} // Mocked since /projects/{id}/docker-status doesn't exist
                isActive={activeProjectId === p.id}
                onOpen={openProject}
                onAnalyze={runAnalysis}
              />
            ))}
          </div>
        )
      }
    </div>
  );
}

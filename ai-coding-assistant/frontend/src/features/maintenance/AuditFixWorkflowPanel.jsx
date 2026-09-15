import React, { useState, useEffect, useRef } from 'react';
import { apiClient } from '../../api/client';

// ─── Sub-components ──────────────────────────────────────────────────────────

const RISK_META = {
  none:   { color: '#8b949e', label: 'None',   bg: 'rgba(139,148,158,0.1)' },
  low:    { color: '#3fb950', label: 'Low',    bg: 'rgba(63,185,80,0.1)'   },
  medium: { color: '#d29922', label: 'Medium', bg: 'rgba(210,153,34,0.1)'  },
  high:   { color: '#f85149', label: 'High',   bg: 'rgba(248,81,73,0.1)'   },
};

function NodeStatusIcon({ status }) {
  if (status === 'complete') return <span style={{ color: '#3fb950' }}>✓</span>;
  if (status === 'failed')   return <span style={{ color: '#f85149' }}>✗</span>;
  if (status === 'running')  return <span style={{ color: '#58a6ff' }}>⟳</span>;
  return <span style={{ color: '#484f58' }}>○</span>;
}

function NodeRow({ node }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 10,
      padding: '7px 12px', borderRadius: 6,
      backgroundColor: node.status === 'running'
        ? 'rgba(88,166,255,0.06)'
        : node.status === 'failed'
          ? 'rgba(248,81,73,0.06)'
          : 'transparent',
      borderLeft: `2px solid ${
        node.status === 'complete' ? '#3fb950'
        : node.status === 'failed' ? '#f85149'
        : node.status === 'running' ? '#58a6ff'
        : '#30363d'}`
    }}>
      <span style={{ fontSize: 14, marginTop: 1, minWidth: 16 }}>
        <NodeStatusIcon status={node.status} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontFamily: 'monospace', color: '#c9d1d9', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.file}
        </div>
        {node.status === 'running' && (
          <div style={{ fontSize: 11, color: '#58a6ff', marginTop: 2 }}>generating…</div>
        )}
        {node.error && (
          <div style={{ fontSize: 11, color: '#f85149', marginTop: 2 }}>{node.error}</div>
        )}
      </div>
      <span style={{
        fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 20, flexShrink: 0,
        backgroundColor: node.status === 'complete' ? 'rgba(63,185,80,0.15)' : node.status === 'failed' ? 'rgba(248,81,73,0.15)' : 'rgba(72,79,88,0.15)',
        color: node.status === 'complete' ? '#3fb950' : node.status === 'failed' ? '#f85149' : '#8b949e'
      }}>
        {node.status}
      </span>
    </div>
  );
}

function SessionProgress({ sessionId, onComplete }) {
  const [session, setSession] = useState(null);
  const [impact, setImpact]   = useState(null);
  const pollRef               = useRef(null);

  const poll = async () => {
    try {
      const data = await apiClient.getJson(`/projects/audit/fix/session/${sessionId}`);
      setSession(data);
      if (['complete', 'failed', 'partial'].includes(data.status)) {
        clearInterval(pollRef.current);
        try {
          const imp = await apiClient.getJson(`/projects/audit/fix/session/${sessionId}/impact`);
          setImpact(imp);
        } catch { /* non-fatal */ }
        if (onComplete) onComplete(data);
      }
    } catch { /* transient network error — keep polling */ }
  };

  useEffect(() => {
    poll();
    pollRef.current = setInterval(poll, 5000);
    return () => clearInterval(pollRef.current);
  }, [sessionId]);

  if (!session) return (
    <div style={{ padding: '16px 0', color: '#8b949e', fontSize: 13, textAlign: 'center' }}>
      ⟳ Connecting to session…
    </div>
  );

  const prog     = session.progress || {};
  const pct      = prog.percent_complete ?? 0;
  const riskMeta = RISK_META[impact?.risk_level] || RISK_META.none;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* Progress bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 12 }}>
          <span style={{ color: '#8b949e' }}>
            {prog.completed ?? 0} of {prog.total_nodes ?? 0} nodes
          </span>
          <span style={{ color: '#c9d1d9', fontWeight: 600 }}>{pct}%</span>
        </div>
        <div style={{ height: 4, borderRadius: 2, backgroundColor: '#21262d', overflow: 'hidden' }}>
          <div style={{
            height: '100%', borderRadius: 2, transition: 'width 0.4s ease',
            width: `${pct}%`,
            backgroundColor: session.status === 'failed' ? '#f85149' : session.status === 'complete' ? '#3fb950' : '#58a6ff'
          }} />
        </div>
      </div>

      {/* Node list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
        {(session.nodes || []).map(n => <NodeRow key={n.id} node={n} />)}
      </div>

      {/* Import warnings */}
      {session.import_warnings?.length > 0 && (
        <div style={{ padding: '10px 14px', borderRadius: 6, backgroundColor: 'rgba(210,153,34,0.08)', border: '1px solid rgba(210,153,34,0.25)', fontSize: 12 }}>
          <div style={{ color: '#d29922', fontWeight: 700, marginBottom: 6 }}>⚠ Import Warnings</div>
          {session.import_warnings.map((w, i) => (
            <div key={i} style={{ color: '#c9d1d9', marginBottom: 2 }}>{w}</div>
          ))}
        </div>
      )}

      {/* Impact Analysis */}
      {impact && (
        <div style={{ borderRadius: 8, border: `1px solid ${riskMeta.color}33`, backgroundColor: riskMeta.bg, overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', borderBottom: `1px solid ${riskMeta.color}22`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#c9d1d9' }}>💥 Impact Analysis</span>
            <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 9px', borderRadius: 20, backgroundColor: `${riskMeta.color}22`, color: riskMeta.color }}>
              {riskMeta.label} Risk
            </span>
          </div>
          <div style={{ padding: '10px 14px' }}>
            <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 8 }}>{impact.summary}</div>
            {Object.entries(impact.affected_dependents || {}).map(([file, deps]) => (
              <div key={file} style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 11, fontFamily: 'monospace', color: '#58a6ff', marginBottom: 4 }}>{file}</div>
                {deps.map(dep => (
                  <div key={dep} style={{ fontSize: 11, fontFamily: 'monospace', color: '#c9d1d9', paddingLeft: 12, marginBottom: 2 }}>↳ {dep}</div>
                ))}
              </div>
            ))}
            {impact.total_affected === 0 && (
              <div style={{ fontSize: 12, color: '#3fb950' }}>✓ No dependents found — isolated change.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Panel ──────────────────────────────────────────────────────────────

export default function AuditFixWorkflowPanel({ setPage }) {
  const [task, setTask]                       = useState(null);
  const [isDrafting, setIsDrafting]           = useState(false);
  const [isApplying, setIsApplying]           = useState(false);
  const [proposedChanges, setProposedChanges] = useState(null);
  const [error, setError]                     = useState(null);
  const [sessionId, setSessionId]             = useState(null);
  const [sessionDone, setSessionDone]         = useState(false);

  useEffect(() => {
    const pending = localStorage.getItem('pendingAuditFix');
    if (pending) {
      try { setTask(JSON.parse(pending)); } catch(e) {}
    }
  }, []);

  const handleDraftFix = async () => {
    if (!task) return;
    setIsDrafting(true);
    setError(null);
    setProposedChanges(null);
    setSessionId(null);
    setSessionDone(false);

    // The backend POST /audit/fix blocks until the session completes.
    // To show live progress, we poll the list_sessions endpoint to discover the newly created session.
    const pollInterval = setInterval(async () => {
      try {
        const res = await apiClient.getJson(`/projects/audit/fix/sessions?project_name=${task.project_name}&limit=1`);
        if (res.sessions && res.sessions.length > 0) {
          const latest = res.sessions[0];
          const ageMs = Date.now() - new Date(latest.created_at).getTime();
          // If it was created recently and is active, it's our session
          if (latest.status === 'in_progress' && ageMs < 60000) {
            setSessionId(latest.session_id);
            clearInterval(pollInterval);
          }
        }
      } catch (e) { /* ignore */ }
    }, 2000);

    try {
      const data = await apiClient.postJson('/projects/audit/fix', {
        project_name: task.project_name,
        task: task.task,
        likely_files: task.likely_files || []
      });
      clearInterval(pollInterval);
      
      const payload = data.proposed_changes || data;
      setProposedChanges(payload.proposed_changes || payload);
      if (payload.session_id) {
        setSessionId(payload.session_id);
      }
    } catch (err) { 
      clearInterval(pollInterval);
      setError(err.message); 
    }
    setIsDrafting(false);
  };

  const handleApplyFix = async () => {
    setIsApplying(true);
    setError(null);
    try {
      const payloadToApply = proposedChanges.proposed_changes ? proposedChanges.proposed_changes : proposedChanges;
      const res = await apiClient.postJson('/projects/audit/fix/apply', {
        project_name: task.project_name,
        task: task.task,
        changes: payloadToApply
      });
      alert('Fix applied successfully!');
      localStorage.removeItem('pendingAuditFix');
      setPage('auditor');
    } catch (err) { setError(err.message); }
    setIsApplying(false);
  };

  const renderDiffLine = (line, index) => {
    if (line.startsWith('+')) return <div key={index} style={{ backgroundColor: '#2ea04322', color: '#3fb950', padding: '0 8px', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{line}</div>;
    if (line.startsWith('-')) return <div key={index} style={{ backgroundColor: '#f8514922', color: '#ff7b72', padding: '0 8px', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{line}</div>;
    return <div key={index} style={{ padding: '0 8px', color: '#8b949e', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>{line}</div>;
  };

  if (!task) return (
    <div style={{ padding: '40px', textAlign: 'center', color: '#8b949e', fontFamily: "'Inter', sans-serif" }}>
      <h3>No Pending Fix</h3>
      <p>Go to the Project Auditor and click "Fix with AI" on a queue item.</p>
      <button onClick={() => setPage('auditor')} style={{ padding: '8px 16px', background: '#1f6feb', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', marginTop: '16px' }}>
        Go to Auditor
      </button>
    </div>
  );

  return (
    <div style={{ display: 'flex', height: '100%', flexDirection: 'column', padding: '20px', fontFamily: "'Inter', sans-serif" }}>

      {/* Header */}
      <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: '24px', margin: '0 0 4px 0', color: '#e6edf3' }}>Audit Fix Workflow</h2>
          <p style={{ margin: 0, color: '#8b949e', fontSize: '14px' }}>Review and apply AI-generated fixes.</p>
        </div>
        <button onClick={() => setPage('auditor')} style={{ padding: '6px 12px', background: 'transparent', color: '#8b949e', border: '1px solid #30363d', borderRadius: '6px', cursor: 'pointer' }}>
          ← Back to Auditor
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', flex: 1, minHeight: 0 }}>

        {/* Left Pane: Auditor Task */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', margin: 0, overflow: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <span style={{ backgroundColor: '#1f6feb22', color: '#58a6ff', fontSize: '12px', fontWeight: 700, padding: '2px 8px', borderRadius: '4px' }}>
              Priority {task.priority}
            </span>
            <h3 style={{ margin: 0, fontSize: '16px', color: '#e6edf3' }}>Target Fix</h3>
          </div>

          <div style={{ fontSize: '14px', color: '#c9d1d9', marginBottom: '24px', lineHeight: 1.6 }}>{task.task}</div>

          <h4 style={{ fontSize: '13px', color: '#8b949e', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Likely Files</h4>
          <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 32px 0', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {task.likely_files?.map(f => (
              <li key={f} style={{ backgroundColor: '#0d1117', border: '1px solid #30363d', padding: '8px 12px', borderRadius: '6px', fontFamily: 'monospace', fontSize: '12px', color: '#e6edf3' }}>{f}</li>
            ))}
          </ul>

          <div style={{ marginTop: 'auto' }}>
            {!sessionId ? (
              <button
                onClick={handleDraftFix}
                disabled={isDrafting}
                style={{ width: '100%', padding: '14px', borderRadius: '8px', fontSize: '15px', fontWeight: 600, backgroundColor: isDrafting ? '#30363d' : '#1f6feb', color: '#ffffff', border: 'none', cursor: isDrafting ? 'wait' : 'pointer', transition: 'all 0.2s', boxShadow: isDrafting ? 'none' : '0 4px 14px 0 rgba(31, 111, 235, 0.39)' }}
              >
                {isDrafting ? '🧠 Agent is drafting code...' : '✨ Draft Fix with AI'}
              </button>
            ) : sessionDone ? (
              <button onClick={() => setPage('auditor')} style={{ width: '100%', padding: '14px', borderRadius: '8px', fontSize: '15px', fontWeight: 600, backgroundColor: '#238636', color: '#fff', border: 'none', cursor: 'pointer' }}>
                ✓ Done — Back to Auditor
              </button>
            ) : (
              <div style={{ padding: '12px', borderRadius: 8, backgroundColor: 'rgba(88,166,255,0.06)', border: '1px solid rgba(88,166,255,0.2)', textAlign: 'center', fontSize: 13, color: '#58a6ff' }}>
                ⟳ Session running…
              </div>
            )}
          </div>

          {error && (
            <div style={{ marginTop: '16px', padding: '12px', borderRadius: '8px', backgroundColor: '#f8717115', border: '1px solid #f8717133', color: '#fca5a5', fontSize: '13px' }}>
              {error}
            </div>
          )}
        </div>

        {/* Right Pane: Diff / Session Progress + Impact */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', margin: 0, overflow: 'hidden', padding: 0 }}>
          <div style={{ padding: '20px 24px', borderBottom: '1px solid #30363d', backgroundColor: '#161b22', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0, fontSize: '16px', color: '#e6edf3' }}>
              {sessionId ? 'Session Progress' : 'Proposed Changes'}
            </h3>
            {proposedChanges && !sessionId && (
              <button
                onClick={handleApplyFix}
                disabled={isApplying}
                style={{ padding: '8px 16px', borderRadius: '6px', fontSize: '13px', fontWeight: 700, backgroundColor: '#238636', color: '#ffffff', border: '1px solid #2ea043', cursor: isApplying ? 'wait' : 'pointer', boxShadow: '0 0 10px 0 rgba(46, 160, 67, 0.5)' }}
              >
                {isApplying ? '⟳ Applying…' : 'Apply Fix to Codebase'}
              </button>
            )}
          </div>

          <div style={{ flex: 1, overflow: 'auto', backgroundColor: '#0d1117', padding: '16px' }}>
            {sessionId ? (
              <SessionProgress
                sessionId={sessionId}
                onComplete={(s) => setSessionDone(['complete', 'partial'].includes(s.status))}
              />
            ) : !proposedChanges ? (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#4b5563', fontSize: '13px' }}>
                {isDrafting ? 'Generating diff...' : 'Click "Draft Fix with AI" to generate the code patch.'}
              </div>
            ) : (
              <div style={{ fontSize: '13px', lineHeight: 1.5 }}>
                {typeof proposedChanges === 'string'
                  ? proposedChanges.split('\n').map((line, i) => renderDiffLine(line, i))
                  : JSON.stringify(proposedChanges, null, 2).split('\n').map((line, i) => renderDiffLine(line, i))
                }
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}


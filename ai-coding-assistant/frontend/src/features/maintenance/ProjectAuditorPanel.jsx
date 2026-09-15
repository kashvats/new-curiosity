import React, { useState, useEffect } from 'react';
import { apiClient } from '../../api/client';

export default function ProjectAuditorPanel({ setPage, injectedProjectName }) {
  const [isAuditing, setIsAuditing] = useState(false);
  const [report, setReport] = useState(() => {
    const saved = localStorage.getItem(`lastAuditReport_${injectedProjectName}`);
    return saved ? JSON.parse(saved) : null;
  });
  const [error, setError] = useState(null);

  const handleAudit = async () => {
    setIsAuditing(true);
    setError(null);
    setReport(null);
    
    try {
      const data = await apiClient.postJson('/projects/audit/run', { project_name: injectedProjectName });
      setReport(data);
      localStorage.setItem(`lastAuditReport_${injectedProjectName}`, JSON.stringify(data));
    } catch (err) {
      setError(err.message);
    }
    setIsAuditing(false);
  };

  const getSeverityColor = (sev) => {
    switch (sev?.toLowerCase()) {
      case 'critical': return '#f87171';
      case 'high': return '#fb923c';
      case 'medium': return '#fbbf24';
      case 'low': return '#60a5fa';
      default: return '#9ca3af';
    }
  };

  const getStatusColor = (status) => {
    switch (status?.toLowerCase()) {
      case 'critical': return '#f87171';
      case 'poor': return '#fb923c';
      case 'warning': return '#fbbf24';
      case 'good': return '#34d399';
      default: return '#9ca3af';
    }
  };

  const executeFix = (item) => {
    try {
      localStorage.setItem('pendingAuditFix', JSON.stringify({ ...item, project_name: injectedProjectName }));
      if (typeof setPage === 'function') {
        setPage('auditfix');
      } else {
        alert("Error: setPage is not a function. The Workspace is not passing the routing prop correctly.");
      }
    } catch (err) {
      alert("Error saving fix context: " + err.message);
    }
  };

  return (
    <div style={{ padding: '20px', fontFamily: "'Inter', sans-serif" }}>
      <div style={{ marginBottom: '24px' }}>
        <h2 style={{ fontSize: '24px', margin: '0 0 8px 0', color: '#e6edf3' }}>Autonomous Project Auditor</h2>
        <p style={{ margin: 0, color: '#8b949e', fontSize: '14px' }}>
          Run a high-level master audit aggregating metrics across the Architecture Map and Error Logs to automatically queue safe fixes.
        </p>
      </div>

      <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h3 style={{ margin: '0 0 4px 0', color: '#e6edf3', fontSize: '16px' }}>Target: {injectedProjectName}</h3>
          <p style={{ margin: 0, color: '#8b949e', fontSize: '13px' }}>Click below to scan this project for vulnerabilities, architecture flaws, and dead code.</p>
        </div>
        <button 
          onClick={handleAudit}
          disabled={isAuditing}
          style={{
            padding: '10px 24px', borderRadius: '6px', fontSize: '14px', fontWeight: 600,
            backgroundColor: isAuditing ? '#1f6feb88' : '#1f6feb', color: '#ffffff',
            border: 'none', cursor: isAuditing ? 'wait' : 'pointer', transition: 'all 0.2s'
          }}
        >
          {isAuditing ? 'Auditing Codebase (This may take up to 10 minutes)...' : 'Run Master Audit'}
        </button>
      </div>
        
        {error && (
          <div style={{ marginTop: '20px', padding: '16px', borderRadius: '8px', backgroundColor: '#f8717115', border: '1px solid #f8717133', color: '#fca5a5' }}>
            <strong style={{ display: 'block', marginBottom: '4px' }}>Audit Failed:</strong>
            {error}
          </div>
        )}

      {report && (
        <div style={{ marginTop: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Header */}
          <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderColor: `${getStatusColor(report.overall_status)}44`, borderLeftWidth: '4px', borderLeftColor: getStatusColor(report.overall_status) }}>
            <div>
              <h3 style={{ margin: '0 0 4px 0', fontSize: '18px', color: '#e6edf3' }}>Audit Complete</h3>
              <p style={{ margin: 0, color: '#8b949e', fontSize: '13px' }}>{report.summary}</p>
            </div>
            <div style={{ 
              padding: '8px 16px', borderRadius: '20px', fontWeight: 800, textTransform: 'uppercase', fontSize: '12px',
              backgroundColor: `${getStatusColor(report.overall_status)}15`, color: getStatusColor(report.overall_status)
            }}>
              Health: {report.overall_status}
            </div>
          </div>

          {/* Findings */}
          <div>
            <h3 style={{ fontSize: '16px', color: '#e6edf3', marginBottom: '12px' }}>Vulnerabilities & Findings</h3>
            {(!report.findings || report.findings.length === 0) ? (
              <div className="card" style={{ textAlign: 'center', color: '#8b949e', padding: '30px' }}>No findings detected! Your codebase is pristine.</div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '16px' }}>
                {report.findings.map((f, i) => (
                  <div key={i} className="card" style={{ borderTopWidth: '3px', borderTopColor: getSeverityColor(f.severity), padding: '16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                      <span style={{ fontSize: '11px', fontWeight: 700, color: getSeverityColor(f.severity), textTransform: 'uppercase' }}>
                        {f.severity} Severity
                      </span>
                      <span style={{ fontSize: '11px', color: '#8b949e', backgroundColor: '#21262d', padding: '2px 8px', borderRadius: '10px' }}>
                        {f.category}
                      </span>
                    </div>
                    <div style={{ fontSize: '14px', fontWeight: 600, color: '#e6edf3', marginBottom: '8px' }}>{f.problem}</div>
                    <div style={{ fontSize: '12px', color: '#8b949e' }}>{f.recommended_action}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Fix Queue */}
          <div>
            <h3 style={{ fontSize: '16px', color: '#e6edf3', marginBottom: '12px' }}>Actionable Fix Queue</h3>
            {(!report.fix_queue || report.fix_queue.length === 0) ? (
              <div className="card" style={{ textAlign: 'center', color: '#8b949e', padding: '30px' }}>No actionable fixes required.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {report.fix_queue.map((q, i) => (
                  <div key={i} className="card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', gap: '20px' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '6px' }}>
                        <span style={{ backgroundColor: '#1f6feb22', color: '#58a6ff', fontSize: '11px', fontWeight: 700, padding: '2px 8px', borderRadius: '4px' }}>
                          P{q.priority}
                        </span>
                        <span style={{ fontSize: '15px', fontWeight: 600, color: '#e6edf3' }}>{q.task}</span>
                      </div>
                      <div style={{ fontSize: '12px', color: '#8b949e' }}>
                        Target files: {q.likely_files?.map(f => <span key={f} style={{ backgroundColor: '#21262d', padding: '2px 6px', borderRadius: '4px', margin: '0 4px', fontFamily: 'monospace' }}>{f}</span>)}
                      </div>
                    </div>
                    <button 
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        executeFix(q);
                      }}
                      style={{
                        padding: '10px 20px', borderRadius: '6px', fontSize: '13px', fontWeight: 600,
                        backgroundColor: '#10b981', color: '#ffffff', border: 'none', cursor: 'pointer',
                        boxShadow: '0 4px 14px 0 rgba(16, 185, 129, 0.39)', flexShrink: 0
                      }}>
                      ⚡ Auto-Fix Bug
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

        </div>
      )}
    </div>
  );
}

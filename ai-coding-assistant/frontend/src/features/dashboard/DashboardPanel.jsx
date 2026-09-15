/**
 * DashboardPanel.jsx — Autonomous Project Auditor Dashboard.
 *
 * Shows:
 *   - Recent Audit Reports
 *   - Codebase Indexing Status
 *   - System health ring (Backend, Ollama, Qdrant)
 *   - Quick navigation cards to Auditor features
 */
import React, { useState, useEffect, useCallback } from 'react';
import { apiClient } from '../../api/client';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function timeAgo(iso) {
  if (!iso) return '';
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function ServiceDot({ status, label, detail }) {
  const color = status === 'ok' ? '#34d399' : status === 'loading' ? '#f59e0b' : '#f87171';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 0' }}>
      <div style={{
        width: '10px', height: '10px', borderRadius: '50%',
        backgroundColor: color,
        boxShadow: `0 0 8px ${color}88`,
        flexShrink: 0,
        animation: status === 'loading' ? 'pulse 1.5s ease-in-out infinite' : 'none',
      }} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: '13px', color: '#e6edf3', fontWeight: 500 }}>{label}</div>
        {detail && <div style={{ fontSize: '11px', color: '#4b5563', marginTop: '1px' }}>{detail}</div>}
      </div>
      <span style={{
        fontSize: '10px', padding: '2px 7px', borderRadius: '10px',
        backgroundColor: `${color}22`, color, border: `1px solid ${color}55`,
        fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em',
      }}>
        {status === 'loading' ? '...' : status}
      </span>
    </div>
  );
}

function QuickNavCard({ icon, label, desc, onClick, accent = '#1d4ed8' }) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: '16px', borderRadius: '10px', cursor: 'pointer',
        border: `1px solid ${hover ? accent + '88' : '#21262d'}`,
        backgroundColor: hover ? `${accent}18` : '#0d1117',
        transition: 'all 0.18s',
        display: 'flex', alignItems: 'center', gap: '14px',
      }}
    >
      <div style={{ fontSize: '24px', width: '40px', textAlign: 'center', flexShrink: 0 }}>{icon}</div>
      <div>
        <div style={{ fontSize: '13px', fontWeight: 600, color: '#e6edf3' }}>{label}</div>
        <div style={{ fontSize: '11px', color: '#6e7681', marginTop: '2px' }}>{desc}</div>
      </div>
    </div>
  );
}

// ─── Main ────────────────────────────────────────────────────────────────────

export default function DashboardPanel({ setPage }) {
  const [health, setHealth] = useState({ backend: 'loading', qdrant: 'loading', ollama: 'loading' });
  const [reports, setReports] = useState([]);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchAll = useCallback(async () => {
    // Health checks
    try {
      await apiClient.getJson('/health');
      setHealth(h => ({ ...h, backend: 'ok' }));
    } catch (_) {
      setHealth(h => ({ ...h, backend: 'error' }));
    }

    try {
      const q = await apiClient.getJson('/qdrant/health');
      setHealth(h => ({ ...h, qdrant: q.status || 'ok' }));
    } catch (_) {
      setHealth(h => ({ ...h, qdrant: 'error' }));
    }
    
    // Fetch recent audit reports
    try {
      const auditData = await apiClient.getJson('/projects/audit/reports');
      setReports(auditData.reports || []);
    } catch (_) {}

    setLastUpdate(new Date());
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 10000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const allSystemsOk = health.backend === 'ok' && health.qdrant === 'ok';
  
  // Calculate stats from reports
  const latestReport = reports[0];
  const latestHealth = latestReport?.overall_status || 'unknown';
  const totalAudits = reports.length;
  
  const getHealthColor = (status) => {
    switch (status) {
      case 'critical': return '#f87171';
      case 'warning': return '#f59e0b';
      case 'good': return '#34d399';
      default: return '#60a5fa';
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', fontFamily: "'Inter', 'Segoe UI', sans-serif" }}>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.35; }
        }
        .auditor-gradient {
          background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }
      `}</style>

      {/* ── TOP ROW: Auditor Hero + Health ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: '14px', alignItems: 'stretch' }}>
        
        {/* Hero Card */}
        <div style={{
          padding: '28px', backgroundColor: '#0d1117',
          border: '1px solid #1e3a8a44', borderRadius: '12px',
          display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
          position: 'relative', overflow: 'hidden'
        }}>
          {/* Subtle background glow */}
          <div style={{
            position: 'absolute', top: '-50px', right: '-50px', width: '200px', height: '200px',
            background: 'radial-gradient(circle, rgba(59,130,246,0.15) 0%, rgba(0,0,0,0) 70%)',
            pointerEvents: 'none'
          }} />
          
          <div>
            <h1 style={{ margin: '0 0 8px 0', fontSize: '28px', fontWeight: 800 }} className="auditor-gradient">
              Autonomous Project Auditor
            </h1>
            <p style={{ margin: '0', color: '#9ca3af', fontSize: '14px', maxWidth: '80%' }}>
              Your AI-powered QA Engineer. Scanning for architectural flaws, predicting bug blast radiuses, and generating automated code fixes.
            </p>
          </div>
          
          <div style={{ display: 'flex', gap: '16px', marginTop: '24px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <span style={{ fontSize: '11px', color: '#6b7280', textTransform: 'uppercase', letterSpacing: '1px' }}>Project Health</span>
              <span style={{ fontSize: '22px', fontWeight: 700, color: getHealthColor(latestHealth), textTransform: 'capitalize' }}>
                {latestHealth}
              </span>
            </div>
            <div style={{ width: '1px', backgroundColor: '#1f2937' }} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <span style={{ fontSize: '11px', color: '#6b7280', textTransform: 'uppercase', letterSpacing: '1px' }}>Total Audits</span>
              <span style={{ fontSize: '22px', fontWeight: 700, color: '#e5e7eb' }}>
                {totalAudits}
              </span>
            </div>
          </div>
        </div>

        {/* Health panel */}
        <div style={{
          padding: '20px', backgroundColor: '#0d1117',
          border: `1px solid ${allSystemsOk ? '#34d39933' : '#f8717133'}`, borderRadius: '12px',
          borderLeft: `4px solid ${allSystemsOk ? '#34d399' : '#f87171'}`,
        }}>
          <div style={{ fontSize: '12px', color: '#6e7681', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '12px' }}>
            System Infrastructure
          </div>
          <ServiceDot status={health.backend} label="Backend API" />
          <ServiceDot status={health.qdrant}  label="Codebase Vector DB" />
          <ServiceDot status={health.ollama || 'unknown'} label="Ollama Runtime" detail="Local GPU Inference" />
          {lastUpdate && (
            <div style={{ fontSize: '10px', color: '#374151', marginTop: '12px', textAlign: 'right' }}>
              updated {lastUpdate.toLocaleTimeString()}
            </div>
          )}
        </div>
      </div>

      {/* ── MIDDLE: Quick Nav + Audit History ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: '14px', alignItems: 'start' }}>

        {/* Quick nav */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ fontSize: '12px', color: '#6e7681', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px' }}>
            Audit Actions
          </div>
          <QuickNavCard icon="🛡️" label="Run Project Audit" desc="Full codebase health check" accent="#3b82f6"
            onClick={() => setPage('auditor')} />
          <QuickNavCard icon="🔧" label="Audit Fix Workflow" desc="Execute AI-generated patches" accent="#10b981"
            onClick={() => setPage('auditfix')} />
          <QuickNavCard icon="💥" label="Impact Analysis" desc="Calculate blast radius" accent="#f59e0b"
            onClick={() => setPage('impact')} />
          <QuickNavCard icon="🏗️" label="Architecture Map" desc="Visualize codebase structure" accent="#8b5cf6"
            onClick={() => setPage('architecture')} />
        </div>
        
        {/* Recent Audits */}
        <div style={{ padding: '20px', backgroundColor: '#0d1117', border: '1px solid #21262d', borderRadius: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div style={{ fontSize: '14px', fontWeight: 600, color: '#e6edf3' }}>📜 Recent Health Audits</div>
            <button onClick={fetchAll} style={{
              fontSize: '11px', color: '#6e7681', backgroundColor: 'transparent',
              border: '1px solid #21262d', borderRadius: '6px', padding: '4px 12px', cursor: 'pointer',
            }}>↻ Refresh</button>
          </div>
          
          {reports.length === 0 ? (
             <div style={{ color: '#4b5563', fontSize: '13px', padding: '30px', textAlign: 'center' }}>
               No audits run yet. Go to Project Auditor to run your first scan.
             </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {reports.slice(0, 5).map((r, i) => {
                const healthColor = getHealthColor(r.overall_status);
                return (
                  <div key={r.id} style={{
                    display: 'flex', alignItems: 'center', gap: '12px',
                    padding: '12px 0',
                    borderBottom: i < Math.min(reports.length, 5) - 1 ? '1px solid #1f2937' : 'none',
                  }}>
                    <span style={{ color: healthColor, fontSize: '16px', flexShrink: 0 }}>
                      {r.overall_status === 'good' ? '✅' : r.overall_status === 'warning' ? '⚠️' : '🚨'}
                    </span>
                    <span style={{ fontSize: '13px', color: '#d1d5db', flex: 1 }}>
                      Project: <strong>{r.scope}</strong>
                    </span>
                    <span style={{ fontSize: '11px', color: '#6b7280', flexShrink: 0 }}>
                      {timeAgo(r.created_at)}
                    </span>
                    <button 
                      onClick={() => setPage('auditor')}
                      style={{
                        fontSize: '11px', padding: '4px 10px', borderRadius: '6px',
                        backgroundColor: '#1f2937', color: '#e5e7eb', border: '1px solid #374151',
                        cursor: 'pointer'
                      }}>
                      View Details
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}

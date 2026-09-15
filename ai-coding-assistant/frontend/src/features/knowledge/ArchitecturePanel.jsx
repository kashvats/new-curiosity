import React, { useState, useEffect } from 'react';
import { apiClient } from '../../api/client';

export default function ArchitecturePanel({ injectedProjectName }) {
  const [summary, setSummary] = useState(() => {
    const saved = localStorage.getItem(`lastArchitectureMap_${injectedProjectName}`);
    return saved ? JSON.parse(saved) : null;
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [filePath, setFilePath] = useState('');
  const [impactData, setImpactData] = useState(null);
  const [impactLoading, setImpactLoading] = useState(false);

  const handleScan = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.postJson('/architecture/scan', { project_name: injectedProjectName });
      setSummary(data);
      localStorage.setItem(`lastArchitectureMap_${injectedProjectName}`, JSON.stringify(data));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const checkImpact = async () => {
    if (!filePath) return;
    setImpactLoading(true);
    try {
      const data = await apiClient.getJson(`/architecture/file-impact?file_path=${encodeURIComponent(filePath)}`);
      setImpactData(data);
    } catch (err) {
      alert("Failed: " + err.message);
    } finally {
      setImpactLoading(false);
    }
  };

  return (
    <div style={{padding: '20px', borderRadius: '8px', marginBottom: '20px'}}>
      <h2>Architecture Understanding</h2>
      <p style={{fontSize: '14px'}}>Scan workspace to give the Planner context about file dependencies and roles.</p>

      <div style={{marginBottom: '20px'}}>
        <button onClick={handleScan} disabled={loading} style={{padding: '10px 20px', borderRadius: '6px', cursor: loading ? 'wait' : 'pointer', fontWeight: 600, backgroundColor: loading ? '#1f6feb88' : '#1f6feb', color: '#ffffff', border: 'none'}}>
          {loading ? "Generating Architecture Map (This may take several minutes)..." : "Scan Workspace Architecture"}
        </button>
        {error && <div style={{marginTop: '10px', padding: '12px', backgroundColor: '#f8717115', border: '1px solid #f8717133', color: '#fca5a5', borderRadius: '6px'}}>{error}</div>}
      </div>

      {summary && summary.architecture_map_md && (
        <div className="card" style={{padding: '20px'}}>
          <h3 style={{marginTop: 0, borderBottom: '1px solid #30363d', paddingBottom: '15px', color: '#e6edf3'}}>Generated Architecture Map</h3>
          <pre style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word', fontFamily: 'monospace', fontSize: '14px', lineHeight: '1.5', color: '#c9d1d9' }}>
            {summary.architecture_map_md}
          </pre>
        </div>
      )}
    </div>
  );
}

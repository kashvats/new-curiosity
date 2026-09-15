import React, { useState, useEffect } from 'react';
import { apiClient } from '../../api/client';

export default function ImpactAnalysisPanel({ injectedProjectName }) {
  const [task, setTask] = useState('');
  const [filePaths, setFilePaths] = useState('');
  
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  const [history, setHistory] = useState([]);
  
  const fetchHistory = async () => {
    try {
      const data = await apiClient.getJson('/impact/reports');
      setHistory(data.reports || []);
    } catch (err) {
      console.error("Failed to load history", err);
    }
  };
  
  useEffect(() => {
    fetchHistory();
  }, []);

  const handleAnalyze = async () => {
    if (!task) return alert("Task is required");
    
    setLoading(true);
    setError(null);
    setReport(null);
    
    try {
      const pathsArray = filePaths.split(',').map(s => s.trim()).filter(s => s);
      const data = await apiClient.postJson('/impact/analyze', {
        task,
        file_paths: pathsArray,
        project_name: injectedProjectName
      });
      setReport(data);
      fetchHistory();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadReport = async (id) => {
    try {
      const data = await apiClient.getJson(`/impact/reports/${id}`);
      setReport(data.report);
    } catch (err) {
      alert("Failed to load report: " + err.message);
    }
  };

  const riskColor = report?.risk_level === 'high' ? '#ffebee' : report?.risk_level === 'medium' ? '#fff8e1' : '#e8f5e9';
  const riskBorder = report?.risk_level === 'high' ? '#f44336' : report?.risk_level === 'medium' ? '#ff9800' : '#4caf50';

  return (
    <div style={{padding: '20px', borderRadius: '8px', marginBottom: '20px'}}>
      <h2>Impact Analysis Engine</h2>
      <p style={{fontSize: '14px'}}>Analyze the blast radius of a planned change before touching any files.</p>
      
      <div style={{display: 'grid', gridTemplateColumns: '1fr 300px', gap: '20px'}}>
        <div>
          {report && report.impact_report_md && (
            <div className="card" style={{marginBottom: '20px', padding: '20px'}}>
              <h3 style={{marginTop: 0, borderBottom: '1px solid #30363d', paddingBottom: '15px', color: '#e6edf3'}}>Generated Impact Analysis</h3>
              <pre style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word', fontFamily: 'monospace', fontSize: '14px', lineHeight: '1.5', color: '#c9d1d9' }}>
                {report.impact_report_md}
              </pre>
            </div>
          )}
          <div style={{marginBottom: '15px'}}>
            <label style={{display: 'block', fontWeight: 'bold', marginBottom: '5px'}}>Planned Task:</label>
            <textarea 
              value={task} 
              onChange={e => setTask(e.target.value)} 
              placeholder="e.g. Add authentication to document upload"
              style={{width: '100%', padding: '10px', height: '80px', borderRadius: '4px'}}
            />
          </div>
          
          <div style={{marginBottom: '15px'}}>
            <label style={{display: 'block', fontWeight: 'bold', marginBottom: '5px'}}>Target Files (comma separated):</label>
            <textarea 
              value={filePaths} 
              onChange={e => setFilePaths(e.target.value)} 
              placeholder="e.g. backend/app/documents.py, frontend/src/features/documents/DocumentUpload.jsx"
              style={{width: '100%', padding: '10px', height: '80px', borderRadius: '4px'}}
            />
          </div>
          
          <button 
            onClick={handleAnalyze} 
            disabled={loading}
            style={{padding: '10px 20px', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold'}}
          >
            {loading ? "Analyzing..." : "Analyze Impact"}
          </button>
          
          {error && <div style={{marginTop: '10px'}}>{error}</div>}
          
          {report && (
            <div style={{marginTop: '20px', padding: '15px',  borderRadius: '4px'}}>
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px'}}>
                <h3 style={{margin: 0}}>Impact Report: {report.report_id || report.id}</h3>
                <span style={{padding: '4px 8px', borderRadius: '4px', fontWeight: 'bold'}}>
                  {report.risk_level.toUpperCase()} RISK ({(report.risk_score * 100).toFixed(0)}%)
                </span>
              </div>
              
              {report.warnings && report.warnings.length > 0 && (
                <div style={{padding: '10px', marginBottom: '15px'}}>
                  <strong>Warnings:</strong>
                  <ul style={{margin: '5px 0 0 0', paddingLeft: '20px', fontSize: '13px'}}>
                    {report.warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}
              
              <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px', fontSize: '13px'}}>
                <div>
                  <strong>Impacted Files ({report.impacted_files.length}):</strong>
                  <ul style={{paddingLeft: '20px', margin: '5px 0'}}>
                    {report.impacted_files.length === 0 && <li>None</li>}
                    {report.impacted_files.map((f, i) => <li key={i}>{f}</li>)}
                  </ul>
                </div>
                <div>
                  <strong>Impacted Routes ({report.impacted_routes.length}):</strong>
                  <ul style={{paddingLeft: '20px', margin: '5px 0'}}>
                    {report.impacted_routes.length === 0 && <li>None</li>}
                    {report.impacted_routes.map((f, i) => <li key={i}>{f}</li>)}
                  </ul>
                </div>
                <div>
                  <strong>Impacted Components ({report.impacted_components.length}):</strong>
                  <ul style={{paddingLeft: '20px', margin: '5px 0'}}>
                    {report.impacted_components.length === 0 && <li>None</li>}
                    {report.impacted_components.map((f, i) => <li key={i}>{f}</li>)}
                  </ul>
                </div>
                <div>
                  <strong>Impacted DB Tables ({report.impacted_tables.length}):</strong>
                  <ul style={{paddingLeft: '20px', margin: '5px 0'}}>
                    {report.impacted_tables.length === 0 && <li>None</li>}
                    {report.impacted_tables.map((f, i) => <li key={i}>{f}</li>)}
                  </ul>
                </div>
              </div>
              
              <div style={{marginTop: '15px'}}>
                <strong>Related Tests to Run:</strong>
                <ul style={{paddingLeft: '20px', margin: '5px 0', fontSize: '13px'}}>
                  {report.impacted_tests.length === 0 && <li>None identified</li>}
                  {report.impacted_tests.map((f, i) => <li key={i}>{f}</li>)}
                </ul>
              </div>
              
              <div style={{marginTop: '15px', padding: '10px', borderRadius: '4px'}}>
                <strong>AI Recommendations:</strong>
                <ul style={{paddingLeft: '20px', margin: '5px 0', fontSize: '13px'}}>
                  {report.recommendations.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </div>
            </div>
          )}
        </div>
        
        <div>
          <h4 style={{marginTop: 0}}>Recent Reports</h4>
          <div style={{maxHeight: '400px', overflowY: 'auto', borderRadius: '4px'}}>
            {history.length === 0 && <p style={{padding: '10px', fontSize: '13px'}}>No reports yet.</p>}
            {history.map(h => (
              <div key={h.id} style={{padding: '10px', cursor: 'pointer'}} onClick={() => loadReport(h.id)}>
                <div style={{fontSize: '12px', fontWeight: 'bold'}}>{h.task.substring(0, 30)}...</div>
                <div style={{fontSize: '11px', display: 'flex', justifyContent: 'space-between', marginTop: '5px'}}>
                  <span>{new Date(h.created_at).toLocaleDateString()}</span>
                  <span style={{fontWeight: 'bold'}}>{h.risk_level.toUpperCase()}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

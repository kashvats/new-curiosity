import React, { useState } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function RegressionDetectionPanel() {
  const [baselinePath, setBaselinePath] = useState('');
  const [currentPath, setCurrentPath] = useState('');
  const [restorePointId, setRestorePointId] = useState('');
  
  const [isDetecting, setIsDetecting] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);

  const handleDetect = async (e) => {
    e.preventDefault();
    if (!baselinePath.trim() || !currentPath.trim()) {
      return alert("Both baseline and current paths are required for explicit detection.");
    }
    
    setIsDetecting(true);
    setError(null);
    setReport(null);
    try {
      const payload = {
        baseline_debug_report_path: baselinePath,
        current_debug_report_path: currentPath,
        restore_point_id: restorePointId || null
      };
      const data = await apiClient.postJson('/regression/detect', payload);
      setReport(data);
    } catch (err) {
      setError(err.message);
    }
    setIsDetecting(false);
  };

  const handleDetectLatest = async () => {
    setIsDetecting(true);
    setError(null);
    setReport(null);
    try {
      const payload = {
        baseline_restore_point_id: restorePointId || null
      };
      const data = await apiClient.postJson('/regression/detect-latest', payload);
      setReport(data);
      // Auto-fill paths for context
      if (data.status === 'ok') {
        const fullReport = await apiClient.getJson(`/regression/reports/${data.report_id}`);
        if (fullReport && fullReport.report) {
          setBaselinePath(fullReport.report.baseline_debug_report_path);
          setCurrentPath(fullReport.report.current_debug_report_path);
        }
      }
    } catch (err) {
      setError(err.message);
    }
    setIsDetecting(false);
  };

  const StatusItem = ({ item, isRegression }) => (
    <div style={{padding: '10px', marginBottom: '10px',  borderRadius: '4px', boxShadow: '0 1px 3px rgba(0,0,0,0.1)'}}>
      <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: '5px'}}>
        <strong>{item.feature_id}</strong>
        <span style={{fontSize: '12px'}}>
          {item.previous_status} ➔ <span style={{fontWeight: 'bold'}}>{item.current_status}</span>
        </span>
      </div>
      {item.suggested_start_point && (
        <div style={{fontSize: '12px', marginTop: '5px'}}>
          <em>Suggestion: {item.suggested_start_point}</em>
        </div>
      )}
    </div>
  );

  return (
    <Section title="Regression Detection" description="Compare debug reports to automatically detect newly broken features." >
      <form onSubmit={handleDetect} style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>
        <div style={{display: 'flex', gap: '15px'}}>
          <div style={{flex: 1}}>
            <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold', fontSize: '14px'}}>Baseline Debug Report Path:</label>
            <input 
              type="text" 
              value={baselinePath} 
              onChange={e => setBaselinePath(e.target.value)} 
              placeholder="/absolute/path/to/old_debug.json" 
              style={{width: '100%', padding: '8px', borderRadius: '4px', boxSizing: 'border-box'}}
            />
          </div>
          <div style={{flex: 1}}>
            <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold', fontSize: '14px'}}>Current Debug Report Path:</label>
            <input 
              type="text" 
              value={currentPath} 
              onChange={e => setCurrentPath(e.target.value)} 
              placeholder="/absolute/path/to/new_debug.json" 
              style={{width: '100%', padding: '8px', borderRadius: '4px', boxSizing: 'border-box'}}
            />
          </div>
        </div>
        
        <div>
          <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold', fontSize: '14px'}}>Restore Point ID (Optional):</label>
          <input 
            type="text" 
            value={restorePointId} 
            onChange={e => setRestorePointId(e.target.value)} 
            placeholder="Link to a specific restore point" 
            style={{width: '100%', padding: '8px', borderRadius: '4px', boxSizing: 'border-box'}}
          />
        </div>

        <div style={{display: 'flex', gap: '10px'}}>
          <LoadingButton type="submit" loading={isDetecting} text="Compare Explicit Paths"  />
          <LoadingButton 
            type="button" 
            onClick={handleDetectLatest} 
            loading={isDetecting} 
            text="Auto-Compare Latest Two Reports" 
             
          />
        </div>
      </form>

      {error && (
        <div style={{marginTop: '15px', padding: '10px', borderRadius: '4px'}}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {report && (
        <div style={{marginTop: '20px', padding: '20px', borderRadius: '8px'}}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px'}}>
            <h3 style={{margin: 0}}>Regression Report</h3>
            <span style={{fontSize: '12px', fontFamily: 'monospace'}}>ID: {report.report_id}</span>
          </div>

          <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '20px', marginBottom: '25px'}}>
            <div style={{padding: '15px', borderRadius: '6px', textAlign: 'center'}}>
              <strong style={{display: 'block', fontSize: '24px'}}>{report.summary.regressions}</strong>
              <span style={{fontSize: '13px', textTransform: 'uppercase', fontWeight: 'bold'}}>Regressions</span>
            </div>
            <div style={{padding: '15px', borderRadius: '6px', textAlign: 'center'}}>
              <strong style={{display: 'block', fontSize: '24px'}}>{report.summary.improvements}</strong>
              <span style={{fontSize: '13px', textTransform: 'uppercase', fontWeight: 'bold'}}>Improvements</span>
            </div>
            <div style={{padding: '15px', borderRadius: '6px', textAlign: 'center'}}>
              <strong style={{display: 'block', fontSize: '24px'}}>{report.summary.unchanged_failures}</strong>
              <span style={{fontSize: '13px', textTransform: 'uppercase', fontWeight: 'bold'}}>Unchanged Failures</span>
            </div>
          </div>

          {report.regressions?.length > 0 && (
            <div style={{marginBottom: '20px'}}>
              <h4 style={{margin: '0 0 10px 0', paddingBottom: '5px'}}>Detected Regressions (Needs Fix)</h4>
              {report.regressions.map((reg, idx) => <StatusItem key={idx} item={reg} isRegression={true} />)}
            </div>
          )}

          {report.improvements?.length > 0 && (
            <div style={{marginBottom: '20px'}}>
              <h4 style={{margin: '0 0 10px 0', paddingBottom: '5px'}}>Detected Improvements</h4>
              {report.improvements.map((imp, idx) => <StatusItem key={idx} item={imp} isRegression={false} />)}
            </div>
          )}

          {report.unchanged_failures?.length > 0 && (
            <div style={{marginBottom: '10px'}}>
              <h4 style={{margin: '0 0 10px 0', paddingBottom: '5px'}}>Unchanged Failures (Still broken)</h4>
              <ul style={{margin: 0, paddingLeft: '20px', fontSize: '13px'}}>
                {report.unchanged_failures.map((uf, idx) => (
                  <li key={idx}><strong>{uf.feature_id}</strong> (Status: {uf.current_status})</li>
                ))}
              </ul>
            </div>
          )}

          {report.summary.regressions === 0 && report.summary.improvements === 0 && report.summary.unchanged_failures === 0 && (
            <div style={{textAlign: 'center', padding: '20px'}}>
              No status changes detected between these reports.
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

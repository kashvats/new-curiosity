import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function CoverageAnalysisPanel() {
  const [report, setReport] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [warnings, setWarnings] = useState([]);
  
  const [lookupFile, setLookupFile] = useState('');
  const [lookupResult, setLookupResult] = useState(null);
  const [isLookingUp, setIsLookingUp] = useState(false);

  const fetchLatestReport = async () => {
    try {
      const data = await apiClient.getJson('/coverage/latest');
      if (data.status === 'ok') {
        setReport(data.report);
      }
    } catch (err) {
      // Silently ignore — no coverage report yet is normal on a fresh install
    }
  };

  useEffect(() => {
    fetchLatestReport();
  }, []);

  const handleAnalyze = async () => {
    setIsAnalyzing(true);
    setWarnings([]);
    try {
      const data = await apiClient.postJson('/coverage/analyze', {});
      if (data.status === 'ok' && data.warnings?.length > 0) {
        setWarnings(data.warnings);
      } else if (data.status === 'ok') {
        await fetchLatestReport();
        alert("Coverage analysis complete!");
      } else {
        setWarnings(data.warnings || [data.message || "Failed to analyze coverage"]);
      }
    } catch (err) {
      setWarnings([err.message]);
    }
    setIsAnalyzing(false);
  };

  const handleLookup = async (e) => {
    e.preventDefault();
    if (!lookupFile.trim()) return;
    
    setIsLookingUp(true);
    setLookupResult(null);
    try {
      const data = await apiClient.getJson(`/coverage/file?file_path=${encodeURIComponent(lookupFile)}`);
      setLookupResult(data);
    } catch (err) {
      alert(`Lookup failed: ${err.message}`);
    }
    setIsLookingUp(false);
  };

  return (
    <Section title="Coverage Analysis" description="Analyze test coverage reports and map them to the codebase." >
      <div style={{marginBottom: '20px'}}>
        <LoadingButton onClick={handleAnalyze} loading={isAnalyzing} loadingText="Scanning..." text="Scan for Coverage Reports"  />
        <p style={{fontSize: '12px', marginTop: '5px'}}>
          This will search the workspace for `coverage.xml` or `coverage-summary.json` and persist the stats.
        </p>
      </div>

      {warnings.length > 0 && (
        <div style={{padding: '10px', borderRadius: '4px', marginBottom: '20px'}}>
          <strong style={{display: 'block', marginBottom: '5px'}}>Warnings:</strong>
          <ul style={{margin: 0, paddingLeft: '20px'}}>
            {warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}

      {report && (
        <div style={{padding: '15px', borderRadius: '8px', marginBottom: '20px'}}>
          <h3 style={{margin: '0 0 10px 0'}}>Latest Report Summary</h3>
          <p style={{fontSize: '12px', margin: '0 0 10px 0'}}>Source: {report.source} | Scanned: {new Date(report.created_at).toLocaleString()}</p>
          
          <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '15px', marginBottom: '15px'}}>
            <div style={{padding: '10px', borderRadius: '4px', textAlign: 'center'}}>
              <strong style={{display: 'block', fontSize: '20px'}}>{report.summary.total_files}</strong>
              <span style={{fontSize: '12px'}}>Total Files</span>
            </div>
            <div style={{padding: '10px', borderRadius: '4px', textAlign: 'center'}}>
              <strong style={{display: 'block', fontSize: '20px'}}>
                {report.summary.average_coverage.toFixed(1)}%
              </strong>
              <span style={{fontSize: '12px'}}>Avg Coverage</span>
            </div>
            <div style={{padding: '10px', borderRadius: '4px', textAlign: 'center'}}>
              <strong style={{display: 'block', fontSize: '20px'}}>{report.summary.low_coverage_count}</strong>
              <span style={{fontSize: '12px'}}>Low/Uncovered Files</span>
            </div>
          </div>
          
          {report.low_coverage_files?.length > 0 && (
            <div>
              <strong>Low Coverage Files:</strong>
              <div style={{maxHeight: '150px', overflowY: 'auto', padding: '10px', marginTop: '5px', borderRadius: '4px'}}>
                <ul style={{margin: 0, paddingLeft: '20px', fontSize: '13px', fontFamily: 'monospace'}}>
                  {report.low_coverage_files.map((f, i) => <li key={i}>{f}</li>)}
                </ul>
              </div>
            </div>
          )}
        </div>
      )}

      <div style={{padding: '15px', borderRadius: '8px'}}>
        <h4 style={{margin: '0 0 10px 0'}}>File Coverage Lookup</h4>
        <form onSubmit={handleLookup} style={{display: 'flex', gap: '10px'}}>
          <input 
            type="text" 
            value={lookupFile} 
            onChange={e => setLookupFile(e.target.value)} 
            placeholder="e.g. backend/app/models.py" 
            style={{flex: 1, padding: '8px', borderRadius: '4px'}}
          />
          <LoadingButton type="submit" loading={isLookingUp} loadingText="Looking up..." text="Lookup" />
        </form>

        {lookupResult && (
          <div style={{marginTop: '15px', padding: '10px', borderRadius: '4px', fontSize: '14px'}}>
            <p style={{margin: '0 0 5px 0'}}><strong>File:</strong> {lookupResult.file_path}</p>
            <p style={{margin: '0 0 5px 0'}}><strong>Coverage:</strong> {lookupResult.coverage.toFixed(1)}%</p>
            <p style={{margin: '0 0 5px 0'}}><strong>Risk Level:</strong> <span style={{textTransform: 'capitalize'}}>{lookupResult.risk_level}</span></p>
            {lookupResult.uncovered_lines?.length > 0 && (
              <p style={{margin: 0, fontSize: '12px'}}>
                <strong>Uncovered Lines:</strong> {lookupResult.uncovered_lines.join(', ')}
              </p>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

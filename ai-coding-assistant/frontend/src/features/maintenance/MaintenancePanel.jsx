import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function MaintenancePanel() {
  const [report, setReport] = useState(null);
  const [models, setModels] = useState(null);
  const [storage, setStorage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const runChecks = async () => {
    setLoading(true);
    setError(null);
    try {
      const repData = await apiClient.getJson('/maintenance/report');
      setReport(repData);

      const modData = await apiClient.getJson('/maintenance/models');
      setModels(modData);

      const stoData = await apiClient.getJson('/maintenance/storage');
      setStorage(stoData);
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  };

  useEffect(() => {
    runChecks();
  }, []);

  const StatusBadge = ({ status }) => {
    let color = '#28a745'; // ok
    if (status === 'warning') color = '#ffc107';
    if (status === 'error') color = '#dc3545';
    return <span style={{padding: '2px 6px', borderRadius: '4px', fontSize: '11px', textTransform: 'uppercase', fontWeight: 'bold'}}>{status}</span>;
  };

  return (
    <Section title="Project Maintenance & Health" description="Run read-only diagnostics across your local environment, models, storage, and databases." >

      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px'}}>
        <h3 style={{margin: 0, fontSize: '16px'}}>
          Overall Health: {report ? <StatusBadge status={report.overall_health} /> : 'Unknown'}
        </h3>
        <LoadingButton
          loading={loading}
          loadingText="Running Checks..."
          text="Run Maintenance Checks"
          onClick={runChecks}
          
        />
      </div>

      {error && <div style={{padding: '10px', borderRadius: '4px', marginBottom: '15px', fontSize: '13px'}}>Error: {error}</div>}

      <div style={{display: 'flex', gap: '20px', flexWrap: 'wrap'}}>

        {/* Core System Checks */}
        <div style={{flex: 2, minWidth: '400px', padding: '15px', borderRadius: '8px'}}>
          <h4 style={{margin: '0 0 10px 0', fontSize: '15px'}}>System Diagnostics</h4>
          {report ? (
            <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '13px'}}>
              <thead>
                <tr style={{textAlign: 'left'}}>
                  <th style={{padding: '8px'}}>Check</th>
                  <th style={{padding: '8px'}}>Status</th>
                  <th style={{padding: '8px'}}>Message</th>
                  <th style={{padding: '8px'}}>Recommendation</th>
                </tr>
              </thead>
              <tbody>
                {report.checks.map((c, i) => (
                  <tr key={i} >
                    <td style={{padding: '8px', fontWeight: 'bold'}}>{c.name}</td>
                    <td style={{padding: '8px'}}><StatusBadge status={c.status} /></td>
                    <td style={{padding: '8px'}}>{c.message}</td>
                    <td style={{padding: '8px', fontStyle: 'italic'}}>{c.recommendation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p style={{fontSize: '13px'}}>Run checks to view diagnostics.</p>}
        </div>

        <div style={{flex: 1, minWidth: '300px', display: 'flex', flexDirection: 'column', gap: '20px'}}>

          {/* Models Status */}
          <div style={{padding: '15px', borderRadius: '8px'}}>
            <h4 style={{margin: '0 0 10px 0', fontSize: '15px'}}>Model Availability</h4>
            {models ? (
              <ul style={{margin: 0, padding: 0, listStyle: 'none', fontSize: '13px'}}>
                {models.required_models.map((m, i) => (
                  <li key={i} style={{padding: '5px 0', display: 'flex', justifyContent: 'space-between'}}>
                    <span><strong>{m.role}:</strong> {m.model}</span>
                    <span style={{fontWeight: 'bold'}}>
                      {m.available ? '✓ Downloaded' : '✗ Missing'}
                    </span>
                  </li>
                ))}
              </ul>
            ) : <p style={{fontSize: '13px'}}>Run checks to view models.</p>}
            {models?.missing_models.length > 0 && (
              <p style={{fontSize: '12px', marginTop: '10px'}}>
                Missing models detected. Go to Model Manager to pull them via Ollama.
              </p>
            )}
          </div>

          {/* Storage Status */}
          <div style={{padding: '15px', borderRadius: '8px'}}>
            <h4 style={{margin: '0 0 10px 0', fontSize: '15px'}}>Storage Footprint</h4>
            {storage ? (
              <div>
                <ul style={{margin: '0 0 10px 0', padding: 0, listStyle: 'none', fontSize: '13px'}}>
                  <li style={{padding: '3px 0'}}>Uploads: <strong>{storage.storage.uploads_mb} MB</strong></li>
                  <li style={{padding: '3px 0'}}>Extracted Text: <strong>{storage.storage.extracted_mb} MB</strong></li>
                  <li style={{padding: '3px 0'}}>Screenshots: <strong>{storage.storage.screenshots_mb} MB</strong></li>
                  <li style={{padding: '3px 0'}}>SQLite Backups: <strong>{storage.storage.backups_mb} MB</strong></li>
                  <li style={{padding: '3px 0'}}>Generated Docs: <strong>{storage.storage.generated_docs_mb} MB</strong></li>
                  <li style={{padding: '5px 0', marginTop: '5px', fontSize: '14px'}}>
                    Total Footprint: <strong>{storage.storage.total_mb} MB</strong>
                  </li>
                </ul>
                {storage.warnings.map((w, i) => (
                  <div key={i} style={{fontSize: '12px', padding: '6px', borderRadius: '4px'}}>
                    Warning: {w}
                  </div>
                ))}
              </div>
            ) : <p style={{fontSize: '13px'}}>Run checks to view storage.</p>}
          </div>

        </div>

      </div>
    </Section>
  );
}

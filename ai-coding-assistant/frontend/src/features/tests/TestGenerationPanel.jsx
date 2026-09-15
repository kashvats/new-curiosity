import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function TestGenerationPanel() {
  const [task, setTask] = useState('');
  const [filePaths, setFilePaths] = useState('');
  const [extraContext, setExtraContext] = useState('');
  const [impactReportId, setImpactReportId] = useState('');
  const [impactReports, setImpactReports] = useState([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [testData, setTestData] = useState(null);

  useEffect(() => {
    apiClient.getJson('/impact/reports')
      .then(data => setImpactReports(data.reports || []))
      .catch(err => console.error("Failed to load impact reports", err));
  }, []);

  const handleGenerate = async (e) => {
    e.preventDefault();
    if (!task.trim()) return alert("Task is required");

    setIsGenerating(true);
    setTestData(null);

    try {
      const pathsArray = filePaths.split('\n').map(s => s.trim()).filter(s => s);
      const payload = {
        task,
        file_paths: pathsArray,
        extra_context: extraContext || null,
        impact_report_id: impactReportId || null
      };

      const data = await apiClient.postJson('/agent/generate-tests', payload);
      if (data.status === 'ok') {
        setTestData(data);
      } else {
        alert(`Test generation failed: ${data.message}`);
      }
    } catch (err) {
      alert(`Test generation failed: ${err.message}`);
    }
    setIsGenerating(false);
  };

  return (
    <Section title="Test Generation Agent" description="Draft test files for changed or impacted code safely." >
      <form onSubmit={handleGenerate} style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>
        <textarea
          value={task}
          onChange={e => setTask(e.target.value)}
          placeholder="Describe the test goals (e.g., 'Add unit tests for documents API')..."
          style={{padding: '12px', borderRadius: '4px', minHeight: '80px', fontFamily: 'inherit'}}
        />

        <div>
          <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold'}}>Source Files to Test (one per line):</label>
          <textarea
            value={filePaths}
            onChange={e => setFilePaths(e.target.value)}
            placeholder="backend/app/documents.py"
            style={{width: '100%', padding: '12px', borderRadius: '4px', minHeight: '80px', fontFamily: 'monospace', fontSize: '13px', boxSizing: 'border-box'}}
          />
        </div>

        <div>
          <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold'}}>Attach Impact Report (Optional):</label>
          <select value={impactReportId} onChange={e => setImpactReportId(e.target.value)} style={{width: '100%', padding: '8px', borderRadius: '4px'}}>
            <option value="">-- No Impact Report --</option>
            {impactReports.map(r => (
              <option key={r.id} value={r.id}>{r.task.substring(0, 50)}... ({r.risk_level})</option>
            ))}
          </select>
          <p style={{margin: '5px 0', fontSize: '12px'}}>Attaching a report allows the agent to target high-risk impacted areas automatically.</p>
        </div>

        <div>
          <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold'}}>Extra Context (Optional):</label>
          <textarea
            value={extraContext}
            onChange={e => setExtraContext(e.target.value)}
            placeholder="E.g., Use pytest. Mock database calls."
            style={{width: '100%', padding: '12px', borderRadius: '4px', minHeight: '60px', fontFamily: 'inherit', boxSizing: 'border-box'}}
          />
        </div>

        <div>
          <LoadingButton type="submit" loading={isGenerating} loadingText="Drafting Tests..." text="Generate Tests"  />
        </div>
      </form>

      {testData && testData.result && (
        <div style={{marginTop: '20px', padding: '20px', borderRadius: '8px'}}>
          <div style={{marginBottom: '20px'}}>
            <h3 style={{margin: '0 0 10px 0'}}>Proposed Tests ({testData.model})</h3>
            <p><strong>Summary:</strong> {testData.result.summary}</p>
            <p><strong>Strategy:</strong> {testData.result.test_strategy}</p>

            {testData.result.warnings?.length > 0 && (
              <div style={{padding: '10px', borderRadius: '4px', marginTop: '10px', fontSize: '13px'}}>
                <strong>Warnings / Safety Restrictions:</strong>
                <ul style={{margin: '5px 0', paddingLeft: '20px'}}>
                  {testData.result.warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}
          </div>

          {testData.result.proposed_changes?.length > 0 && (
            <div style={{marginBottom: '20px'}}>
              <h4 style={{margin: '0 0 10px 0'}}>Test File Changes ({testData.result.proposed_changes.length} files)</h4>
              <p style={{fontSize: '12px'}}>Note: These changes are drafts. Please copy the JSON structure below to your Review/Apply workflow if you want to execute them.</p>

              <div style={{display: 'flex', flexDirection: 'column', gap: '20px'}}>
                {testData.result.proposed_changes.map((p, idx) => (
                  <div key={idx} style={{borderRadius: '6px', overflow: 'hidden'}}>
                    <div style={{padding: '10px 15px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                      <strong style={{fontFamily: 'monospace'}}>{p.path}</strong>
                      <span style={{fontSize: '12px', padding: '3px 8px', borderRadius: '12px', fontWeight: 'bold'}}>
                        {p.action.toUpperCase()}
                      </span>
                    </div>
                    <div style={{padding: '10px 15px', fontSize: '13px'}}>
                      <strong>Reason:</strong> {p.reason}
                    </div>
                    <div style={{padding: '0'}}>
                      <pre style={{margin: 0, padding: '15px', fontFamily: 'Consolas, Monaco, monospace', fontSize: '13px', overflowX: 'auto', whiteSpace: 'pre-wrap'}}>
                        {p.action === 'patch' ? p.patch : p.content}
                      </pre>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {testData.result.commands_to_run_manually?.length > 0 && (
            <div>
              <h4 style={{margin: '0 0 10px 0'}}>Test Commands to run manually:</h4>
              <div style={{padding: '15px', borderRadius: '6px', fontFamily: 'Consolas, Monaco, monospace', fontSize: '13px'}}>
                {testData.result.commands_to_run_manually.map((cmd, i) => (
                  <div key={i}>$ {cmd}</div>
                ))}
              </div>
            </div>
          )}

          <div style={{marginTop: '20px', padding: '15px', borderRadius: '4px', fontSize: '13px'}}>
            <strong>Raw JSON Output (For Apply Pipeline):</strong>
            <pre style={{margin: '10px 0 0 0', maxHeight: '150px', overflowY: 'auto', padding: '10px'}}>
              {JSON.stringify(testData.result.proposed_changes, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </Section>
  );
}

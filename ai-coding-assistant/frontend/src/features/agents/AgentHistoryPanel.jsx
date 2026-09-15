import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function AgentHistoryPanel() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filterTool, setFilterTool] = useState('');
  const [clearConfirm, setClearConfirm] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [selectedRun, setSelectedRun] = useState(null);

  const fetchRuns = async () => {
    setLoading(true);
    try {
      let url = '/agent/runs?limit=50';
      if (filterTool) url += `&tool_name=${encodeURIComponent(filterTool)}`;
      const data = await apiClient.getJson(url);
      setRuns(data.runs || []);
    } catch (err) {
      console.error("Failed to fetch runs", err);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchRuns();
  }, [filterTool]);

  const handleClear = async () => {
    if (!clearConfirm) return alert("Must check confirm.");
    setIsClearing(true);
    try {
      await apiClient.postJson('/agent/runs/clear', { confirm: true });
      setClearConfirm(false);
      setSelectedRun(null);
      fetchRuns();
    } catch (err) {
      alert(`Failed to clear: ${err.message}`);
    }
    setIsClearing(false);
  };

  const handleDelete = async (runId) => {
    try {
      await apiClient.delete(`/agent/runs/${runId}`);
      if (selectedRun?.id === runId) setSelectedRun(null);
      fetchRuns();
    } catch (err) {
      alert(`Failed to delete: ${err.message}`);
    }
  };

  const statusColor = (status) => {
    if (status === 'success') return '#28a745';
    if (status === 'failed') return '#dc3545';
    if (status === 'running') return '#007bff';
    return '#6c757d';
  };

  return (
    <Section title="Agent Run History" description="Audit logs for planner, coder, apply, browser, and RAG requests.">

      <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: '15px'}}>
        <div style={{display: 'flex', gap: '10px', alignItems: 'center'}}>
          <button onClick={fetchRuns} disabled={loading} style={{padding: '6px 12px'}}>
            {loading ? 'Refreshing...' : '↻ Refresh'}
          </button>
          <select value={filterTool} onChange={e => setFilterTool(e.target.value)} style={{padding: '6px'}}>
            <option value="">All Tools</option>
            <option value="planner">planner</option>
            <option value="coder">coder</option>
            <option value="apply">apply</option>
            <option value="rag_chat">rag_chat</option>
            <option value="web_search">web_search</option>
            <option value="browser_open">browser_open</option>
            <option value="browser_text">browser_text</option>
            <option value="browser_screenshot">browser_screenshot</option>
          </select>
        </div>

        <div style={{display: 'flex', gap: '10px', alignItems: 'center'}}>
          <label style={{fontSize: '12px', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '4px'}}>
            <input type="checkbox" checked={clearConfirm} onChange={e => setClearConfirm(e.target.checked)} /> Confirm Clear
          </label>
          <LoadingButton onClick={handleClear} disabled={!clearConfirm} loading={isClearing} text="Clear History" loadingText="Clearing..." style={{padding: '6px 12px'}} />
        </div>
      </div>

      <div style={{display: 'flex', gap: '20px', minHeight: '300px'}}>
        {/* List View */}
        <div style={{flex: 1, borderRadius: '4px', overflowY: 'auto', maxHeight: '400px'}}>
          {runs.length === 0 ? (
            <div style={{padding: '20px', textAlign: 'center'}}>No runs found.</div>
          ) : (
            <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '13px'}}>
              <thead>
                <tr style={{textAlign: 'left'}}>
                  <th style={{padding: '8px'}}>Tool</th>
                  <th style={{padding: '8px'}}>Status</th>
                  <th style={{padding: '8px'}}>Time</th>
                  <th style={{padding: '8px'}}>Duration</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.id} onClick={() => setSelectedRun(r)} style={{cursor: 'pointer'}}>
                    <td style={{padding: '8px', fontWeight: 'bold'}}>{r.tool_name}</td>
                    <td style={{padding: '8px'}}>{r.status}</td>
                    <td style={{padding: '8px'}}>{new Date(r.created_at).toLocaleTimeString()}</td>
                    <td style={{padding: '8px'}}>{r.duration_ms}ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Detail View */}
        {selectedRun && (
          <div style={{flex: 1, borderRadius: '4px', padding: '15px', overflowY: 'auto', maxHeight: '400px'}}>
            <div style={{display: 'flex', justifyContent: 'space-between', paddingBottom: '10px', marginBottom: '10px'}}>
              <h4 style={{margin: 0}}>Run Details</h4>
              <button onClick={() => handleDelete(selectedRun.id)} style={{cursor: 'pointer', fontSize: '12px', textDecoration: 'underline'}}>Delete Run</button>
            </div>
            <div style={{fontSize: '13px', display: 'flex', flexDirection: 'column', gap: '8px'}}>
              <div><strong>ID:</strong> <span style={{fontFamily: 'monospace'}}>{selectedRun.id}</span></div>
              <div><strong>Tool:</strong> {selectedRun.tool_name}</div>
              <div><strong>Status:</strong> <span >{selectedRun.status}</span></div>
              <div><strong>Model:</strong> {selectedRun.model || 'N/A'}</div>
              <div><strong>Created:</strong> {new Date(selectedRun.created_at).toLocaleString()}</div>
              <div><strong>Duration:</strong> {selectedRun.duration_ms}ms</div>

              <div style={{marginTop: '10px'}}>
                <strong>Input Summary:</strong>
                <pre style={{padding: '8px', borderRadius: '4px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: '4px', maxHeight: '100px', overflowY: 'auto'}}>
                  {selectedRun.input_summary}
                </pre>
              </div>

              {selectedRun.output_summary && (
                <div style={{marginTop: '5px'}}>
                  <strong>Output Summary:</strong>
                  <pre style={{padding: '8px', borderRadius: '4px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: '4px'}}>
                    {selectedRun.output_summary}
                  </pre>
                </div>
              )}

              {selectedRun.error && (
                <div style={{marginTop: '5px'}}>
                  <strong >Error:</strong>
                  <pre style={{padding: '8px', borderRadius: '4px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginTop: '4px'}}>
                    {selectedRun.error}
                  </pre>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Section>
  );
}

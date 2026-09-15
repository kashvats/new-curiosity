import React, { useState, useEffect } from 'react';
import { apiClient } from '../../api/client';

export default function RestorePointsPanel() {
  const [points, setPoints] = useState([]);
  const [loading, setLoading] = useState(false);
  
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [phaseNumber, setPhaseNumber] = useState('');
  const [createSnapshot, setCreateSnapshot] = useState(true);
  const [runDebug, setRunDebug] = useState(false);
  const [status, setStatus] = useState('good');

  const [summaryData, setSummaryData] = useState(null);

  const fetchPoints = async () => {
    setLoading(true);
    try {
      const data = await apiClient.getJson('/restore-points');
      setPoints(data.restore_points || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPoints();
  }, []);

  const handleCreate = async () => {
    if (!name) return alert("Name required");
    try {
      await apiClient.postJson('/restore-points', {
        name,
        description,
        phase_number: phaseNumber ? parseInt(phaseNumber) : null,
        create_snapshot: createSnapshot,
        run_debug: runDebug,
        status
      });
      alert("Restore point created!");
      setName('');
      setDescription('');
      fetchPoints();
    } catch (err) {
      alert("Failed: " + err.message);
    }
  };

  const handleStatusChange = async (id, newStatus) => {
    try {
      await apiClient.putJson(`/restore-points/${id}/status`, { status: newStatus });
      fetchPoints();
    } catch (err) {
      alert("Failed: " + err.message);
    }
  };

  const loadSummary = async (id) => {
    try {
      const data = await apiClient.getJson(`/restore-points/${id}/recovery-summary`);
      setSummaryData(data.summary);
    } catch (err) {
      alert("Failed to load summary: " + err.message);
    }
  };

  return (
    <div style={{padding: '20px', borderRadius: '8px', marginBottom: '20px'}}>
      <h2>Restore Points</h2>
      <p style={{fontSize: '14px'}}>Bookmark stable states before taking risky actions.</p>
      
      <div style={{marginBottom: '20px', padding: '15px', borderRadius: '4px'}}>
        <h3 style={{marginTop: 0}}>Create Restore Point</h3>
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px'}}>
          <input placeholder="Name (e.g. Pre Phase 51)" value={name} onChange={e => setName(e.target.value)} style={{padding: '8px'}} />
          <input placeholder="Phase Number (e.g. 50)" type="number" value={phaseNumber} onChange={e => setPhaseNumber(e.target.value)} style={{padding: '8px'}} />
          <input placeholder="Description" value={description} onChange={e => setDescription(e.target.value)} style={{padding: '8px', gridColumn: 'span 2'}} />
        </div>
        <div style={{marginTop: '10px', display: 'flex', gap: '15px', fontSize: '13px'}}>
          <label><input type="checkbox" checked={createSnapshot} onChange={e => setCreateSnapshot(e.target.checked)} /> Create Snapshot</label>
          <label><input type="checkbox" checked={runDebug} onChange={e => setRunDebug(e.target.checked)} /> Run Debug Checks</label>
          <label>
            Status: 
            <select value={status} onChange={e => setStatus(e.target.value)} style={{marginLeft: '5px'}}>
              <option value="good">Good</option>
              <option value="risky">Risky</option>
              <option value="broken">Broken</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
        </div>
        <button onClick={handleCreate} style={{marginTop: '10px', padding: '8px 16px', cursor: 'pointer'}}>Create Restore Point</button>
      </div>

      <div>
        <h3 style={{marginTop: 0}}>Existing Restore Points</h3>
        {loading && <p>Loading...</p>}
        {!loading && points.length === 0 && <p>No restore points yet.</p>}
        {points.map(rp => (
          <div key={rp.id} style={{borderRadius: '4px', padding: '10px', marginBottom: '10px'}}>
            <div style={{display: 'flex', justifyContent: 'space-between'}}>
              <strong>{rp.name} (Phase {rp.phase_number || '?'})</strong>
              <span style={{fontSize: '12px'}}>{new Date(rp.created_at).toLocaleString()}</span>
            </div>
            {rp.description && <p style={{fontSize: '13px', margin: '5px 0'}}>{rp.description}</p>}
            <div style={{fontSize: '12px', marginTop: '5px'}}>
              {rp.snapshot_id && <span>Snapshot: {rp.snapshot_id} | </span>}
              {rp.debug_report_path && <span>Debug: {rp.debug_report_path} | </span>}
              Status: 
              <select value={rp.status} onChange={e => handleStatusChange(rp.id, e.target.value)} style={{marginLeft: '5px'}}>
                <option value="good">Good</option>
                <option value="risky">Risky</option>
                <option value="broken">Broken</option>
                <option value="unknown">Unknown</option>
              </select>
              <button onClick={() => loadSummary(rp.id)} style={{marginLeft: '10px', fontSize: '11px'}}>View Recovery Summary</button>
            </div>
          </div>
        ))}
      </div>

      {summaryData && (
        <div style={{marginTop: '20px', padding: '15px', borderRadius: '4px'}}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
            <h3 style={{margin: 0}}>Recovery Summary for {summaryData.name}</h3>
            <button onClick={() => setSummaryData(null)} style={{cursor: 'pointer'}}>Close</button>
          </div>
          <p style={{fontSize: '13px'}}>Files changed since this restore point:</p>
          <ul style={{fontSize: '12px', maxHeight: '150px', overflowY: 'auto'}}>
            {summaryData.changed_files_since.length === 0 && <li>None detected</li>}
            {summaryData.changed_files_since.map(f => <li key={f}>{f}</li>)}
          </ul>
          <p style={{fontSize: '13px', fontWeight: 'bold'}}>Recommended Steps:</p>
          <ul style={{fontSize: '12px'}}>
            {summaryData.recommended_recovery_steps.map((step, i) => <li key={i}>{step}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

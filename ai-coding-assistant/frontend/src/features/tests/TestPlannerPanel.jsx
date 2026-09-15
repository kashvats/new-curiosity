import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function TestPlannerPanel() {
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Runner state
  const [allowedCommands, setAllowedCommands] = useState([]);
  const [selectedCommandId, setSelectedCommandId] = useState('');
  const [runConfirm, setRunConfirm] = useState(false);
  const [isCommandRunning, setIsCommandRunning] = useState(false);
  const [recentRuns, setRecentRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);

  const fetchRunnerData = async () => {
    try {
      const allowedData = await apiClient.getJson('/tests/allowed');
      setAllowedCommands(allowedData.commands || []);
      if (allowedData.commands?.length > 0 && !selectedCommandId) {
        setSelectedCommandId(allowedData.commands[0].id);
      }

      const runsData = await apiClient.getJson('/tests/runs');
      setRecentRuns(runsData.runs || []);
    } catch (e) {
      console.error(e);
    }
  };

  React.useEffect(() => {
    fetchRunnerData();
  }, []);

  const handleScan = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getJson('/tests/plan');
      setPlan(data);
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  };

  const handleCopy = async (command) => {
    try {
      await navigator.clipboard.writeText(command);
      alert(`Copied to clipboard:\n${command}`);
    } catch (err) {
      alert("Failed to copy text.");
    }
  };

  const handleRunCommand = async () => {
    if (!runConfirm) return alert("Please check confirm before running.");
    if (!selectedCommandId) return alert("Please select a command.");

    setIsCommandRunning(true);
    setSelectedRun(null);
    try {
      const data = await apiClient.postJson('/tests/run', {
        command_id: selectedCommandId,
        confirm: runConfirm
      });
      setSelectedRun({ run: data });
      setRunConfirm(false);
      fetchRunnerData();
    } catch (err) {
      alert(`Test run failed: ${err.message}`);
    }
    setIsCommandRunning(false);
  };

  const loadRunDetails = async (runId) => {
    try {
      const data = await apiClient.getJson(`/tests/runs/${runId}`);
      setSelectedRun(data);
    } catch (e) {
      alert(`Failed to load run details: ${e.message}`);
    }
  };

  return (
    <Section title="Test Runner Planner" description="Safely scan your workspace for test files and view recommended test execution commands." >

      <div style={{marginBottom: '15px'}}>
        <LoadingButton
          loading={loading}
          loadingText="Scanning Workspace..."
          text="Scan for Tests & Commands"
          onClick={handleScan}
          
        />
      </div>

      {error && <div style={{padding: '10px', borderRadius: '4px', marginBottom: '15px', fontSize: '13px'}}>Error: {error}</div>}

      {plan && (
        <div style={{display: 'flex', gap: '20px', flexWrap: 'wrap'}}>

          <div style={{flex: 1, minWidth: '300px', display: 'flex', flexDirection: 'column', gap: '15px'}}>

            <div style={{padding: '15px', borderRadius: '8px'}}>
              <h4 style={{margin: '0 0 10px 0', fontSize: '15px'}}>Suggested Commands</h4>
              {plan.suggested_commands.length === 0 ? (
                <p style={{fontSize: '13px'}}>No known test commands detected.</p>
              ) : (
                <div style={{display: 'flex', flexDirection: 'column', gap: '10px'}}>
                  {plan.suggested_commands.map((cmd, i) => (
                    <div key={i} style={{padding: '10px', borderRadius: '4px'}}>
                      <div style={{fontWeight: 'bold', fontSize: '13px', marginBottom: '5px'}}>{cmd.name}</div>
                      <div style={{padding: '8px', borderRadius: '4px', fontFamily: 'monospace', fontSize: '12px', marginBottom: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                        <code>{cmd.command}</code>
                        <button onClick={() => handleCopy(cmd.command)} style={{borderRadius: '3px', cursor: 'pointer', padding: '2px 6px', fontSize: '10px'}}>Copy</button>
                      </div>
                      <div style={{fontSize: '11px', fontStyle: 'italic'}}>Reason: {cmd.reason}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {plan.warnings && plan.warnings.length > 0 && (
              <div style={{padding: '10px', borderRadius: '4px', fontSize: '13px'}}>
                <strong style={{display: 'block', marginBottom: '5px'}}>Warnings:</strong>
                <ul style={{margin: 0, paddingLeft: '20px'}}>
                  {plan.warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}
          </div>

          <div style={{flex: 1, minWidth: '300px', padding: '15px', borderRadius: '8px', maxHeight: '500px', overflowY: 'auto'}}>
            <h4 style={{margin: '0 0 10px 0', fontSize: '15px'}}>Detected Test Files</h4>

            <div style={{marginBottom: '15px'}}>
              <h5 style={{margin: '0 0 5px 0', fontSize: '13px'}}>Backend Tests ({plan.test_files.backend.length})</h5>
              {plan.test_files.backend.length === 0 ? <p style={{fontSize: '12px', margin: 0}}>None</p> : (
                <ul style={{margin: 0, paddingLeft: '20px', fontSize: '12px', fontFamily: 'monospace'}}>
                  {plan.test_files.backend.map((f, i) => <li key={i} style={{padding: '2px 0'}}>{f}</li>)}
                </ul>
              )}
            </div>

            <div>
              <h5 style={{margin: '0 0 5px 0', fontSize: '13px'}}>Frontend Tests ({plan.test_files.frontend.length})</h5>
              {plan.test_files.frontend.length === 0 ? <p style={{fontSize: '12px', margin: 0}}>None</p> : (
                <ul style={{margin: 0, paddingLeft: '20px', fontSize: '12px', fontFamily: 'monospace'}}>
                  {plan.test_files.frontend.map((f, i) => <li key={i} style={{padding: '2px 0'}}>{f}</li>)}
                </ul>
              )}
            </div>

          </div>

        </div>
      )}

      {/* Test Runner UI */}
      <div style={{marginTop: '30px', display: 'flex', gap: '20px', flexWrap: 'wrap'}}>

        {/* Left: Execution */}
        <div style={{flex: 1, minWidth: '300px', padding: '15px', borderRadius: '8px'}}>
          <h4 style={{margin: '0 0 15px 0', fontSize: '15px'}}>Execute Safe Tests</h4>

          <div style={{marginBottom: '15px'}}>
            <label style={{display: 'block', fontSize: '13px', marginBottom: '5px', fontWeight: 'bold'}}>Select Allowed Command</label>
            <select
              value={selectedCommandId}
              onChange={e => setSelectedCommandId(e.target.value)}
              style={{width: '100%', padding: '8px', borderRadius: '4px', fontSize: '13px'}}
            >
              <option value="">-- Select a command --</option>
              {allowedCommands.map(cmd => (
                <option key={cmd.id} value={cmd.id}>{cmd.id} - {cmd.command}</option>
              ))}
            </select>
          </div>

          <div style={{padding: '10px', borderRadius: '4px', marginBottom: '15px'}}>
            <label style={{display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', fontWeight: 'bold'}}>
              <input type="checkbox" checked={runConfirm} onChange={e => setRunConfirm(e.target.checked)} />
              Confirm exact execution of allowlisted command
            </label>
          </div>

          <LoadingButton
            loading={isCommandRunning}
            loadingText="Executing Test Runner (Timeout 120s)..."
            text="Run Selected Command"
            disabled={!runConfirm || !selectedCommandId}
            onClick={handleRunCommand}
            style={{width: '100%'}}
          />

          <div style={{marginTop: '20px'}}>
            <h5 style={{margin: '0 0 10px 0', fontSize: '13px'}}>Recent Test Runs</h5>
            <ul style={{margin: 0, padding: 0, listStyle: 'none', fontSize: '12px'}}>
              {recentRuns.slice(0, 5).map(r => (
                <li key={r.id} style={{padding: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                  <div style={{display: 'flex', flexDirection: 'column'}}>
                    <strong>{r.command_id}</strong>
                    <span style={{fontSize: '10px'}}>{new Date(r.created_at).toLocaleString()}</span>
                  </div>
                  <div style={{display: 'flex', alignItems: 'center', gap: '10px'}}>
                    <span style={{fontWeight: 'bold'}}>{r.status} (exit: {r.exit_code})</span>
                    <button onClick={() => loadRunDetails(r.id)} style={{padding: '3px 8px', fontSize: '11px', cursor: 'pointer'}}>View Details</button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Right: Output */}
        <div style={{flex: 1, minWidth: '400px', padding: '15px', borderRadius: '8px', display: 'flex', flexDirection: 'column'}}>
          <h4 style={{margin: '0 0 10px 0', fontSize: '15px'}}>Test Output Console</h4>
          {selectedRun ? (
            <div style={{flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '10px'}}>
              <div style={{fontSize: '12px', paddingBottom: '10px'}}>
                <div><strong>Command ID:</strong> {selectedRun.run.command_id || selectedRun.run.command}</div>
                <div><strong>Status:</strong> {selectedRun.run.run_status || selectedRun.run.status}</div>
                <div><strong>Exit Code:</strong> {selectedRun.run.exit_code}</div>
                <div><strong>Duration:</strong> {selectedRun.run.duration_ms} ms</div>
              </div>
              <div style={{display: 'flex', flexDirection: 'column', gap: '10px'}}>
                <div>
                  <strong style={{fontSize: '12px'}}>STDOUT:</strong>
                  <pre style={{margin: 0, padding: '10px', borderRadius: '4px', fontSize: '11px', whiteSpace: 'pre-wrap', fontFamily: 'monospace'}}>
                    {selectedRun.run.stdout || '(no stdout output)'}
                  </pre>
                </div>
                <div>
                  <strong style={{fontSize: '12px'}}>STDERR:</strong>
                  <pre style={{margin: 0, padding: '10px', borderRadius: '4px', fontSize: '11px', whiteSpace: 'pre-wrap', fontFamily: 'monospace'}}>
                    {selectedRun.run.stderr || '(no stderr output)'}
                  </pre>
                </div>
              </div>
            </div>
          ) : (
            <p style={{fontSize: '12px'}}>Run a command or click "View Details" to see output.</p>
          )}
        </div>

      </div>

    </Section>
  );
}

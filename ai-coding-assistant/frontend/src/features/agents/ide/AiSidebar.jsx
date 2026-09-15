import React, { useState } from 'react';
import { apiClient } from '../../../api/client';

export default function AiSidebar({ selectedFile, onFileChanged }) {
  const [task, setTask] = useState('');
  const [mode, setMode] = useState('coder'); // 'planner', 'coder', 'reviewer'
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState(null);

  const handleSubmit = async () => {
    if (!task.trim()) return;
    setLoading(true);
    setResponse(null);

    // If a file is selected, automatically append the context so the backend agent knows what to work on.
    const contextStr = selectedFile ? `\n\nFocus on file: ${selectedFile}` : '';
    const fullTask = task + contextStr;

    try {
      if (mode === 'planner') {
        const res = await apiClient.postJson('/agent/plan', { request: fullTask });
        setResponse(res);
      } else if (mode === 'coder') {
        const res = await apiClient.postJson('/agent/code', { task: fullTask });
        setResponse(res);
      } else if (mode === 'reviewer') {
        // Find project ID (mocked for now, assumes default or relies on workspace root)
        const res = await apiClient.postJson('/agent/review', { project_id: 'default', mode: 'auto' });
        setResponse(res);
      }
    } catch (e) {
      setResponse({ status: 'error', message: e.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="ai-sidebar-container">
      {/* Header Tabs */}
      <div className="ai-header-tabs">
        {['planner', 'coder', 'reviewer'].map(m => (
          <div 
            key={m}
            onClick={() => setMode(m)}
            className={`ai-tab ${mode === m ? 'active' : ''}`}
          >
            {m}
          </div>
        ))}
      </div>

      {/* Output / Chat Area */}
      <div className="ai-chat-area">
        {response ? (
          <div style={{ fontSize: '13px' }}>
            {response.status === 'error' ? (
              <div style={{ color: 'red' }}>Error: {response.message}</div>
            ) : (
              <div>
                <div style={{ color: '#94a3b8', marginBottom: '10px', fontSize: '12px' }}>
                  Model: {response.model}
                </div>
                {mode === 'planner' && response.plan && (
                  <div>
                    <h4 style={{ color: '#e2e8f0', margin: '0 0 10px 0' }}>Plan:</h4>
                    {response.plan.phases && response.plan.phases.map((p, i) => (
                      <div key={i} className="chat-message">
                        <strong style={{ color: '#3b82f6' }}>{p.name}</strong><br/>
                        <div style={{ marginTop: '5px', color: '#cbd5e1' }}>{p.description}</div>
                      </div>
                    ))}
                  </div>
                )}
                {mode === 'coder' && response.diff && (
                  <div>
                    <h4 style={{ color: '#e2e8f0', margin: '0 0 10px 0' }}>Proposed Diff:</h4>
                    <pre style={{ background: 'rgba(0,0,0,0.4)', padding: '15px', overflowX: 'auto', borderRadius: '8px', color: '#cbd5e1', border: '1px solid rgba(255,255,255,0.05)' }}>
                      {response.diff}
                    </pre>
                  </div>
                )}
                {mode === 'reviewer' && response.review_report && (
                  <div className="chat-message system">
                    <h4 style={{ color: '#8b5cf6', margin: '0 0 10px 0' }}>Review Report:</h4>
                    <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0, color: '#e2e8f0' }}>
                      {response.review_report.summary}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div style={{ color: '#64748b', fontSize: '13px', textAlign: 'center', marginTop: '40px' }}>
            Enter a prompt below to instruct the agent.
            <br/><br/>
            {selectedFile && <span style={{ color: '#8b5cf6' }}>Currently focused on: {selectedFile.split(/[/\\]/).pop()}</span>}
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="ai-input-container">
        <textarea
          className="ai-textarea"
          rows={4}
          placeholder={`Instruct the ${mode}...`}
          value={task}
          onChange={(e) => setTask(e.target.value)}
          disabled={loading}
        />
        <button 
          onClick={handleSubmit}
          disabled={loading || (!task.trim() && mode !== 'reviewer')}
          className="btn btn-primary"
          style={{ width: '100%' }}
        >
          {loading ? 'Working...' : 'Submit'}
        </button>
      </div>
    </div>
  );
}

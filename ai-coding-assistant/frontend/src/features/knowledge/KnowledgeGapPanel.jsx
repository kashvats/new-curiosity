import React, { useState } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function KnowledgeGapPanel() {
  const [scope, setScope] = useState('full_system');
  const [kbId, setKbId] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);

  const handleAnalyze = async (e) => {
    e.preventDefault();
    setIsAnalyzing(true);
    setError(null);
    setReport(null);
    
    try {
      const payload = { scope };
      if (kbId) payload.knowledge_base_id = kbId;
      
      const data = await apiClient.postJson('/knowledge-gaps/analyze', payload);
      setReport(data);
    } catch (err) {
      setError(err.message);
    }
    setIsAnalyzing(false);
  };

  const handleCopy = (text, label) => {
    navigator.clipboard.writeText(text);
    alert(`Copied ${label} to clipboard!`);
  };

  return (
    <Section title="Knowledge Gap Detection" description="Identify where your local knowledge base is missing context or struggling." >
      <form onSubmit={handleAnalyze} style={{display: 'flex', gap: '15px', alignItems: 'center', marginBottom: '20px'}}>
        <div style={{flex: 1}}>
          <label style={{display: 'block', fontWeight: 'bold', fontSize: '14px', marginBottom: '5px'}}>Scope:</label>
          <select 
            value={scope} 
            onChange={(e) => setScope(e.target.value)} 
            style={{width: '100%', padding: '8px', borderRadius: '4px'}}
          >
            <option value="full_system">Full System</option>
            <option value="rag">RAG / Chat</option>
            <option value="codebase">Codebase Coverage</option>
            <option value="knowledge_base">Documents & PDFs</option>
            <option value="failed_queries">Failed Queries</option>
          </select>
        </div>
        <div style={{flex: 1}}>
          <label style={{display: 'block', fontWeight: 'bold', fontSize: '14px', marginBottom: '5px'}}>Knowledge Base ID (Optional):</label>
          <input 
            type="text" 
            value={kbId} 
            onChange={e => setKbId(e.target.value)} 
            placeholder="e.g. default_knowledge" 
            style={{width: '100%', padding: '8px', borderRadius: '4px', boxSizing: 'border-box'}}
          />
        </div>
        <div style={{paddingTop: '22px'}}>
          <LoadingButton type="submit" loading={isAnalyzing} loadingText="Scanning..." text="Analyze Gaps"  />
        </div>
      </form>

      {error && (
        <div style={{padding: '10px', borderRadius: '4px', marginBottom: '15px'}}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {report && (
        <div style={{padding: '20px', borderRadius: '8px'}}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px'}}>
            <h3 style={{margin: 0}}>Gap Report ({report.scope})</h3>
          </div>

          <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '15px', marginBottom: '25px'}}>
            <div style={{padding: '15px', borderRadius: '6px', textAlign: 'center'}}>
              <strong style={{display: 'block', fontSize: '24px'}}>{report.summary.gap_count}</strong>
              <span style={{fontSize: '13px', fontWeight: 'bold'}}>Total Gaps</span>
            </div>
            <div style={{padding: '15px', borderRadius: '6px', textAlign: 'center'}}>
              <strong style={{display: 'block', fontSize: '24px'}}>{report.summary.high_priority}</strong>
              <span style={{fontSize: '13px', fontWeight: 'bold'}}>High Priority</span>
            </div>
            <div style={{padding: '15px', borderRadius: '6px', textAlign: 'center'}}>
              <strong style={{display: 'block', fontSize: '24px'}}>{report.summary.medium_priority}</strong>
              <span style={{fontSize: '13px', fontWeight: 'bold'}}>Medium Priority</span>
            </div>
            <div style={{padding: '15px', borderRadius: '6px', textAlign: 'center'}}>
              <strong style={{display: 'block', fontSize: '24px'}}>{report.summary.low_priority}</strong>
              <span style={{fontSize: '13px', fontWeight: 'bold'}}>Low Priority</span>
            </div>
          </div>

          {report.gaps?.length > 0 ? (
            <div style={{display: 'flex', flexDirection: 'column', gap: '20px'}}>
              {report.gaps.map((gap, idx) => (
                <div key={idx} style={{padding: '15px', borderRadius: '4px'}}>
                  <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: '10px'}}>
                    <strong style={{fontSize: '16px'}}>[{gap.area.toUpperCase()}] {gap.problem}</strong>
                    <span style={{fontSize: '12px', fontWeight: 'bold', textTransform: 'uppercase'}}>{gap.priority} Priority</span>
                  </div>
                  
                  {gap.evidence?.length > 0 && (
                    <div style={{marginBottom: '10px', fontSize: '13px'}}>
                      <em>Evidence:</em> {gap.evidence.join(' | ')}
                    </div>
                  )}
                  
                  <div style={{marginBottom: '15px', padding: '10px', borderRadius: '4px'}}>
                    <strong style={{display: 'block', fontSize: '13px', marginBottom: '5px'}}>Recommended Action:</strong>
                    <span style={{fontSize: '13px'}}>{gap.recommended_action}</span>
                  </div>
                  
                  {gap.suggested_documents?.length > 0 && (
                    <div style={{marginBottom: '15px'}}>
                      <strong style={{fontSize: '13px'}}>Target Files/Docs:</strong>
                      <ul style={{margin: '5px 0 0 0', paddingLeft: '20px', fontSize: '13px'}}>
                        {gap.suggested_documents.map((doc, i) => <li key={i}>{doc}</li>)}
                      </ul>
                    </div>
                  )}

                  <div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
                    {gap.manual_note_prompt && (
                      <div style={{display: 'flex', gap: '10px', alignItems: 'center'}}>
                        <button onClick={() => handleCopy(gap.manual_note_prompt, "Note Prompt")} style={{padding: '4px 8px', fontSize: '11px', cursor: 'pointer', whiteSpace: 'nowrap'}}>Copy Note Prompt</button>
                        <code style={{fontSize: '11px', padding: '2px 6px', borderRadius: '3px', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{gap.manual_note_prompt}</code>
                      </div>
                    )}
                    {gap.web_search_query && (
                      <div style={{display: 'flex', gap: '10px', alignItems: 'center'}}>
                        <button onClick={() => handleCopy(gap.web_search_query, "Web Search Query")} style={{padding: '4px 8px', fontSize: '11px', cursor: 'pointer', whiteSpace: 'nowrap'}}>Copy Search Query</button>
                        <code style={{fontSize: '11px', padding: '2px 6px', borderRadius: '3px', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{gap.web_search_query}</code>
                      </div>
                    )}
                    {gap.agent_action_prompt && (
                      <div style={{display: 'flex', gap: '10px', alignItems: 'center'}}>
                        <button onClick={() => handleCopy(gap.agent_action_prompt, "Agent Prompt")} style={{padding: '4px 8px', fontSize: '11px', cursor: 'pointer', whiteSpace: 'nowrap'}}>Copy Agent Fix</button>
                        <code style={{fontSize: '11px', padding: '2px 6px', borderRadius: '3px', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{gap.agent_action_prompt}</code>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p >No significant knowledge gaps detected.</p>
          )}
        </div>
      )}
    </Section>
  );
}

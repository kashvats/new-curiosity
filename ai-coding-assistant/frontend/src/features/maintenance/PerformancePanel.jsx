import React, { useState } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function PerformancePanel() {
  const [scope, setScope] = useState('full_system');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);

  const handleAnalyze = async (e) => {
    e.preventDefault();
    setIsAnalyzing(true);
    setError(null);
    setReport(null);
    
    try {
      const data = await apiClient.postJson('/performance/analyze', { scope });
      setReport(data);
    } catch (err) {
      setError(err.message);
    }
    setIsAnalyzing(false);
  };

  const handleCopy = (text) => {
    navigator.clipboard.writeText(text);
    alert('Copied Fix Prompt to clipboard!');
  };

  return (
    <Section title="Performance Optimization Agent" description="Identify structural bottlenecks and generate safe AI prompts to fix them." >
      <form onSubmit={handleAnalyze} style={{display: 'flex', gap: '15px', alignItems: 'center', marginBottom: '20px'}}>
        <div style={{flex: 1}}>
          <label style={{display: 'block', fontWeight: 'bold', fontSize: '14px', marginBottom: '5px'}}>Analysis Scope:</label>
          <select 
            value={scope} 
            onChange={(e) => setScope(e.target.value)} 
            style={{width: '100%', padding: '8px', borderRadius: '4px'}}
          >
            <option value="full_system">Full System</option>
            <option value="rag">RAG Pipeline</option>
            <option value="qdrant">Qdrant Vector DB</option>
            <option value="embeddings">Embeddings</option>
            <option value="backend">Backend API</option>
            <option value="frontend">Frontend Build</option>
            <option value="storage">Storage Footprint</option>
            <option value="docker">Docker Resources</option>
          </select>
        </div>
        <div style={{paddingTop: '22px'}}>
          <LoadingButton type="submit" loading={isAnalyzing} loadingText="Agent Thinking..." text="Analyze Bottlenecks"  />
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
            <h3 style={{margin: 0}}>Performance Report ({report.scope})</h3>
            <span style={{padding: '5px 10px', borderRadius: '4px', fontWeight: 'bold', textTransform: 'uppercase', fontSize: '13px'}}>
              Status: {report.summary.overall_performance}
            </span>
          </div>

          {report.bottlenecks?.length > 0 ? (
            <div style={{marginBottom: '25px'}}>
              <h4 style={{margin: '0 0 10px 0', paddingBottom: '5px'}}>Detected Bottlenecks</h4>
              <div style={{display: 'flex', flexDirection: 'column', gap: '10px'}}>
                {report.bottlenecks.map((btn, idx) => (
                  <div key={idx} style={{padding: '10px', borderRadius: '4px',  boxShadow: '0 1px 2px rgba(0,0,0,0.05)'}}>
                    <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: '5px'}}>
                      <strong style={{fontSize: '14px'}}>[{btn.area.toUpperCase()}] {btn.problem}</strong>
                      <span style={{fontSize: '12px', fontWeight: 'bold'}}>Severity: {btn.severity}</span>
                    </div>
                    <p style={{margin: '0 0 5px 0', fontSize: '13px'}}><em>Evidence:</em> {btn.evidence}</p>
                    {btn.likely_files?.length > 0 && (
                      <p style={{margin: 0, fontSize: '12px'}}><strong>Likely Files:</strong> {btn.likely_files.join(', ')}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p >No significant bottlenecks detected in this scope.</p>
          )}

          {report.recommendations?.length > 0 && (
            <div>
              <h4 style={{margin: '0 0 10px 0', paddingBottom: '5px'}}>Agent Recommendations</h4>
              <div style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>
                {report.recommendations.map((rec, idx) => (
                  <div key={idx} style={{padding: '15px', borderRadius: '4px'}}>
                    <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px'}}>
                      <div>
                        <strong style={{display: 'block', fontSize: '15px', marginBottom: '5px'}}>{rec.title}</strong>
                        <div style={{fontSize: '12px'}}>
                          <span style={{marginRight: '10px'}}><strong>Benefit:</strong> {rec.expected_benefit}</span>
                          <span style={{marginRight: '10px'}}><strong>Risk:</strong> {rec.risk}</span>
                          <span><strong>Phase:</strong> {rec.suggested_phase}</span>
                        </div>
                      </div>
                    </div>
                    
                    <div style={{marginTop: '10px', padding: '10px', borderRadius: '4px'}}>
                      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '5px'}}>
                        <strong style={{fontSize: '12px'}}>Agent Fix Prompt:</strong>
                        <button 
                          onClick={() => handleCopy(rec.agent_fix_prompt)}
                          style={{padding: '4px 8px', fontSize: '11px', borderRadius: '3px', cursor: 'pointer'}}
                        >
                          Copy Prompt
                        </button>
                      </div>
                      <code style={{display: 'block', fontSize: '12px', whiteSpace: 'pre-wrap', wordBreak: 'break-word'}}>
                        {rec.agent_fix_prompt}
                      </code>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import TemplateSelector from '../../components/TemplateSelector';
import { apiClient } from '../../api/client';

export default function PlannerPanel() {
  const [planRequest, setPlanRequest] = useState('');
  const [planData, setPlanData] = useState(null);
  const [isPlanning, setIsPlanning] = useState(false);
  const [templateData, setTemplateData] = useState({ id: null, vars: null, error: false });

  const handleCreatePlan = async (e) => {
    e.preventDefault();
    if (!planRequest.trim()) return;
    if (templateData.error) return alert("Please fix template errors first.");

    setIsPlanning(true);
    setPlanData(null);
    try {
      const payload = { request: planRequest };
      if (templateData.id) {
        payload.template_id = templateData.id;
        payload.template_variables = templateData.vars;
      }

      const data = await apiClient.postJson('/agent/plan', payload);
      if (data.status === 'ok') {
        setPlanData(data);
      } else {
        alert(`Planning failed: ${data.message}`);
      }
    } catch (err) {
      alert(`Planning failed: ${err.message}`);
    }
    setIsPlanning(false);
  };

  return (
    <Section title="Project Planner (LangGraph)" description="Break large user requests into safe implementation phases.">
      <form onSubmit={handleCreatePlan} style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>
        <textarea 
          className="form-input"
          value={planRequest} 
          onChange={e => setPlanRequest(e.target.value)} 
          placeholder="Describe what you want to build or what task to solve..." 
          style={{padding: '12px', minHeight: '100px'}}
        />
        <TemplateSelector category="planner" onTemplateChange={(id, vars, error) => setTemplateData({ id, vars, error })} />
        <div>
          <LoadingButton type="submit" loading={isPlanning} loadingText="Generating Plan..." text="Create Plan" className="btn btn-primary" />
        </div>
      </form>

      {planData && planData.plan && (
        <div className="card" style={{marginTop: '20px'}}>
          <div style={{marginBottom: '20px'}}>
            <h3 style={{margin: '0 0 10px 0'}}>Plan Overview ({planData.model})</h3>
            {planData.fallback_used && (
              <div style={{fontSize: '13px', marginBottom: '10px'}}>Warning: Model parsing failed, using simple fallback plan.</div>
            )}
            <p><strong>Goal:</strong> {planData.plan.goal}</p>
            <p><strong>Summary:</strong> {planData.plan.summary}</p>
            {planData.plan.recommended_stack?.length > 0 && (
              <p><strong>Recommended Stack:</strong> {planData.plan.recommended_stack.join(', ')}</p>
            )}
            {planData.plan.risks?.length > 0 && (
              <p><strong>Risks:</strong> {planData.plan.risks.join(', ')}</p>
            )}
          </div>
          
          <div style={{marginBottom: '20px'}}>
            <h4 style={{margin: '0 0 10px 0'}}>Implementation Phases ({planData.plan.phases?.length || 0})</h4>
            <div style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>
              {planData.plan.phases?.map((p, idx) => (
                <div key={idx} style={{padding: '15px', borderRadius: 'var(--border-radius-md)'}}>
                  <div style={{fontSize: '16px', fontWeight: 'bold', marginBottom: '8px'}}>
                    Phase {p.id}: {p.title}
                  </div>
                  <div style={{fontSize: '14px', marginBottom: '10px'}}>
                    {p.description}
                  </div>
                  <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '13px'}}>
                    <div>
                      <strong >Files Needed:</strong>
                      <ul style={{margin: '5px 0', paddingLeft: '20px'}}>
                        {p.files_likely_needed?.map((f, i) => <li key={i}>{f}</li>)}
                      </ul>
                    </div>
                    <div>
                      <strong >Success Criteria:</strong>
                      <ul style={{margin: '5px 0', paddingLeft: '20px'}}>
                        {p.success_criteria?.map((c, i) => <li key={i}>{c}</li>)}
                      </ul>
                    </div>
                  </div>
                  <div style={{marginTop: '10px', fontSize: '12px'}}>
                    <strong>Allowed Actions:</strong> {p.allowed_actions?.join(', ')}<br/>
                    <strong>Forbidden Actions:</strong> {p.forbidden_actions?.join(', ')}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <h4 style={{margin: '0 0 10px 0'}}>Next Phase Prompt (Phase 1)</h4>
            <textarea 
              readOnly 
              className="form-input"
              value={planData.plan.next_phase_prompt || ''} 
              style={{minHeight: '100px', fontFamily: "'JetBrains Mono', monospace", resize: 'vertical'}}
            />
          </div>
        </div>
      )}
    </Section>
  );
}

import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import TemplateSelector from '../../components/TemplateSelector';
import { apiClient } from '../../api/client';

export default function ReviewerAgentPanel() {
  const [diff, setDiff] = useState('');
  const [reviewData, setReviewData] = useState(null);
  const [isReviewing, setIsReviewing] = useState(false);
  const [templateData, setTemplateData] = useState({ id: null, vars: null, error: false });
  const [impactReportId, setImpactReportId] = useState('');
  const [impactReports, setImpactReports] = useState([]);

  useEffect(() => {
    apiClient.getJson('/impact/reports')
      .then(data => setImpactReports(data.reports || []))
      .catch(err => console.error("Failed to load impact reports", err));
  }, []);

  const handleReview = async (e) => {
    e.preventDefault();
    if (!diff.trim()) return;
    if (templateData.error) return alert("Please fix template errors first.");
    
    setIsReviewing(true);
    setReviewData(null);
    try {
      const payload = { 
        diff,
        impact_report_id: impactReportId || null
      };
      if (templateData.id) {
        payload.template_id = templateData.id;
        payload.template_variables = templateData.vars;
      }
      
      const data = await apiClient.postJson('/agent/review', payload);
      if (data.status === 'ok') {
        setReviewData(data);
      } else {
        alert(`Review failed: ${data.message}`);
      }
    } catch (err) {
      alert(`Review failed: ${err.message}`);
    }
    setIsReviewing(false);
  };

  return (
    <Section title="Reviewer Agent" description="Analyze a code diff for risks and correctness.">
      <form onSubmit={handleReview} style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>
        <div>
          <label className="form-label">Code Diff (Unified Diff format):</label>
          <textarea 
            className="form-input"
            value={diff} 
            onChange={e => setDiff(e.target.value)} 
            placeholder="--- a/file.py\n+++ b/file.py\n@@ -1,3 +1,3 @@\n..." 
            style={{minHeight: '150px', fontFamily: "'JetBrains Mono', monospace"}}
          />
        </div>
        
        <div>
          <label className="form-label">Attach Impact Report (Optional):</label>
          <select className="form-input" value={impactReportId} onChange={e => setImpactReportId(e.target.value)}>
            <option value="">-- No Impact Report --</option>
            {impactReports.map(r => (
              <option key={r.id} value={r.id}>{r.task.substring(0, 50)}... ({r.risk_level})</option>
            ))}
          </select>
        </div>
        
        <TemplateSelector category="reviewer" onTemplateChange={(id, vars, error) => setTemplateData({ id, vars, error })} />

        <div>
          <LoadingButton type="submit" loading={isReviewing} loadingText="Reviewing..." text="Request Review" className="btn btn-primary" />
        </div>
      </form>

      {reviewData && reviewData.result && (
        <div className="card" style={{marginTop: '20px'}}>
          <h3 style={{margin: '0 0 10px 0'}}>
            Review Status: {reviewData.result.approved ? "Approved" : "Rejected"}
          </h3>
          <p><strong>Safe to Apply:</strong> {reviewData.result.safe_to_apply ? "Yes" : "No"}</p>
          <p><strong>Risk Level:</strong> <span style={{textTransform: 'capitalize'}}>{reviewData.result.risk_level}</span></p>
          
          <div style={{marginTop: '10px'}}>
            <strong >Files Reviewed:</strong>
            <ul style={{margin: '5px 0', paddingLeft: '20px'}}>
              {(reviewData.result.files_reviewed || []).map((f, i) => <li key={i}>{f}</li>)}
            </ul>
          </div>
          
          {reviewData.result.rejected_files?.length > 0 && (
            <div style={{marginTop: '10px'}}>
              <strong>Rejected Files (Needs fixes):</strong>
              <ul style={{margin: '5px 0', paddingLeft: '20px'}}>
                {reviewData.result.rejected_files.map((f, i) => <li key={i}>{f}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

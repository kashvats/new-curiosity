import React, { useState, useEffect, useCallback } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

const STATUS_COLORS = {
  completed: '#28a745',
  failed: '#dc3545',
  running: '#007bff',
  queued: '#ffc107',
  paused: '#fd7e14',
  cancelled: '#6c757d',
};

const STEP_ORDER = ['extract', 'chunk', 'embed', 'index'];

function StepProgress({ requestedSteps, completedSteps, currentStep, status }) {
  return (
    <div style={{display: 'flex', gap: '4px', alignItems: 'center'}}>
      {STEP_ORDER.filter(s => requestedSteps.includes(s)).map(step => {
        const isDone = completedSteps.includes(step);
        const isActive = currentStep === step && status === 'running';
        const color = isDone ? '#28a745' : isActive ? '#007bff' : '#dee2e6';
        const label = { extract: 'EXT', chunk: 'CHK', embed: 'EMB', index: 'IDX' }[step];
        return (
          <span
            key={step}
            title={step}
            style={{padding: '2px 6px',
              borderRadius: '3px',
              fontSize: '10px',
              fontWeight: 'bold',
              
              animation: isActive ? 'pulse 1s infinite' : 'none'}}
          >
            {isActive ? '⟳ ' : isDone ? '✓ ' : ''}{label}
          </span>
        );
      })}
    </div>
  );
}

export default function IngestionQueuePanel({ documents }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState('');
  const [selectedDocId, setSelectedDocId] = useState('');
  const [isCreatingBulk, setIsCreatingBulk] = useState(false);
  const [actionInProgress, setActionInProgress] = useState({});

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      let url = '/ingestion/jobs?limit=50';
      if (filterStatus) url += `&status=${encodeURIComponent(filterStatus)}`;
      const data = await apiClient.getJson(url);
      setJobs(data || []);
    } catch (err) {
      console.error('Failed to fetch jobs', err);
    }
    setLoading(false);
  }, [filterStatus]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  // Auto-refresh when a job is running or has a pause pending
  useEffect(() => {
    const hasActive = jobs.some(j => j.status === 'running' || j.pause_requested === 1);
    if (!hasActive) return;
    const interval = setInterval(fetchJobs, 3000);
    return () => clearInterval(interval);
  }, [jobs, fetchJobs]);

  const doAction = async (jobId, action, label) => {
    setActionInProgress(prev => ({ ...prev, [jobId]: label }));
    try {
      await apiClient.postJson(`/ingestion/jobs/${jobId}/${action}`, {});
      await fetchJobs();
    } catch (err) {
      alert(`${label} failed: ${err.message}`);
      await fetchJobs();
    }
    setActionInProgress(prev => { const n = { ...prev }; delete n[jobId]; return n; });
  };

  const handleCreateJob = async () => {
    if (!selectedDocId) return alert('Select a document first');
    try {
      await apiClient.postJson('/ingestion/jobs', {
        document_id: selectedDocId,
        steps: ['extract', 'chunk', 'embed', 'index'],
      });
      fetchJobs();
    } catch (err) {
      alert(`Failed to create job: ${err.message}`);
    }
  };

  const handleCreateBulk = async () => {
    setIsCreatingBulk(true);
    try {
      const res = await apiClient.postJson('/ingestion/jobs/create-for-unprocessed', {
        steps: ['extract', 'chunk', 'embed', 'index'],
        limit: 20,
      });
      alert(`Created ${res.jobs_created} jobs.`);
      fetchJobs();
    } catch (err) {
      alert(`Bulk create failed: ${err.message}`);
    }
    setIsCreatingBulk(false);
  };

  const docOptions = documents?.filter(d => d.status !== 'duplicate') || [];

  const ActionButton = ({ jobId, action, label, color, title }) => {
    const busy = actionInProgress[jobId];
    return (
      <button
        onClick={() => doAction(jobId, action, label)}
        disabled={!!busy}
        title={title}
        style={{padding: '2px 7px',
          fontSize: '11px',
          borderRadius: '3px',
          cursor: busy ? 'not-allowed' : 'pointer',
          whiteSpace: 'nowrap'}}
      >
        {busy === label ? '...' : label}
      </button>
    );
  };

  return (
    <Section
      title="Document Ingestion Queue"
      description="Manage and process background extraction, chunking, embedding, and indexing. Pause, resume, and retry individual jobs safely."
    >
      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
      `}</style>

      <div style={{display: 'flex', gap: '15px', marginBottom: '15px', flexWrap: 'wrap', alignItems: 'flex-end'}}>
        <div style={{display: 'flex', gap: '10px', alignItems: 'center'}}>
          <select
            id="ingestion-doc-select"
            value={selectedDocId}
            onChange={e => setSelectedDocId(e.target.value)}
            style={{padding: '6px'}}
          >
            <option value="">-- Select Document --</option>
            {docOptions.map(d => (
              <option key={d.id} value={d.id}>
                {d.original_filename} ({d.id.substring(0, 6)})
              </option>
            ))}
          </select>
          <button
            id="ingestion-queue-btn"
            onClick={handleCreateJob}
            disabled={!selectedDocId}
            style={{padding: '6px 12px'}}
          >
            Queue Document
          </button>
        </div>

        <div style={{paddingLeft: '15px'}}>
          <LoadingButton
            onClick={handleCreateBulk}
            loading={isCreatingBulk}
            text="Queue Unprocessed (Max 20)"
            loadingText="Queueing..."
            style={{padding: '6px 12px'}}
          />
        </div>

        <div style={{paddingLeft: '15px', display: 'flex', gap: '10px', alignItems: 'center'}}>
          <button
            id="ingestion-refresh-btn"
            onClick={fetchJobs}
            disabled={loading}
            style={{padding: '6px 12px'}}
          >
            {loading ? 'Refreshing...' : '↻ Refresh'}
          </button>
          <select
            id="ingestion-filter-status"
            value={filterStatus}
            onChange={e => setFilterStatus(e.target.value)}
            style={{padding: '6px'}}
          >
            <option value="">All Statuses</option>
            <option value="queued">Queued</option>
            <option value="running">Running</option>
            <option value="paused">Paused</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
      </div>

      <div style={{borderRadius: '4px', overflowY: 'auto', maxHeight: '450px'}}>
        {jobs.length === 0 ? (
          <div style={{padding: '20px', textAlign: 'center'}}>No jobs found in queue.</div>
        ) : (
          <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '12px'}}>
            <thead>
              <tr style={{textAlign: 'left'}}>
                <th style={{padding: '8px'}}>Job ID</th>
                <th style={{padding: '8px'}}>Document</th>
                <th style={{padding: '8px'}}>Status</th>
                <th style={{padding: '8px'}}>Progress</th>
                <th style={{padding: '8px'}}>Attempts</th>
                <th style={{padding: '8px'}}>Created</th>
                <th style={{padding: '8px', minWidth: '200px'}}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(job => (
                <tr key={job.id} >
                  <td style={{padding: '8px', fontFamily: 'monospace'}} title={job.id}>
                    {job.id.substring(0, 8)}…
                  </td>
                  <td style={{padding: '8px', fontFamily: 'monospace'}} title={job.document_id}>
                    {job.document_id.substring(0, 8)}…
                  </td>
                  <td style={{padding: '8px'}}>
                    <span style={{fontWeight: 'bold'}}>
                      {job.status}
                      {job.pause_requested === 1 && (
                        <span style={{fontSize: '10px', marginLeft: '4px'}}>(pausing…)</span>
                      )}
                    </span>
                    {job.error && (
                      <div style={{fontSize: '10px', marginTop: '2px', maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}} title={job.error}>
                        {job.error}
                      </div>
                    )}
                  </td>
                  <td style={{padding: '8px'}}>
                    <StepProgress
                      requestedSteps={job.requested_steps || []}
                      completedSteps={job.completed_steps || []}
                      currentStep={job.current_step}
                      status={job.status}
                    />
                  </td>
                  <td style={{padding: '8px', textAlign: 'center'}}>
                    {job.attempts ?? 0}
                  </td>
                  <td style={{padding: '8px', whiteSpace: 'nowrap'}}>
                    {new Date(job.created_at).toLocaleTimeString()}
                  </td>
                  <td style={{padding: '8px'}}>
                    <div style={{display: 'flex', gap: '4px', flexWrap: 'wrap'}}>
                      {/* Run — for queued or failed */}
                      {(job.status === 'queued' || job.status === 'failed') && (
                        <ActionButton jobId={job.id} action="run" label="Run" color="#007bff" title="Run this job now" />
                      )}

                      {/* Pause — for running or queued */}
                      {(job.status === 'running' || job.status === 'queued') && job.pause_requested !== 1 && (
                        <ActionButton jobId={job.id} action="pause" label="Pause" color="#fd7e14" title="Pause before next step" />
                      )}

                      {/* Resume — for paused */}
                      {job.status === 'paused' && (
                        <ActionButton jobId={job.id} action="resume" label="Resume" color="#20c997" title="Resume from paused point" />
                      )}

                      {/* Retry (full) — for failed */}
                      {job.status === 'failed' && (
                        <ActionButton jobId={job.id} action="retry" label="Retry All" color="#6f42c1" title="Retry all steps from the beginning" />
                      )}

                      {/* Retry Step — for failed, only if partial steps completed */}
                      {job.status === 'failed' && (job.completed_steps || []).length > 0 && (
                        <ActionButton jobId={job.id} action="retry-step" label="Retry Step" color="#e83e8c" title="Retry only the failed step, skip completed" />
                      )}

                      {/* Cancel — for queued or paused */}
                      {(job.status === 'queued' || job.status === 'paused') && (
                        <ActionButton jobId={job.id} action="cancel" label="Cancel" color="#dc3545" title="Cancel this job" />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={{marginTop: '8px', fontSize: '11px'}}>
        <strong>EXT</strong> = Extract &nbsp;|&nbsp; <strong>CHK</strong> = Chunk &nbsp;|&nbsp; <strong>EMB</strong> = Embed &nbsp;|&nbsp; <strong>IDX</strong> = Index
        &nbsp;|&nbsp; Green = done, Blue = active, Gray = pending.
        Running jobs auto-refresh every 3 seconds.
      </div>
    </Section>
  );
}

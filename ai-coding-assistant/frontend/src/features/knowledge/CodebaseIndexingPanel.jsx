import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function CodebaseIndexingPanel({ kbs }) {
  const [limit, setLimit] = useState(50);
  const [createJobs, setCreateJobs] = useState(true);
  const [knowledgeBaseId, setKnowledgeBaseId] = useState('');

  const [isScanning, setIsScanning] = useState(false);
  const [scanStats, setScanStats] = useState(null);

  const [files, setFiles] = useState([]);
  const [isLoadingFiles, setIsLoadingFiles] = useState(false);

  const fetchFiles = async () => {
    setIsLoadingFiles(true);
    try {
      const data = await apiClient.getJson('/codebase/files');
      setFiles(data.files || []);
    } catch (err) {
      console.error("Failed to fetch codebase files:", err);
    }
    setIsLoadingFiles(false);
  };

  useEffect(() => {
    fetchFiles();
  }, []);

  const handleIndexCodebase = async () => {
    setIsScanning(true);
    setScanStats(null);
    try {
      const payload = {
        limit: parseInt(limit, 10) || 50,
        create_jobs: createJobs,
        knowledge_base_id: knowledgeBaseId || null
      };

      const data = await apiClient.postJson('/codebase/index', payload);
      setScanStats(data);
      fetchFiles();
    } catch (err) {
      alert(`Codebase indexing failed: ${err.message}`);
    }
    setIsScanning(false);
  };

  return (
    <Section title="Codebase Indexing (Phase 47)" description="Index the current workspace codebase to allow the AI to search project files.">
      <div style={{marginBottom: '20px', padding: '15px', borderRadius: '6px'}}>
        <h4 style={{margin: '0 0 10px 0'}}>Scan & Index Settings</h4>
        <div style={{display: 'flex', gap: '20px', alignItems: 'center', flexWrap: 'wrap'}}>
          <div>
            <label style={{fontSize: '12px', fontWeight: 'bold', display: 'block', marginBottom: '5px'}}>File Limit</label>
            <input
              type="number"
              value={limit}
              onChange={e => setLimit(e.target.value)}
              min="1"
              max="5000"
              style={{width: '80px', padding: '8px', borderRadius: '4px'}}
            />
          </div>
          <div>
            <label style={{fontSize: '12px', fontWeight: 'bold', display: 'block', marginBottom: '5px'}}>Knowledge Base (Optional)</label>
            <select
              value={knowledgeBaseId}
              onChange={e => setKnowledgeBaseId(e.target.value)}
              style={{width: '180px', padding: '8px', borderRadius: '4px'}}
            >
              <option value="">None</option>
              {(kbs || []).map(k => <option key={k.id} value={k.id}>{k.name}</option>)}
            </select>
          </div>
          <div style={{display: 'flex', alignItems: 'center', height: '100%', marginTop: '20px'}}>
            <label style={{display: 'flex', alignItems: 'center', gap: '5px', fontSize: '13px', cursor: 'pointer'}}>
              <input
                type="checkbox"
                checked={createJobs}
                onChange={e => setCreateJobs(e.target.checked)}
              />
              Create Ingestion Jobs
            </label>
          </div>
          <div style={{marginTop: '20px'}}>
            <LoadingButton
              onClick={handleIndexCodebase}
              loading={isScanning}
              loadingText="Scanning & Indexing..."
              text="Scan & Index Codebase"
            />
          </div>
        </div>

        {scanStats && (
          <div style={{marginTop: '15px', padding: '10px', borderRadius: '4px'}}>
            <strong>Scan Complete!</strong>
            <ul style={{margin: '5px 0 0 20px', padding: 0}}>
              <li>Created: {scanStats.created}</li>
              <li>Updated: {scanStats.updated}</li>
              <li>Unchanged: {scanStats.unchanged}</li>
              <li>Jobs Created: {scanStats.jobs_created}</li>
            </ul>
          </div>
        )}
      </div>

      <div>
        <h4 style={{margin: '0 0 10px 0'}}>Indexed Codebase Files ({files.length})</h4>
        {isLoadingFiles ? (
          <p>Loading files...</p>
        ) : files.length === 0 ? (
          <p style={{fontSize: '14px'}}>No codebase files indexed yet. Run the scanner above.</p>
        ) : (
          <div style={{maxHeight: '300px', overflowY: 'auto', borderRadius: '4px'}}>
            <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '13px'}}>
              <thead>
                <tr style={{textAlign: 'left'}}>
                  <th style={{padding: '8px'}}>Path</th>
                  <th style={{padding: '8px'}}>Language</th>
                  <th style={{padding: '8px'}}>Size</th>
                  <th style={{padding: '8px'}}>Status</th>
                </tr>
              </thead>
              <tbody>
                {files.map((f, idx) => (
                  <tr key={idx} >
                    <td style={{padding: '8px', wordBreak: 'break-all'}}>{f.relative_path}</td>
                    <td style={{padding: '8px'}}>{f.language}</td>
                    <td style={{padding: '8px'}}>{(f.file_size_bytes / 1024).toFixed(1)} KB</td>
                    <td style={{padding: '8px'}}>
                      {f.indexed ? 'Indexed' : 'Pending'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Section>
  );
}

import React, { useState } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';
import PipelineLog from './PipelineLog';

export default function DocumentUpload({ onUploadSuccess }) {
  const [file, setFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadedDoc, setUploadedDoc] = useState(null); // { document_id, filename }
  const [uploadError, setUploadError] = useState(null);

  const [techName, setTechName] = useState('');
  const [customUrl, setCustomUrl] = useState('');
  const [isUpdatingDocs, setIsUpdatingDocs] = useState(false);
  const [docsResult, setDocsResult] = useState(null);
  const [docsError, setDocsError] = useState(null);

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
    setUploadedDoc(null);
    setUploadError(null);
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file) return;
    setIsUploading(true);
    setUploadedDoc(null);
    setUploadError(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await apiClient.postForm('/documents/upload', formData);
      
      if (res.status === 'duplicate') {
        setUploadError(`Duplicate: this file already exists (ID: ${res.document_id})`);
      } else if (res.document_id) {
        setUploadedDoc({ document_id: res.document_id, filename: file.name });
        setFile(null);
        if (onUploadSuccess) onUploadSuccess();
      }
    } catch (err) {
      setUploadError(`Upload failed: ${err.message}`);
    }
    setIsUploading(false);
  };

  const handleUpdateDocs = async (e) => {
    e.preventDefault();
    if (!techName) return;
    setIsUpdatingDocs(true);
    setDocsResult(null);
    setDocsError(null);
    try {
      const payload = { technology: techName };
      if (customUrl) payload.custom_url = customUrl;
      const res = await apiClient.postJson('/documents/update-official-docs', payload);
      setDocsResult(res);
      setTechName('');
      setCustomUrl('');
      if (onUploadSuccess) onUploadSuccess();
    } catch (err) {
      setDocsError(`Docs update failed: ${err.message}`);
    }
    setIsUpdatingDocs(false);
  };

  return (
    <>
    <Section title="Upload Document" description="Upload a PDF — the pipeline runs automatically.">
      <form onSubmit={handleUpload} style={{ display: 'flex', gap: '10px', marginBottom: '16px' }}>
        <input type="file" accept=".pdf" onChange={handleFileChange} style={{ padding: '5px' }} />
        <LoadingButton
          type="submit"
          loading={isUploading}
          loadingText="Uploading..."
          text="Upload PDF"
          disabled={!file}
        />
      </form>

      {uploadError && (
        <div style={{ color: '#f87171', fontSize: '13px', marginBottom: '12px', padding: '8px', backgroundColor: '#1f0a0a', borderRadius: '6px' }}>
          {uploadError}
        </div>
      )}

      {uploadedDoc && (
        <div style={{ marginTop: '8px' }}>
          <div style={{ fontSize: '12px', color: '#34d399', marginBottom: '8px' }}>
            ✅ Uploaded successfully — pipeline started automatically
          </div>
          <PipelineLog documentId={uploadedDoc.document_id} filename={uploadedDoc.filename} />
        </div>
      )}
    </Section>

    <Section title="Update Official Docs" description="Fetch and ingest official stable documentation from the web.">
      <form onSubmit={handleUpdateDocs} style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '16px' }}>
        <div style={{ display: 'flex', gap: '10px' }}>
          <input 
            type="text" 
            value={techName}
            onChange={(e) => setTechName(e.target.value)}
            placeholder="e.g., React, FastAPI"
            style={{ padding: '5px 10px', borderRadius: '4px', border: '1px solid #475569', backgroundColor: '#1e293b', color: '#fff', flex: 1 }} 
          />
          <input 
            type="text" 
            value={customUrl}
            onChange={(e) => setCustomUrl(e.target.value)}
            placeholder="Custom URL (Optional)"
            style={{ padding: '5px 10px', borderRadius: '4px', border: '1px solid #475569', backgroundColor: '#1e293b', color: '#fff', flex: 2 }} 
          />
          <LoadingButton
            type="submit"
            loading={isUpdatingDocs}
            loadingText="Fetching Docs..."
            text="Update Docs"
            disabled={!techName}
          />
        </div>
      </form>

      {docsError && (
        <div style={{ color: '#f87171', fontSize: '13px', marginBottom: '12px', padding: '8px', backgroundColor: '#1f0a0a', borderRadius: '6px' }}>
          {docsError}
        </div>
      )}

      {docsResult && (
        <div style={{ marginTop: '8px', padding: '12px', backgroundColor: '#0f172a', borderRadius: '6px', border: '1px solid #334155' }}>
          <div style={{ fontSize: '13px', color: '#34d399', marginBottom: '8px', fontWeight: 'bold' }}>
            ✅ {docsResult.technology} documentation updated
          </div>
          <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
            <div><strong>Version:</strong> {docsResult.stable_version}</div>
            <div><strong>Source:</strong> <a href={docsResult.source_used} target="_blank" rel="noreferrer" style={{color: '#60a5fa'}}>{docsResult.source_used}</a></div>
            <div style={{ marginTop: '8px' }}>
              Added: <span style={{color: '#34d399'}}>{docsResult.chunks_added}</span> | 
              Updated: <span style={{color: '#60a5fa'}}>{docsResult.chunks_updated}</span> | 
              Skipped (unchanged): <span style={{color: '#94a3b8'}}>{docsResult.chunks_skipped}</span>
            </div>
            {docsResult.warnings?.length > 0 && (
              <div style={{ marginTop: '8px', color: '#fbbf24' }}>
                <strong>Warnings:</strong> {docsResult.warnings.join(', ')}
              </div>
            )}
          </div>
        </div>
      )}
    </Section>
    </>
  );
}

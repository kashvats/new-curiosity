import React, { useState, useRef } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';
import PipelineLog from './PipelineLog';

export default function BatchDocumentUpload({ onUploadSuccess }) {
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [results, setResults] = useState(null);
  const [uploadedDocs, setUploadedDocs] = useState([]); // [{document_id, filename}]

  const fileInputRef = useRef(null);

  const handleFileChange = (e) => {
    if (e.target.files) {
      setSelectedFiles(Array.from(e.target.files));
    }
  };

  const handleUpload = async () => {
    if (selectedFiles.length === 0) return alert("Please select at least one file");
    setIsUploading(true);
    setResults(null);
    setUploadedDocs([]);

    const formData = new FormData();
    selectedFiles.forEach(file => formData.append('files', file));

    try {
      const data = await apiClient.postForm('/documents/upload-batch', formData);
      setResults(data);
      // Collect successfully uploaded docs for pipeline log display
      const uploaded = (data.results || [])
        .filter(r => r.status === 'uploaded' && r.document_id)
        .map(r => ({ document_id: r.document_id, filename: r.original_filename }));
      setUploadedDocs(uploaded);
      if (onUploadSuccess) onUploadSuccess();
    } catch (err) {
      alert(`Batch upload failed: ${err.message}`);
    }

    setIsUploading(false);
    setSelectedFiles([]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const getStatusColor = (status) => {
    if (status === 'uploaded') return '#28a745';
    if (status === 'duplicate') return '#ffc107';
    if (status === 'failed') return '#dc3545';
    return '#6c757d';
  };

  return (
    <Section title="Batch Document Upload" description="Upload multiple PDF documents at once safely.">
      <div style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>

        <div style={{display: 'flex', gap: '15px', alignItems: 'center', flexWrap: 'wrap'}}>
          <input
            type="file"
            multiple
            accept="application/pdf"
            onChange={handleFileChange}
            ref={fileInputRef}
            style={{padding: '8px', borderRadius: '4px', flex: 1}}
          />
          <LoadingButton
            onClick={handleUpload}
            loading={isUploading}
            disabled={selectedFiles.length === 0}
            text={`Upload ${selectedFiles.length > 0 ? selectedFiles.length : ''} Files`}
            loadingText="Uploading..."
          />
        </div>

        {results && (
          <div style={{marginTop: '10px', borderRadius: '4px', padding: '15px'}}>
            <h4 style={{margin: '0 0 10px 0'}}>Upload Results</h4>
            <div style={{display: 'flex', gap: '15px', marginBottom: '15px', fontSize: '13px', fontWeight: 'bold'}}>
              <span>Total: {results.total_files}</span>
              <span>Uploaded: {results.uploaded_count}</span>
              <span>Duplicates: {results.duplicate_count}</span>
              <span>Failed: {results.failed_count}</span>
            </div>
          </div>
        )}

        {/* Live pipeline logs per uploaded document */}
        {uploadedDocs.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '8px' }}>
            <div style={{ fontSize: '12px', color: '#34d399' }}>✅ Pipeline started automatically for {uploadedDocs.length} file(s)</div>
            {uploadedDocs.map(doc => (
              <PipelineLog key={doc.document_id} documentId={doc.document_id} filename={doc.filename} />
            ))}
          </div>
        )}
      </div>
    </Section>
  );
}

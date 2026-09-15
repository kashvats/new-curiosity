import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function DocumentList({ documents, fetchDocuments }) {
  const [statusFilter, setStatusFilter] = useState('all');
  const [activeTab, setActiveTab] = useState('pdfs');
  const [officialDocs, setOfficialDocs] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(false);

  useEffect(() => {
    if (activeTab === 'official') {
      fetchOfficialDocs();
    }
  }, [activeTab]);

  const fetchOfficialDocs = async () => {
    setLoadingDocs(true);
    try {
      const data = await apiClient.getJson('/documents/official-docs');
      setOfficialDocs(data);
    } catch (err) {
      console.error('Failed to fetch official docs:', err);
    } finally {
      setLoadingDocs(false);
    }
  };

  const handleDeleteOfficialDoc = async (technology) => {
    if (!confirm(`Are you sure you want to delete ${technology} documentation from the database?`)) return;
    try {
      await apiClient.deleteJson(`/documents/official-docs/${encodeURIComponent(technology)}`);
      fetchOfficialDocs();
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  const handleAction = async (endpoint, docId) => {
    try {
      await apiClient.postJson(endpoint, {});
      fetchDocuments();
    } catch (err) {
      alert(`Action failed: ${err.message}`);
    }
  };

  const getDocStatus = (doc) => {
    if (doc.is_indexed || doc.qdrant_status === 'indexed') return 'ready';
    if (doc.is_embedded || doc.embedding_status === 'embedded') return 'embedded';
    if (doc.is_chunked || doc.chunking_status === 'chunked') return 'chunked';
    if (doc.is_extracted || doc.extraction_status === 'extracted') return 'extracted';
    return 'not_started';
  };

  const filteredDocs = documents.filter(doc => {
    if (statusFilter === 'all') return true;
    const status = getDocStatus(doc);
    return status === statusFilter;
  });

  const getStatusBadge = (status) => {
    switch (status) {
      case 'ready': return { label: 'Ready (Indexed)', color: '#3fb950', bg: '#3fb95022' };
      case 'embedded': return { label: 'Embedded', color: '#58a6ff', bg: '#58a6ff22' };
      case 'chunked': return { label: 'Chunked', color: '#d29922', bg: '#d2992222' };
      case 'extracted': return { label: 'Extracted', color: '#bc8cff', bg: '#bc8cff22' };
      default: return { label: 'Not Started', color: '#8b949e', bg: '#30363d' };
    }
  };

  const filters = [
    { id: 'all', label: 'All Documents' },
    { id: 'ready', label: 'Ready (Indexed)' },
    { id: 'embedded', label: 'Embedded' },
    { id: 'chunked', label: 'Chunked' },
    { id: 'extracted', label: 'Extracted' },
    { id: 'not_started', label: 'Not Started' }
  ];

  return (
    <Section title="Knowledge Base" description="Manage uploaded PDFs and official documentation for AI retrieval.">
      
      {/* Top Level Tabs */}
      <div style={{ display: 'flex', gap: '10px', marginBottom: '24px', borderBottom: '1px solid #30363d', paddingBottom: '16px' }}>
        <button
          onClick={() => setActiveTab('pdfs')}
          style={{
            padding: '8px 16px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: 600,
            cursor: 'pointer',
            border: 'none',
            backgroundColor: activeTab === 'pdfs' ? '#238636' : 'transparent',
            color: activeTab === 'pdfs' ? '#ffffff' : '#8b949e',
            transition: 'all 0.2s'
          }}
        >
          Learning Docs (PDFs)
        </button>
        <button
          onClick={() => setActiveTab('official')}
          style={{
            padding: '8px 16px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: 600,
            cursor: 'pointer',
            border: 'none',
            backgroundColor: activeTab === 'official' ? '#238636' : 'transparent',
            color: activeTab === 'official' ? '#ffffff' : '#8b949e',
            transition: 'all 0.2s'
          }}
        >
          Official Project Docs (Web)
        </button>
      </div>

      {activeTab === 'pdfs' ? (
      <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {filters.map(f => (
            <button
              key={f.id}
              onClick={() => setStatusFilter(f.id)}
              style={{
                padding: '6px 14px',
                borderRadius: '20px',
                fontSize: '13px',
                fontWeight: 600,
                cursor: 'pointer',
                border: `1px solid ${statusFilter === f.id ? '#58a6ff' : '#30363d'}`,
                backgroundColor: statusFilter === f.id ? '#58a6ff22' : '#0d1117',
                color: statusFilter === f.id ? '#58a6ff' : '#c9d1d9',
                transition: 'all 0.2s'
              }}
            >
              {f.label}
            </button>
          ))}
        </div>
        <button 
          onClick={fetchDocuments} 
          className="btn"
          style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
        >
          <span>↻</span> Refresh List
        </button>
      </div>

      {documents.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', backgroundColor: '#161b22', borderRadius: '12px', border: '1px solid #30363d' }}>
          <div style={{ fontSize: '32px', marginBottom: '12px', opacity: 0.5 }}>📄</div>
          <p style={{ margin: 0, color: '#8b949e' }}>No documents uploaded yet.</p>
        </div>
      ) : filteredDocs.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', backgroundColor: '#161b22', borderRadius: '12px', border: '1px solid #30363d' }}>
          <p style={{ margin: 0, color: '#8b949e' }}>No documents match the "{filters.find(f => f.id === statusFilter).label}" filter.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))', gap: '20px' }}>
          {filteredDocs.map(doc => {
            const currentStatus = getDocStatus(doc);
            const badge = getStatusBadge(currentStatus);
            
            return (
              <div key={doc.id} style={{
                padding: '20px', 
                backgroundColor: '#161b22', 
                border: '1px solid #30363d', 
                borderRadius: '12px',
                position: 'relative',
                overflow: 'hidden',
                transition: 'transform 0.2s, box-shadow 0.2s'
              }}
              onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 8px 16px rgba(0,0,0,0.2)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none'; }}>
                
                {/* Status Indicator Bar */}
                <div style={{ position: 'absolute', top: 0, left: 0, height: '4px', width: '100%', backgroundColor: badge.color }} />
                
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
                  <div style={{ overflow: 'hidden' }}>
                    <h3 style={{ margin: '0 0 4px 0', fontSize: '16px', fontWeight: 600, color: '#e6edf3', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {doc.original_filename || doc.filename}
                    </h3>
                    <div style={{ fontSize: '11px', color: '#8b949e', fontFamily: 'monospace' }}>ID: {doc.id.split('-')[0]}...</div>
                  </div>
                  <div style={{display: 'flex', gap: '5px'}}>
                    {doc.source_type && doc.source_type !== 'pdf' && (
                      <span style={{ 
                        fontSize: '11px', padding: '4px 10px', borderRadius: '12px', fontWeight: 600,
                        backgroundColor: '#1f6feb22', color: '#58a6ff', whiteSpace: 'nowrap'
                      }}>
                        {doc.source_type === 'web_summary' ? 'Web Summary' : 
                         doc.source_type === 'manual_note' ? 'Manual Note' : 'PDF'}
                      </span>
                    )}
                    <span style={{ 
                      fontSize: '11px', padding: '4px 10px', borderRadius: '12px', fontWeight: 600,
                      backgroundColor: badge.bg, color: badge.color, whiteSpace: 'nowrap'
                    }}>
                      {badge.label}
                    </span>
                  </div>
                </div>
                
                <div style={{ fontSize: '12px', color: '#8b949e', marginBottom: '20px', backgroundColor: '#0d1117', padding: '10px', borderRadius: '8px' }}>
                  <div style={{ marginBottom: '4px' }}><strong>Hash:</strong> <span style={{ fontFamily: 'monospace' }}>{doc.file_hash?.substring(0, 16)}...</span></div>
                  <div><strong>Knowledge Bases:</strong> {(doc.knowledge_bases || []).map(kb => kb.name).join(', ') || 'None'}</div>
                </div>
                
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  <LoadingButton 
                    loading={false} 
                    text="Extract" 
                    onClick={() => handleAction(`/documents/${doc.id}/extract`, doc.id)} 
                    disabled={doc.is_extracted || doc.extraction_status === 'extracted'} 
                    style={{ padding: '6px 12px', fontSize: '12px', flex: 1, minWidth: '80px' }}
                  />
                  <LoadingButton 
                    loading={false} 
                    text="Chunk" 
                    onClick={() => handleAction(`/documents/${doc.id}/chunk`, doc.id)} 
                    disabled={!(doc.is_extracted || doc.extraction_status === 'extracted') || doc.is_chunked || doc.chunking_status === 'chunked'} 
                    style={{ padding: '6px 12px', fontSize: '12px', flex: 1, minWidth: '80px' }}
                  />
                  <LoadingButton 
                    loading={false} 
                    text="Embed" 
                    onClick={() => handleAction(`/documents/${doc.id}/embed`, doc.id)} 
                    disabled={!(doc.is_chunked || doc.chunking_status === 'chunked') || doc.is_embedded || doc.embedding_status === 'embedded'} 
                    style={{ padding: '6px 12px', fontSize: '12px', flex: 1, minWidth: '80px' }}
                  />
                  <LoadingButton 
                    loading={false} 
                    text="Index" 
                    onClick={() => handleAction(`/documents/${doc.id}/index`, doc.id)} 
                    disabled={!(doc.is_embedded || doc.embedding_status === 'embedded') || doc.is_indexed || doc.qdrant_status === 'indexed'} 
                    style={{ padding: '6px 12px', fontSize: '12px', flex: 1, minWidth: '80px' }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
      </>
      ) : (
      <>
        {/* Official Project Docs View */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <h3 style={{ margin: 0, color: '#e6edf3', fontSize: '18px' }}>Official Documentations</h3>
          <button 
            onClick={fetchOfficialDocs} 
            className="btn"
            style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
          >
            <span>↻</span> Refresh List
          </button>
        </div>

        {loadingDocs ? (
          <div style={{ padding: '40px', textAlign: 'center', color: '#8b949e' }}>Loading documentation...</div>
        ) : officialDocs.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', backgroundColor: '#161b22', borderRadius: '12px', border: '1px solid #30363d' }}>
            <div style={{ fontSize: '32px', marginBottom: '12px', opacity: 0.5 }}>🌐</div>
            <p style={{ margin: 0, color: '#8b949e' }}>No official project documentation has been ingested yet.</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto', backgroundColor: '#161b22', borderRadius: '12px', border: '1px solid #30363d' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '14px' }}>
              <thead>
                <tr style={{ backgroundColor: '#0d1117', borderBottom: '1px solid #30363d' }}>
                  <th style={{ padding: '16px', color: '#c9d1d9', fontWeight: 600 }}>Technology</th>
                  <th style={{ padding: '16px', color: '#c9d1d9', fontWeight: 600 }}>Version</th>
                  <th style={{ padding: '16px', color: '#c9d1d9', fontWeight: 600 }}>Source URL</th>
                  <th style={{ padding: '16px', color: '#c9d1d9', fontWeight: 600 }}>Chunks Indexed</th>
                  <th style={{ padding: '16px', color: '#c9d1d9', fontWeight: 600, textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {officialDocs.map(doc => (
                  <tr key={doc.technology} style={{ borderBottom: '1px solid #30363d', transition: 'background-color 0.2s' }}>
                    <td style={{ padding: '16px', color: '#e6edf3', fontWeight: 600 }}>{doc.technology}</td>
                    <td style={{ padding: '16px', color: '#8b949e' }}>{doc.version || 'latest'}</td>
                    <td style={{ padding: '16px' }}>
                      <a href={doc.source_url} target="_blank" rel="noreferrer" style={{ color: '#58a6ff', textDecoration: 'none' }}>
                        {doc.source_url} ↗
                      </a>
                    </td>
                    <td style={{ padding: '16px', color: '#8b949e' }}>{doc.chunk_count} chunks</td>
                    <td style={{ padding: '16px', textAlign: 'right' }}>
                      <button 
                        onClick={() => handleDeleteOfficialDoc(doc.technology)}
                        style={{
                          padding: '6px 12px',
                          backgroundColor: '#da363322',
                          color: '#ff7b72',
                          border: '1px solid #da3633',
                          borderRadius: '6px',
                          cursor: 'pointer',
                          fontSize: '12px',
                          fontWeight: 600,
                          transition: 'all 0.2s'
                        }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </>
      )}
    </Section>
  );
}

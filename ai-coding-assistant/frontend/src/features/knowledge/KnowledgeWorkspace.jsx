/**
 * KnowledgeWorkspace.jsx
 *
 * Unified single-page Knowledge workspace.
 * Layout:
 *   Left sidebar  — document list with live pipeline status badges
 *   Right pane    — contextual view based on selected tab:
 *                   Upload | Pipeline | Search | Chat | Notes
 *
 * Rules:
 *   - No navigation away from this page
 *   - Pipeline tab is always visible; shows the terminal log component
 *   - Search & Chat tabs are disabled until at least 1 document is indexed
 *   - Failed pipeline stages get a manual "Retry" button
 *   - No manual Extract / Chunk / Embed / Index buttons anywhere
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { apiClient } from '../../api/client';
import PipelineLog from '../documents/PipelineLog';

// ─── Constants ───────────────────────────────────────────────────────────────

const TABS = [
  { id: 'upload',   label: '⬆ Upload' },
  { id: 'pipeline', label: '⚙ Pipeline' },
  { id: 'notes',    label: '📝 Notes' },
];

const PIPELINE_STATUS_COLOR = {
  indexed:    '#34d399',
  indexing:   '#60a5fa',
  embedded:   '#818cf8',
  chunked:    '#a78bfa',
  extracted:  '#f59e0b',
  failed:     '#f87171',
  duplicate:  '#6b7280',
  not_started:'#374151',
  uploading:  '#60a5fa',
};

const PIPELINE_STATUS_ICON = {
  indexed:    '✅',
  indexing:   '⟳',
  embedded:   '◕',
  chunked:    '◑',
  extracted:  '◔',
  failed:     '✗',
  duplicate:  '≡',
  not_started:'○',
};

function getDocOverallStatus(doc) {
  if (doc.status === 'duplicate') return 'duplicate';
  if (doc.qdrant_status === 'indexed') return 'indexed';
  if (doc.qdrant_status === 'indexing' || doc.embedding_status === 'embedding') return 'indexing';
  if (doc.qdrant_status === 'failed' || doc.embedding_status === 'failed' || doc.extraction_status === 'failed') return 'failed';
  if (doc.embedding_status === 'embedded') return 'embedded';
  if (doc.chunking_status === 'chunked') return 'chunked';
  if (doc.extraction_status === 'extracted') return 'extracted';
  return 'not_started';
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const color = PIPELINE_STATUS_COLOR[status] || '#374151';
  const icon  = PIPELINE_STATUS_ICON[status]  || '○';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '4px',
      fontSize: '10px', padding: '2px 7px', borderRadius: '10px',
      backgroundColor: `${color}22`, border: `1px solid ${color}55`, color,
      fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em',
      flexShrink: 0,
    }}>
      {icon} {status.replace('_', ' ')}
    </span>
  );
}

// ─── Upload Tab ──────────────────────────────────────────────────────────────

function UploadTab({ onUploadDone }) {
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [justUploaded, setJustUploaded] = useState([]);
  const [error, setError] = useState(null);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef();

  const doUpload = async (fileList) => {
    const pdfs = Array.from(fileList).filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (!pdfs.length) { setError('Only PDF files are supported.'); return; }
    setUploading(true); setError(null); setJustUploaded([]);

    const results = [];
    for (const file of pdfs) {
      const fd = new FormData();
      fd.append('file', file);
      try {
        const res = await apiClient.postForm('/documents/upload', fd);
        results.push({ filename: file.name, ...res });
      } catch (e) {
        results.push({ filename: file.name, status: 'error', message: e.message });
      }
    }

    const uploaded = results.filter(r => r.document_id && r.status === 'uploaded');
    setJustUploaded(uploaded);
    setUploading(false);
    setFiles([]);
    if (inputRef.current) inputRef.current.value = '';
    onUploadDone();
  };

  const handleDrop = (e) => {
    e.preventDefault(); setDrag(false);
    doUpload(e.dataTransfer.files);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Drop zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        style={{
          border: `2px dashed ${drag ? '#60a5fa' : '#374151'}`,
          borderRadius: '12px',
          padding: '48px 24px',
          textAlign: 'center',
          cursor: 'pointer',
          backgroundColor: drag ? '#1e2a3a' : '#0d1117',
          transition: 'all 0.2s',
        }}
      >
        <div style={{ fontSize: '36px', marginBottom: '12px' }}>📄</div>
        <div style={{ color: '#9ca3af', fontSize: '14px' }}>
          {uploading ? 'Uploading…' : 'Drop PDFs here or click to browse'}
        </div>
        <div style={{ color: '#4b5563', fontSize: '12px', marginTop: '6px' }}>
          Pipeline runs automatically after upload
        </div>
        <input ref={inputRef} type="file" accept=".pdf" multiple hidden
          onChange={e => doUpload(e.target.files)} />
      </div>

      {error && (
        <div style={{ color: '#f87171', fontSize: '13px', padding: '10px', backgroundColor: '#1f0a0a', borderRadius: '8px' }}>
          ⚠ {error}
        </div>
      )}

      {/* Live pipeline logs for just-uploaded docs */}
      {justUploaded.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ fontSize: '12px', color: '#34d399', fontWeight: 600 }}>
            ✅ {justUploaded.length} file(s) uploaded — pipeline started automatically
          </div>
          {justUploaded.map(doc => (
            <PipelineLog key={doc.document_id} documentId={doc.document_id} filename={doc.filename} />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Pipeline Tab ─────────────────────────────────────────────────────────────

function PipelineTab({ selectedDoc, onRetry, onDelete }) {
  if (!selectedDoc) {
    return (
      <div style={{ color: '#4b5563', fontSize: '14px', padding: '40px', textAlign: 'center' }}>
        Select a document from the list to view its pipeline status.
      </div>
    );
  }

  const status = getDocOverallStatus(selectedDoc);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Stage-by-stage tracker */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0', marginBottom: '8px' }}>
        {[
          { label: 'Extract',   key: 'extraction_status',  done: 'extracted' },
          { label: 'Chunk',     key: 'chunking_status',    done: 'chunked' },
          { label: 'Embed',     key: 'embedding_status',   done: 'embedded' },
          { label: 'Index',     key: 'qdrant_status',      done: 'indexed' },
        ].map((step, i) => {
          const val = selectedDoc[step.key] || 'not_started';
          const done = val === step.done;
          const failed = val === 'failed';
          const active = !done && !failed && val !== 'not_started';
          const color = failed ? '#f87171' : done ? '#34d399' : active ? '#60a5fa' : '#374151';
          return (
            <React.Fragment key={step.key}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1 }}>
                <div style={{
                  width: '32px', height: '32px', borderRadius: '50%',
                  backgroundColor: `${color}22`, border: `2px solid ${color}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '14px', color,
                }}>
                  {failed ? '✗' : done ? '✓' : active ? '⟳' : '○'}
                </div>
                <div style={{ fontSize: '10px', marginTop: '4px', color, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  {step.label}
                </div>
                <div style={{ fontSize: '9px', color: '#4b5563' }}>{val}</div>
              </div>
              {i < 3 && (
                <div style={{ flex: 2, height: '2px', backgroundColor: done ? '#34d399' : '#1f2937', marginBottom: '20px' }} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Live terminal log */}
      <PipelineLog documentId={selectedDoc.id} filename={selectedDoc.original_filename || selectedDoc.filename} />

      {/* Manual Trigger / Retry / Delete buttons */}
      <div style={{ display: 'flex', gap: '10px' }}>
        {status !== 'indexed' && (
          <button
            onClick={() => onRetry(selectedDoc.id)}
            style={{
              flex: 1, padding: '10px 20px', 
              backgroundColor: status === 'failed' ? '#7f1d1d' : '#1d4ed8', 
              color: status === 'failed' ? '#fca5a5' : '#fff',
              border: `1px solid ${status === 'failed' ? '#f87171' : '#3b82f6'}`, 
              borderRadius: '8px', cursor: 'pointer',
              fontSize: '13px', fontWeight: 600,
            }}
          >
            {status === 'failed' ? '↺ Retry Pipeline' : '▶ Manually Trigger Pipeline'}
          </button>
        )}
        <button
          onClick={() => onDelete(selectedDoc.id)}
          style={{
            flex: status === 'indexed' ? 1 : 'none', padding: '10px 20px', 
            backgroundColor: '#1f0a0a', color: '#f87171',
            border: '1px solid #7f1d1d', borderRadius: '8px', cursor: 'pointer',
            fontSize: '13px', fontWeight: 600,
          }}
        >
          🗑 Delete / Stop
        </button>
      </div>
    </div>
  );
}

// ─── Search Tab ──────────────────────────────────────────────────────────────

function SearchTab({ documents, kbs }) {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('vector');
  const [docId, setDocId] = useState('');
  const [kbId, setKbId] = useState('');
  const [rerank, setRerank] = useState(false);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true); setError(null); setResults([]);
    try {
      let url = `/search?q=${encodeURIComponent(query)}&search_mode=${mode}`;
      if (docId) url += `&document_id=${docId}`;
      if (kbId)  url += `&knowledge_base_id=${kbId}`;
      if (rerank) url += '&rerank=true';
      const data = await apiClient.getJson(url);
      setResults(data.results || []);
    } catch (e) { setError(e.message); }
    setLoading(false);
  };

  const indexedDocs = documents.filter(d => d.qdrant_status === 'indexed');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <form onSubmit={handleSearch} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <input
          value={query} onChange={e => setQuery(e.target.value)}
          placeholder="Search your knowledge base…"
          style={{ padding: '10px 14px', borderRadius: '8px', border: '1px solid #374151', backgroundColor: '#0d1117', color: '#e6edf3', fontSize: '14px' }}
        />
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <select value={mode} onChange={e => setMode(e.target.value)}
            style={{ padding: '7px', borderRadius: '6px', border: '1px solid #374151', backgroundColor: '#161b22', color: '#e6edf3', fontSize: '13px' }}>
            <option value="vector">Vector</option>
            <option value="keyword">Keyword</option>
            <option value="hybrid">Hybrid</option>
          </select>
          <select value={docId} onChange={e => setDocId(e.target.value)}
            style={{ padding: '7px', borderRadius: '6px', border: '1px solid #374151', backgroundColor: '#161b22', color: '#e6edf3', fontSize: '13px', flex: 1 }}>
            <option value="">All Documents</option>
            {indexedDocs.map(d => <option key={d.id} value={d.id}>{d.original_filename || d.filename}</option>)}
          </select>
          {kbs.length > 0 && (
            <select value={kbId} onChange={e => setKbId(e.target.value)}
              style={{ padding: '7px', borderRadius: '6px', border: '1px solid #374151', backgroundColor: '#161b22', color: '#e6edf3', fontSize: '13px', flex: 1 }}>
              <option value="">All KBs</option>
              {kbs.map(kb => <option key={kb.id} value={kb.id}>{kb.name}</option>)}
            </select>
          )}
          <label style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '13px', color: '#9ca3af', cursor: 'pointer' }}>
            <input type="checkbox" checked={rerank} onChange={e => setRerank(e.target.checked)} />
            Rerank
          </label>
          <button type="submit" disabled={loading}
            style={{ padding: '7px 18px', backgroundColor: '#1d4ed8', color: '#fff', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}>
            {loading ? '…' : 'Search'}
          </button>
        </div>
      </form>

      {error && <div style={{ color: '#f87171', fontSize: '13px' }}>⚠ {error}</div>}

      {results.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {results.map((r, i) => (
            <div key={i} style={{ padding: '12px', backgroundColor: '#0d1117', border: '1px solid #21262d', borderRadius: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ fontSize: '12px', color: '#6e7681' }}>{r.filename} · pg {r.page_start}–{r.page_end}</span>
                <span style={{ fontSize: '11px', color: '#34d399' }}>score {(r.score || 0).toFixed(3)}</span>
              </div>
              <div style={{ fontSize: '13px', color: '#e6edf3', lineHeight: '1.6' }}>{r.text?.slice(0, 400)}…</div>
            </div>
          ))}
        </div>
      )}
      {results.length === 0 && !loading && query && !error && (
        <div style={{ color: '#4b5563', fontSize: '13px' }}>No results found.</div>
      )}
    </div>
  );
}



// ─── Notes Tab ───────────────────────────────────────────────────────────────

function NotesTab({ kbs }) {
  const [note, setNote] = useState('');
  const [title, setTitle] = useState('');
  const [kbId, setKbId] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  const handleSave = async () => {
    if (!title.trim() || !note.trim()) return setError('Title and content are required.');
    setSaving(true); setError(null); setSaved(false);
    try {
      await apiClient.postJson('/knowledge/notes', { title, content: note, knowledge_base_id: kbId || null });
      setSaved(true); setNote(''); setTitle('');
    } catch (e) { setError(e.message); }
    setSaving(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Note title…"
        style={{ padding: '10px 14px', borderRadius: '8px', border: '1px solid #374151', backgroundColor: '#0d1117', color: '#e6edf3', fontSize: '14px' }} />
      {kbs.length > 0 && (
        <select value={kbId} onChange={e => setKbId(e.target.value)}
          style={{ padding: '8px', borderRadius: '6px', border: '1px solid #374151', backgroundColor: '#161b22', color: '#e6edf3', fontSize: '13px' }}>
          <option value="">No Knowledge Base</option>
          {kbs.map(kb => <option key={kb.id} value={kb.id}>{kb.name}</option>)}
        </select>
      )}
      <textarea value={note} onChange={e => setNote(e.target.value)} placeholder="Write your note here…" rows={10}
        style={{ padding: '10px 14px', borderRadius: '8px', border: '1px solid #374151', backgroundColor: '#0d1117', color: '#e6edf3', fontSize: '14px', resize: 'vertical', fontFamily: 'inherit', lineHeight: '1.6' }} />
      {error && <div style={{ color: '#f87171', fontSize: '13px' }}>⚠ {error}</div>}
      {saved && <div style={{ color: '#34d399', fontSize: '13px' }}>✅ Note saved and indexed.</div>}
      <button onClick={handleSave} disabled={saving}
        style={{ padding: '10px 20px', backgroundColor: '#1d4ed8', color: '#fff', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
        {saving ? 'Saving…' : 'Save & Index Note'}
      </button>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function KnowledgeWorkspace({ kbs = [] }) {
  const [documents, setDocuments] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [tab, setTab] = useState('upload');
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [loading, setLoading] = useState(true);

  const fetchDocuments = useCallback(async () => {
    try {
      const data = await apiClient.getJson('/documents');
      const docs = Array.isArray(data) ? data : (data.documents || []);
      setDocuments(docs);
    } catch (e) {
      console.error('Failed to fetch documents', e);
    } finally {
      setLoading(false);
    }
  }, []);

  // Connect to WebSocket for real-time document list updates
  useEffect(() => {
    // Initial fetch
    fetchDocuments();
    
    const wsUrl = `ws://127.0.0.1:8000/documents/ws`;
    const socket = new WebSocket(wsUrl);

    socket.onopen = () => console.log('Documents WS Connected');
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.documents) {
        setDocuments(data.documents);
      }
    };
    socket.onclose = () => console.log('Documents WS Disconnected');

    return () => socket.close();
  }, [fetchDocuments]);

  const handleRetry = async (docId) => {
    // Re-trigger the pipeline by dispatching ingest event via the backend
    try {
      await apiClient.postJson(`/documents/${docId}/process`, {});
      fetchDocuments();
    } catch (e) {
      console.error('Retry failed', e);
    }
  };

  const handleDelete = async (docId) => {
    if (!window.confirm('Are you sure you want to permanently delete this document and stop its processing?')) return;
    try {
      await apiClient.deleteJson(`/documents/${docId}`);
      if (selectedDocId === docId) {
        setSelectedDocId(null);
        setTab('upload');
      }
      fetchDocuments();
    } catch (e) {
      console.error('Delete failed', e);
      alert('Failed to delete document: ' + e.message);
    }
  };

  const selectedDoc = documents.find(d => d.id === selectedDocId) || null;
  const hasIndexed   = documents.some(d => d.qdrant_status === 'indexed');
  const filteredDocs = documents.filter(d => {
    const name = (d.original_filename || d.filename || '').toLowerCase();
    if (!name.includes(search.toLowerCase())) return false;
    
    if (filterStatus === 'all') return true;
    const s = getDocOverallStatus(d);
    if (filterStatus === 'ready') return s === 'indexed';
    if (filterStatus === 'processing') return ['extracted','chunked','embedded','indexing'].includes(s);
    if (filterStatus === 'failed') return s === 'failed';
    if (filterStatus === 'other') return ['not_started','duplicate'].includes(s);
    return true;
  });

  const groupedDocs = {
    ready:      filteredDocs.filter(d => getDocOverallStatus(d) === 'indexed'),
    processing: filteredDocs.filter(d => ['extracted','chunked','embedded','indexing'].includes(getDocOverallStatus(d))),
    failed:     filteredDocs.filter(d => getDocOverallStatus(d) === 'failed'),
    other:      filteredDocs.filter(d => ['not_started','duplicate'].includes(getDocOverallStatus(d))),
  };

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '280px 1fr',
      height: 'calc(100vh - 120px)',
      gap: '0',
      border: '1px solid #21262d',
      borderRadius: '12px',
      overflow: 'hidden',
      backgroundColor: '#0d1117',
    }}>
      {/* ── Left: Document List ── */}
      <div style={{
        borderRight: '1px solid #21262d',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: '#010409',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ padding: '14px 14px 10px', borderBottom: '1px solid #21262d', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ fontSize: '11px', color: '#6e7681', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Documents ({documents.length})
          </div>
          <select
            value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
            style={{ width: '100%', padding: '6px', borderRadius: '6px', border: '1px solid #21262d', backgroundColor: '#161b22', color: '#e6edf3', fontSize: '12px', outline: 'none' }}
          >
            <option value="all">All Documents</option>
            <option value="ready">✅ Indexed</option>
            <option value="processing">⟳ In Process</option>
            <option value="failed">❌ Failed</option>
            <option value="other">○ Pending</option>
          </select>
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search..."
            style={{ width: '100%', padding: '6px 10px', borderRadius: '6px', border: '1px solid #21262d', backgroundColor: '#0d1117', color: '#e6edf3', fontSize: '12px', boxSizing: 'border-box' }}
          />
        </div>

        {/* Upload shortcut */}
        <div
          onClick={() => setTab('upload')}
          style={{
            padding: '10px 14px', fontSize: '12px', color: tab === 'upload' ? '#60a5fa' : '#6e7681',
            cursor: 'pointer', borderBottom: '1px solid #21262d',
            backgroundColor: tab === 'upload' ? '#1c2d4f' : 'transparent',
            display: 'flex', alignItems: 'center', gap: '8px',
          }}
        >
          ⬆ Upload New Document
        </div>

        {/* List */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loading && <div style={{ color: '#4b5563', fontSize: '12px', padding: '16px' }}>Loading…</div>}

          {!loading && documents.length === 0 && (
            <div style={{ color: '#4b5563', fontSize: '12px', padding: '16px', textAlign: 'center' }}>
              No documents yet.<br />Upload a PDF to get started.
            </div>
          )}

          {[
            { label: '✅ Indexed', docs: groupedDocs.ready },
            { label: '⟳ Processing', docs: groupedDocs.processing },
            { label: '❌ Failed', docs: groupedDocs.failed },
            { label: '○ Pending', docs: groupedDocs.other },
          ].map(group => group.docs.length === 0 ? null : (
            <div key={group.label}>
              <div style={{ padding: '8px 14px 4px', fontSize: '9px', color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                {group.label}
              </div>
              {group.docs.map(doc => {
                const status = getDocOverallStatus(doc);
                const color  = PIPELINE_STATUS_COLOR[status] || '#374151';
                const selected = doc.id === selectedDocId;
                return (
                  <div
                    key={doc.id}
                    onClick={() => { setSelectedDocId(doc.id); setTab('pipeline'); }}
                    style={{
                      padding: '9px 14px',
                      cursor: 'pointer',
                      backgroundColor: selected ? '#1c2d4f' : 'transparent',
                      borderLeft: `3px solid ${selected ? color : 'transparent'}`,
                      display: 'flex', flexDirection: 'column', gap: '3px',
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={e => { if (!selected) e.currentTarget.style.backgroundColor = '#0d1117'; }}
                    onMouseLeave={e => { if (!selected) e.currentTarget.style.backgroundColor = 'transparent'; }}
                  >
                    <div style={{ fontSize: '12px', color: '#e6edf3', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {doc.original_filename || doc.filename}
                    </div>
                    <StatusBadge status={status} />
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Refresh */}
        <div style={{ padding: '10px 14px', borderTop: '1px solid #21262d' }}>
          <button onClick={fetchDocuments}
            style={{ width: '100%', padding: '6px', backgroundColor: '#161b22', color: '#6e7681', border: '1px solid #21262d', borderRadius: '6px', cursor: 'pointer', fontSize: '11px' }}>
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* ── Right: Content pane ── */}
      <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid #21262d', backgroundColor: '#010409', flexShrink: 0 }}>
          {TABS.map(t => {
            const disabled = t.requiresIndexed && !hasIndexed;
            const active   = tab === t.id;
            return (
              <div
                key={t.id}
                onClick={() => !disabled && setTab(t.id)}
                title={disabled ? 'Index at least one document to enable this' : undefined}
                style={{
                  padding: '12px 18px',
                  fontSize: '13px',
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  color: disabled ? '#374151' : active ? '#60a5fa' : '#6e7681',
                  borderBottom: active ? '2px solid #60a5fa' : '2px solid transparent',
                  transition: 'color 0.15s',
                  whiteSpace: 'nowrap',
                  userSelect: 'none',
                }}
              >
                {t.label}
                {disabled && <span style={{ fontSize: '9px', marginLeft: '4px', color: '#374151' }}>🔒</span>}
              </div>
            );
          })}
        </div>

        {/* Tab content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
          {tab === 'upload'   && <UploadTab onUploadDone={fetchDocuments} />}
          {tab === 'pipeline' && <PipelineTab selectedDoc={selectedDoc} onRetry={handleRetry} onDelete={handleDelete} />}
          {tab === 'search'   && <SearchTab  documents={documents} kbs={kbs} />}
          {tab === 'notes'    && <NotesTab   kbs={kbs} />}
        </div>
      </div>
    </div>
  );
}

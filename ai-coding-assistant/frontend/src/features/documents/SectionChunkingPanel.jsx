import React, { useState, useCallback } from 'react';
import Section from '../../components/Section';
import { apiClient } from '../../api/client';

const LEVEL_LABELS = { 1: 'Chapter', 2: 'Section', 3: 'Subsection', 4: 'Sub-subsection' };
const LEVEL_COLORS = { 1: '#2c3e50', 2: '#2980b9', 3: '#27ae60', 4: '#8e44ad' };
const LEVEL_INDENT = { 1: 0, 2: 16, 3: 32, 4: 48 };

function SectionRow({ sec }) {
  const [expanded, setExpanded] = useState(false);
  const level = sec.level || 1;
  return (
    <div style={{marginLeft: LEVEL_INDENT[level] || 0,
      padding: '6px 10px',
      marginBottom: '6px',
      borderRadius: '0 4px 4px 0',
      cursor: sec.text_preview ? 'pointer' : 'default'}} onClick={() => sec.text_preview && setExpanded(e => !e)}>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
        <div>
          <span style={{fontSize: '10px',
            fontWeight: 'bold',
            marginRight: '8px',
            textTransform: 'uppercase'}}>
            {LEVEL_LABELS[level] || `Level ${level}`}
          </span>
          <span style={{fontWeight: level === 1 ? 'bold' : 'normal', fontSize: '13px'}}>
            {sec.title}
          </span>
        </div>
        <span style={{fontSize: '11px', whiteSpace: 'nowrap', marginLeft: '12px'}}>
          {sec.page_start != null && sec.page_end != null
            ? `pp. ${sec.page_start}–${sec.page_end}`
            : ''}
          {sec.text_preview ? (expanded ? ' ▲' : ' ▼') : ''}
        </span>
      </div>
      {expanded && sec.text_preview && (
        <div style={{marginTop: '6px',
          fontSize: '11px',
          padding: '6px 8px',
          borderRadius: '3px',
          maxHeight: '120px',
          overflowY: 'auto',
          whiteSpace: 'pre-wrap',
          fontFamily: 'monospace'}}>
          {sec.text_preview}
        </div>
      )}
    </div>
  );
}

export default function SectionChunkingPanel({ documents }) {
  const [selectedDocId, setSelectedDocId] = useState('');
  const [chunkSize, setChunkSize] = useState(900);
  const [overlapTokens, setOverlapTokens] = useState(120);
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [chunkResult, setChunkResult] = useState(null);
  const [sections, setSections] = useState([]);
  const [sectionsLoading, setSectionsLoading] = useState(false);
  const [showSections, setShowSections] = useState(false);
  const [busy, setBusy] = useState(false);

  const extractedDocs = (documents || []).filter(
    d => d.extraction_status === 'extracted' && d.status !== 'duplicate'
  );

  const handleSectionChunk = async () => {
    if (!selectedDocId) return alert('Select a document first.');
    if (replaceExisting && !window.confirm(
      'Replace existing section chunks? This will delete previous section chunks. Re-embed and re-index will be required.'
    )) return;

    setBusy(true);
    setChunkResult(null);
    setSections([]);
    setShowSections(false);
    try {
      const res = await apiClient.postJson(`/documents/${selectedDocId}/chunk/sections`, {
        chunk_size_tokens: Number(chunkSize),
        overlap_tokens: Number(overlapTokens),
        replace_existing: replaceExisting,
      });
      setChunkResult(res);
    } catch (err) {
      setChunkResult({ status: 'error', message: err.message });
    }
    setBusy(false);
  };

  const handleViewSections = useCallback(async () => {
    if (!selectedDocId) return;
    setSectionsLoading(true);
    setShowSections(true);
    try {
      const res = await apiClient.getJson(`/documents/${selectedDocId}/sections`);
      setSections(res.sections || []);
    } catch (err) {
      setSections([]);
      alert(`Failed to load sections: ${err.message}`);
    }
    setSectionsLoading(false);
  }, [selectedDocId]);

  return (
    <Section
      title="Section-Aware Chunking"
      description="Detect chapters, sections, and subsections and create smart chunks with heading metadata. Existing basic chunks are preserved unless 'Replace existing' is checked."
    >
      {/* Document selection */}
      <div style={{marginBottom: '14px'}}>
        <label style={{fontSize: '13px', fontWeight: 'bold', display: 'block', marginBottom: '5px'}}>
          Select Extracted Document
        </label>
        <select
          id="section-chunk-doc-select"
          value={selectedDocId}
          onChange={e => {
            setSelectedDocId(e.target.value);
            setChunkResult(null);
            setSections([]);
            setShowSections(false);
          }}
          style={{padding: '6px', width: '100%', maxWidth: '480px'}}
        >
          <option value="">-- Select a document --</option>
          {extractedDocs.map(d => (
            <option key={d.id} value={d.id}>
              {d.original_filename} ({d.id.substring(0, 8)}…)
            </option>
          ))}
        </select>
        {extractedDocs.length === 0 && (
          <p style={{fontSize: '12px', margin: '4px 0 0 0'}}>
            No extracted documents found. Upload and extract a PDF first.
          </p>
        )}
      </div>

      {/* Parameters */}
      <div style={{display: 'flex', gap: '20px', flexWrap: 'wrap', marginBottom: '14px', alignItems: 'flex-end'}}>
        <label style={{fontSize: '13px', display: 'flex', flexDirection: 'column', gap: '4px'}}>
          Chunk size (tokens)
          <input
            id="section-chunk-size"
            type="number"
            min="200"
            max="4000"
            value={chunkSize}
            onChange={e => setChunkSize(e.target.value)}
            style={{width: '100px', padding: '5px'}}
          />
        </label>
        <label style={{fontSize: '13px', display: 'flex', flexDirection: 'column', gap: '4px'}}>
          Overlap (tokens)
          <input
            id="section-overlap-tokens"
            type="number"
            min="0"
            max="500"
            value={overlapTokens}
            onChange={e => setOverlapTokens(e.target.value)}
            style={{width: '80px', padding: '5px'}}
          />
        </label>
        <label style={{fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', paddingBottom: '2px'}}>
          <input
            id="section-replace-existing"
            type="checkbox"
            checked={replaceExisting}
            onChange={e => setReplaceExisting(e.target.checked)}
          />
          Replace existing section chunks
        </label>
      </div>

      {/* Action buttons */}
      <div style={{display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '14px'}}>
        <button
          id="section-chunk-btn"
          onClick={handleSectionChunk}
          disabled={busy || !selectedDocId}
          style={{padding: '8px 16px',
            borderRadius: '4px',
            cursor: busy || !selectedDocId ? 'not-allowed' : 'pointer',
            fontWeight: 'bold'}}
        >
          {busy ? '⟳ Chunking…' : '🔖 Section Chunk'}
        </button>

        <button
          id="section-view-btn"
          onClick={handleViewSections}
          disabled={!selectedDocId || sectionsLoading}
          style={{padding: '8px 16px',
            borderRadius: '4px',
            cursor: !selectedDocId ? 'not-allowed' : 'pointer'}}
        >
          {sectionsLoading ? 'Loading…' : '📋 View Sections'}
        </button>
      </div>

      {/* Chunking result */}
      {chunkResult && (
        <div style={{padding: '12px',
          borderRadius: '4px',
          
          marginBottom: '14px',
          fontSize: '13px'}}>
          {chunkResult.status === 'error' ? (
            <span >Error: {chunkResult.message}</span>
          ) : (
            <>
              <div style={{fontWeight: 'bold', marginBottom: '6px'}}>
                ✓ Section chunking complete
              </div>
              <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '6px'}}>
                <div>Strategy: <strong>{chunkResult.strategy}</strong></div>
                <div>Sections found: <strong>{chunkResult.sections_found}</strong></div>
                <div>Chunks created: <strong>{chunkResult.chunks_created}</strong></div>
              </div>
              {chunkResult.warnings && chunkResult.warnings.length > 0 && (
                <div style={{marginTop: '8px'}}>
                  {chunkResult.warnings.map((w, i) => (
                    <div key={i} style={{fontSize: '12px'}}>⚠ {w}</div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Section list */}
      {showSections && (
        <div style={{marginTop: '10px'}}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px'}}>
            <strong style={{fontSize: '13px'}}>
              Sections ({sections.length})
            </strong>
            <button
              onClick={() => setShowSections(false)}
              style={{fontSize: '11px', padding: '2px 8px', cursor: 'pointer'}}
            >
              Close
            </button>
          </div>

          {sectionsLoading ? (
            <div style={{fontSize: '13px'}}>Loading sections…</div>
          ) : sections.length === 0 ? (
            <div style={{fontSize: '13px'}}>
              No sections detected yet. Run Section Chunk first.
            </div>
          ) : (
            <div style={{maxHeight: '400px',
              overflowY: 'auto',
              borderRadius: '4px',
              padding: '10px'}}>
              {/* Legend */}
              <div style={{display: 'flex', gap: '12px', marginBottom: '10px', flexWrap: 'wrap', fontSize: '11px'}}>
                {Object.entries(LEVEL_LABELS).map(([lvl, label]) => (
                  <span key={lvl} style={{display: 'flex', alignItems: 'center', gap: '4px'}}>
                    <span style={{width: '10px', height: '10px', borderRadius: '2px', display: 'inline-block'}} />
                    {label}
                  </span>
                ))}
              </div>
              {sections.map(sec => (
                <SectionRow key={sec.id} sec={sec} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Info note */}
      <div style={{marginTop: '10px', fontSize: '11px'}}>
        Section chunks carry <strong>heading_path</strong>, <strong>chapter_title</strong>, <strong>section_title</strong>, and <strong>subsection_title</strong> metadata for richer retrieval.
        Basic chunking is unaffected. After section chunking, re-run embedding and indexing.
      </div>
    </Section>
  );
}

import React, { useState } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

const CONTEXT_TYPE_COLOR = {
  parent_section: 'var(--accent-hover)', // Light blue/purple
  chunk: 'var(--status-info)', // Info blue
};

function ContextCard({ ctx, index }) {
  const [expanded, setExpanded] = useState(false);
  const typeColor = CONTEXT_TYPE_COLOR[ctx.type] || 'var(--text-muted)';
  const isParent = ctx.type === 'parent_section';

  return (
    <div style={{borderRadius: 'var(--border-radius-md)',
      padding: '12px',
      marginBottom: '10px'}}>
      {/* Header */}
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '6px'}}>
        <div>
          <span style={{display: 'inline-block',
            padding: '2px 7px',
            borderRadius: 'var(--border-radius-sm)',
            fontSize: '10px',
            fontWeight: 'bold',
            marginRight: '8px'}}>
            {isParent ? 'PARENT SECTION' : 'CHUNK FALLBACK'} [{index + 1}]
          </span>
          <strong style={{fontSize: '13px'}}>
            {ctx.filename || 'unknown'}
          </strong>
          <span style={{fontSize: '11px', marginLeft: '8px'}}>
            pp. {ctx.page_start ?? '?'}–{ctx.page_end ?? '?'}
          </span>
        </div>
        <span style={{fontSize: '11px',
          padding: '2px 6px',
          borderRadius: 'var(--border-radius-sm)',
          fontWeight: 600}}>
          Score: {(ctx.best_score || 0).toFixed(4)}
        </span>
      </div>

      {/* Heading path */}
      {ctx.heading_path && (
        <div style={{marginTop: '6px', fontSize: '11px', fontStyle: 'italic'}}>
          📑 {ctx.heading_path}
        </div>
      )}

      {/* Matched chunks */}
      {isParent && ctx.matched_chunk_ids && ctx.matched_chunk_ids.length > 0 && (
        <div style={{marginTop: '4px', fontSize: '10px'}}>
          Matched chunks: {ctx.matched_chunk_ids.length}
          {' · '}
          IDs: {ctx.matched_chunk_ids.slice(0, 3).map(id => id.substring(0, 8) + '…').join(', ')}
          {ctx.matched_chunk_ids.length > 3 && ` +${ctx.matched_chunk_ids.length - 3} more`}
        </div>
      )}

      {/* Text preview / expand */}
      <div
        style={{marginTop: '8px',
          fontSize: '12px',
          borderRadius: 'var(--border-radius-sm)',
          padding: '10px',
          cursor: 'pointer',
          maxHeight: expanded ? '400px' : '80px',
          overflow: 'auto',
          transition: 'max-height 0.2s ease',
          whiteSpace: 'pre-wrap',
          fontFamily: "'JetBrains Mono', monospace",
          lineHeight: 1.5}}
        onClick={() => setExpanded(e => !e)}
        title="Click to expand/collapse"
      >
        {ctx.text || '(no text)'}
      </div>
      <div style={{fontSize: '10px', marginTop: '4px', textAlign: 'right', cursor: 'pointer'}} onClick={() => setExpanded(e => !e)}>
        {expanded ? '▲ Collapse' : '▼ Expand text'}
      </div>
    </div>
  );
}

export default function ParentRetrievalPanel({ kbs }) {
  const [query, setQuery] = useState('');
  const [kbId, setKbId] = useState('');
  const [searchMode, setSearchMode] = useState('vector');
  const [maxParents, setMaxParents] = useState(4);
  const [limit, setLimit] = useState(8);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleRun = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await apiClient.postJson('/retrieval/parent-context', {
        query: query.trim(),
        limit: Number(limit),
        knowledge_base_id: kbId || null,
        search_mode: searchMode,
        max_parent_sections: Number(maxParents),
      });
      setResult(res);
    } catch (err) {
      setResult({ status: 'error', message: err.message });
    }
    setLoading(false);
  };

  return (
    <Section
      title="Parent-Section Retrieval Tester"
      description="Search chunks, then expand to parent section context. Requires section chunking (Phase 44) to have been run. Falls back to chunk-level context when parent metadata is unavailable."
    >
      {/* Query input */}
      <div style={{display: 'flex', gap: '10px', marginBottom: '16px', flexWrap: 'wrap'}}>
        <input
          id="parent-retrieval-query"
          type="text"
          className="form-input"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="e.g. Explain variables in Python"
          onKeyDown={e => e.key === 'Enter' && handleRun()}
          style={{flex: 1, minWidth: '200px'}}
        />
        <LoadingButton
          loading={loading}
          text="Run Parent Retrieval"
          loadingText="Retrieving…"
          onClick={handleRun}
        />
      </div>

      {/* Options */}
      <div style={{display: 'flex',
        gap: '16px',
        flexWrap: 'wrap',
        padding: '12px',
        borderRadius: 'var(--border-radius-md)',
        marginBottom: '16px',
        alignItems: 'center'}}>
        <label className="form-label" style={{display: 'flex', alignItems: 'center', gap: '8px', margin: 0}}>
          KB:
          <select
            className="form-input"
            value={kbId}
            onChange={e => setKbId(e.target.value)}
            style={{padding: '4px 8px', width: 'auto'}}
          >
            <option value="">Any KB</option>
            {(kbs || []).map(k => (
              <option key={k.id} value={k.id}>{k.name}</option>
            ))}
          </select>
        </label>

        <label className="form-label" style={{display: 'flex', alignItems: 'center', gap: '8px', margin: 0}}>
          Search mode:
          <select
            id="parent-retrieval-search-mode"
            className="form-input"
            value={searchMode}
            onChange={e => setSearchMode(e.target.value)}
            style={{padding: '4px 8px', width: 'auto'}}
          >
            <option value="vector">Vector</option>
            <option value="keyword">Keyword</option>
            <option value="hybrid">Hybrid</option>
          </select>
        </label>

        <label className="form-label" style={{display: 'flex', alignItems: 'center', gap: '8px', margin: 0}}>
          Chunk limit:
          <input
            id="parent-retrieval-limit"
            type="number"
            className="form-input"
            min="1"
            max="20"
            value={limit}
            onChange={e => setLimit(e.target.value)}
            style={{width: '60px', padding: '4px 8px'}}
          />
        </label>

        <label className="form-label" style={{display: 'flex', alignItems: 'center', gap: '8px', margin: 0}}>
          Max parent sections:
          <input
            id="parent-retrieval-max-parents"
            type="number"
            className="form-input"
            min="1"
            max="10"
            value={maxParents}
            onChange={e => setMaxParents(e.target.value)}
            style={{width: '60px', padding: '4px 8px'}}
          />
        </label>
      </div>

      {/* Error */}
      {result && result.status === 'error' && (
        <div style={{padding: '10px 14px',  fontSize: '13px', marginBottom: '16px'}}>
          {result.message}
        </div>
      )}

      {/* Results */}
      {result && result.status === 'ok' && (
        <>
          {/* Summary bar */}
          <div style={{display: 'flex',
            gap: '16px',
            padding: '10px 14px',
            
            
            fontSize: '13px',
            flexWrap: 'wrap'}}>
            <span>Contexts: <strong >{result.contexts?.length ?? 0}</strong></span>
            <span>Fallback chunks used: <strong >{result.fallback_chunks_used ?? 0}</strong></span>
            <span>
              Parent sections: <strong >
                {(result.contexts || []).filter(c => c.type === 'parent_section').length}
              </strong>
            </span>
            <span style={{fontStyle: 'italic'}}>
              Query: "{result.query}"
            </span>
          </div>

          {/* Context cards */}
          {result.contexts.length === 0 ? (
            <div style={{fontSize: '13px', textAlign: 'center', padding: '20px'}}>
              No contexts found. Make sure documents are indexed and section chunking has been run.
            </div>
          ) : (
            result.contexts.map((ctx, i) => (
              <ContextCard key={i} ctx={ctx} index={i} />
            ))
          )}
        </>
      )}

      {/* Info */}
      <div style={{marginTop: '16px', fontSize: '12px'}}>
        Parent-section retrieval groups matched chunks by their <code >parent_section_id</code> (Phase 44 section chunking) and returns the full parent section text.
        Documents chunked with basic chunking will use chunk-level fallback context.
      </div>
    </Section>
  );
}

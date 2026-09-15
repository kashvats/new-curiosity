import React, { useState, useEffect, useCallback } from 'react';
import Section from '../../components/Section';
import { apiClient } from '../../api/client';

const OCR_STATUS_COLORS = {
  not_started: '#aaa',
  not_needed: '#28a745',
  needed: '#fd7e14',
  running: '#007bff',
  completed: '#28a745',
  failed: '#dc3545',
  disabled: '#6c757d',
};

function OcrStatusBadge({ status }) {
  const color = OCR_STATUS_COLORS[status] || '#aaa';
  return (
    <span style={{display: 'inline-block',
      padding: '2px 8px',
      borderRadius: '3px',
      fontSize: '11px',
      fontWeight: 'bold'}}>
      {status || 'unknown'}
    </span>
  );
}

function QualityBar({ score }) {
  if (score == null) return <span >—</span>;
  const pct = Math.round(score * 100);
  const color = pct >= 70 ? '#28a745' : pct >= 40 ? '#ffc107' : '#dc3545';
  return (
    <span style={{display: 'inline-flex', alignItems: 'center', gap: '6px'}}>
      <span style={{display: 'inline-block',
        width: '80px',
        height: '8px',
        borderRadius: '4px',
        position: 'relative',
        overflow: 'hidden'}}>
        <span style={{display: 'block',
          width: `${pct}%`,
          height: '100%',
          borderRadius: '4px'}} />
      </span>
      <span style={{fontSize: '11px', color}}>{pct}%</span>
    </span>
  );
}

export default function OcrPanel({ documents, fetchDocuments }) {
  const [ocrHealth, setOcrHealth] = useState(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [selectedDocId, setSelectedDocId] = useState('');
  const [analyzeResult, setAnalyzeResult] = useState(null);
  const [ocrRunResult, setOcrRunResult] = useState(null);
  const [mergeResult, setMergeResult] = useState(null);
  const [maxPages, setMaxPages] = useState('');
  const [forceOcr, setForceOcr] = useState(false);
  const [busy, setBusy] = useState('');

  const extractedDocs = (documents || []).filter(
    d => d.extraction_status === 'extracted' && d.status !== 'duplicate'
  );

  const selectedDoc = extractedDocs.find(d => d.id === selectedDocId);

  const fetchHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const data = await apiClient.getJson('/ocr/health');
      setOcrHealth(data);
    } catch (err) {
      setOcrHealth({ status: 'error', message: err.message });
    }
    setHealthLoading(false);
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  const handleAnalyze = async () => {
    if (!selectedDocId) return;
    setBusy('analyze');
    setAnalyzeResult(null);
    setOcrRunResult(null);
    setMergeResult(null);
    try {
      const res = await apiClient.postJson(`/documents/${selectedDocId}/ocr/analyze`, {});
      setAnalyzeResult(res);
      if (fetchDocuments) fetchDocuments();
    } catch (err) {
      setAnalyzeResult({ status: 'error', message: err.message });
    }
    setBusy('');
  };

  const handleRunOcr = async () => {
    if (!selectedDocId) return;
    if (!window.confirm('Run OCR on this document? This may take several minutes for large PDFs.')) return;
    setBusy('run');
    setOcrRunResult(null);
    try {
      const res = await apiClient.postJson(`/documents/${selectedDocId}/ocr/run`, {
        force: forceOcr,
        max_pages: maxPages ? parseInt(maxPages, 10) : null,
      });
      setOcrRunResult(res);
      if (fetchDocuments) fetchDocuments();
    } catch (err) {
      setOcrRunResult({ status: 'error', message: err.message });
    }
    setBusy('');
  };

  const handleMerge = async () => {
    if (!selectedDocId) return;
    if (!window.confirm('Merge OCR text into extracted JSON? This will reset chunking, embedding, and indexing statuses.')) return;
    setBusy('merge');
    setMergeResult(null);
    try {
      const res = await apiClient.postJson(`/documents/${selectedDocId}/ocr/merge`, {});
      setMergeResult(res);
      if (fetchDocuments) fetchDocuments();
    } catch (err) {
      setMergeResult({ status: 'error', message: err.message });
    }
    setBusy('');
  };

  const resultBox = (result, label) => {
    if (!result) return null;
    const isError = result.status === 'error' || result.status === 'failed';
    return (
      <div style={{marginTop: '10px',
        padding: '10px',
        borderRadius: '4px',
        
        fontSize: '13px'}}>
        <strong>{label}: </strong>
        {isError
          ? <span >{result.message || 'Error'}</span>
          : <span >{result.message || result.status}</span>}
        {result.pages_replaced != null && (
          <div>Pages replaced: <strong>{result.pages_replaced}</strong></div>
        )}
        {result.ocr_page_count != null && (
          <div>OCR pages processed: <strong>{result.ocr_page_count}</strong></div>
        )}
      </div>
    );
  };

  return (
    <Section
      title="OCR — Scanned PDF Detection & Recovery"
      description="Analyze PDF extraction quality, detect scanned documents, and optionally run OCR to recover text. OCR requires OCR_ENABLED=true and Tesseract installed in the container."
    >
      {/* OCR Health */}
      <div style={{padding: '10px 14px',
        borderRadius: '4px',
        marginBottom: '16px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        flexWrap: 'wrap',
        fontSize: '13px'}}>
        <strong>OCR Health:</strong>
        {healthLoading ? (
          <span >Checking…</span>
        ) : ocrHealth ? (
          <>
            <span style={{fontWeight: 'bold'}}>
              {ocrHealth.status === 'ok' ? '✓ Available' : '⚠ Unavailable'}
            </span>
            <span>Enabled: <strong>{ocrHealth.enabled ? 'Yes' : 'No'}</strong></span>
            {ocrHealth.dependencies && Object.entries(ocrHealth.dependencies).map(([lib, ok]) => (
              <span key={lib} >
                {lib}: {ok ? '✓' : '✗'}
              </span>
            ))}
            {ocrHealth.message && (
              <span >{ocrHealth.message}</span>
            )}
          </>
        ) : (
          <span >—</span>
        )}
        <button
          onClick={fetchHealth}
          disabled={healthLoading}
          style={{marginLeft: 'auto', padding: '3px 8px', fontSize: '12px', cursor: 'pointer'}}
        >
          ↻ Refresh
        </button>
      </div>

      {/* Document selector */}
      <div style={{marginBottom: '16px'}}>
        <label style={{fontSize: '13px', fontWeight: 'bold', display: 'block', marginBottom: '6px'}}>
          Select Extracted Document
        </label>
        <select
          id="ocr-doc-select"
          value={selectedDocId}
          onChange={e => {
            setSelectedDocId(e.target.value);
            setAnalyzeResult(null);
            setOcrRunResult(null);
            setMergeResult(null);
          }}
          style={{padding: '6px', width: '100%', maxWidth: '500px'}}
        >
          <option value="">-- Select a document --</option>
          {extractedDocs.map(d => (
            <option key={d.id} value={d.id}>
              {d.original_filename} (ID: {d.id.substring(0, 8)}…)
            </option>
          ))}
        </select>
        {extractedDocs.length === 0 && (
          <p style={{fontSize: '12px', margin: '6px 0 0 0'}}>
            No extracted documents found. Upload and extract a PDF first.
          </p>
        )}
      </div>

      {selectedDoc && (
        <>
          {/* Document OCR Status */}
          <div style={{padding: '12px',
            borderRadius: '4px',
            marginBottom: '16px',
            fontSize: '13px',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: '8px'}}>
            <div>
              <strong>Extraction Quality:</strong>
              <div style={{marginTop: '4px'}}>
                <QualityBar score={selectedDoc.extraction_quality_score} />
              </div>
            </div>
            <div>
              <strong>Likely Scanned:</strong>
              <div style={{marginTop: '4px'}}>
                {selectedDoc.is_likely_scanned == null ? (
                  <span >Not analyzed</span>
                ) : selectedDoc.is_likely_scanned ? (
                  <span style={{fontWeight: 'bold'}}>⚠ Yes — OCR may be needed</span>
                ) : (
                  <span >✓ No — text extraction is good</span>
                )}
              </div>
            </div>
            <div>
              <strong>OCR Status:</strong>
              <div style={{marginTop: '4px'}}>
                <OcrStatusBadge status={selectedDoc.ocr_status || 'not_started'} />
              </div>
            </div>
            <div>
              <strong>OCR Pages:</strong>
              <div style={{marginTop: '4px'}}>
                {selectedDoc.ocr_page_count ?? '—'}
              </div>
            </div>
          </div>

          {/* Analysis result */}
          {analyzeResult && analyzeResult.status === 'analyzed' && (
            <div style={{padding: '12px',
              borderRadius: '4px',
              marginBottom: '16px',
              fontSize: '13px'}}>
              <strong>Analysis Result</strong>
              <div style={{marginTop: '6px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '6px'}}>
                <div>Pages: <strong>{analyzeResult.page_count}</strong></div>
                <div>Empty pages: <strong>{analyzeResult.empty_pages}</strong></div>
                <div>Low-text pages: <strong>{analyzeResult.pages_with_low_text}</strong></div>
                <div>Avg chars/page: <strong>{analyzeResult.average_chars_per_page}</strong></div>
                <div>Scanned ratio: <strong>{(analyzeResult.scanned_page_ratio * 100).toFixed(1)}%</strong></div>
                <div>Quality score: <QualityBar score={analyzeResult.extraction_quality_score} /></div>
              </div>
              <div style={{marginTop: '8px', fontStyle: 'italic'}}>
                {analyzeResult.recommendation}
              </div>
            </div>
          )}
          {analyzeResult && analyzeResult.status === 'error' && (
            <div style={{padding: '10px', borderRadius: '4px', fontSize: '13px', marginBottom: '12px'}}>
              {analyzeResult.message}
            </div>
          )}

          {/* Action buttons */}
          <div style={{display: 'flex', gap: '12px', flexWrap: 'wrap', marginBottom: '16px', alignItems: 'flex-end'}}>
            <button
              id="ocr-analyze-btn"
              onClick={handleAnalyze}
              disabled={!!busy}
              style={{padding: '7px 14px', cursor: busy ? 'not-allowed' : 'pointer', borderRadius: '4px'}}
            >
              {busy === 'analyze' ? 'Analyzing…' : '🔍 Analyze OCR Need'}
            </button>

            <div style={{display: 'flex', flexDirection: 'column', gap: '4px'}}>
              <div style={{display: 'flex', gap: '8px', alignItems: 'center'}}>
                <button
                  id="ocr-run-btn"
                  onClick={handleRunOcr}
                  disabled={!!busy}
                  style={{padding: '7px 14px', cursor: busy ? 'not-allowed' : 'pointer', borderRadius: '4px'}}
                >
                  {busy === 'run' ? 'Running OCR…' : '🤖 Run OCR'}
                </button>
                <label style={{fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer'}}>
                  <input
                    type="checkbox"
                    checked={forceOcr}
                    onChange={e => setForceOcr(e.target.checked)}
                  />
                  Force (skip scanned check)
                </label>
                <label style={{fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px'}}>
                  Max pages (test):
                  <input
                    type="number"
                    min="1"
                    value={maxPages}
                    onChange={e => setMaxPages(e.target.value)}
                    placeholder="all"
                    style={{width: '60px', padding: '3px', fontSize: '12px'}}
                  />
                </label>
              </div>
              <span style={{fontSize: '11px'}}>
                Requires OCR_ENABLED=true and Tesseract installed.
              </span>
            </div>

            <button
              id="ocr-merge-btn"
              onClick={handleMerge}
              disabled={!!busy}
              style={{padding: '7px 14px', cursor: busy ? 'not-allowed' : 'pointer', borderRadius: '4px'}}
            >
              {busy === 'merge' ? 'Merging…' : '🔗 Merge OCR Text'}
            </button>
          </div>

          {resultBox(ocrRunResult, 'OCR Run')}
          {resultBox(mergeResult, 'OCR Merge')}
        </>
      )}
    </Section>
  );
}

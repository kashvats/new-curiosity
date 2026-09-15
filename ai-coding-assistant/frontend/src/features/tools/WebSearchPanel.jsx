import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import TemplateSelector from '../../components/TemplateSelector';
import { apiClient } from '../../api/client';

export default function WebSearchPanel({ kbs, fetchDocuments }) {
  const [webSearchQuery, setWebSearchQuery] = useState('');
  const [webSearchMax, setWebSearchMax] = useState(8);
  const [webSearchSummarize, setWebSearchSummarize] = useState(true);
  const [webSearchData, setWebSearchData] = useState(null);
  const [isSearching, setIsSearching] = useState(false);

  const [saveKbId, setSaveKbId] = useState('');
  const [createJob, setCreateJob] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveResult, setSaveResult] = useState(null);

  const [templateData, setTemplateData] = useState({ id: null, vars: null, error: false });

  const handleWebSearch = async (e) => {
    e.preventDefault();
    if (!webSearchQuery.trim()) return;
    if (templateData.error) return alert("Please fix template errors first.");
    setIsSearching(true);
    setWebSearchData(null);
    setSaveResult(null);
    try {
      const payload = {
        query: webSearchQuery,
        max_results: parseInt(webSearchMax) || 8,
        summarize: webSearchSummarize
      };

      if (templateData.id) {
        payload.template_id = templateData.id;
        payload.template_variables = templateData.vars;
      }

      const data = await apiClient.postJson('/tools/web-search', payload);
      setWebSearchData(data);
    } catch (err) {
      alert(`Search failed: ${err.message}`);
    }
    setIsSearching(false);
  };

  const handleSaveSummary = async () => {
    if (!webSearchData || !webSearchData.summary) return;
    setIsSaving(true);
    setSaveResult(null);
    try {
      const payload = {
        query: webSearchQuery,
        title: `Web Search: ${webSearchQuery}`,
        summary: webSearchData.summary,
        urls: (webSearchData.results || []).map(r => r.url).slice(0, 20),
        knowledge_base_id: saveKbId || null,
        create_job: createJob
      };
      const res = await apiClient.postJson('/memory/web-summary', payload);
      setSaveResult(res);
      if (fetchDocuments) fetchDocuments();
    } catch (err) {
      alert(`Save failed: ${err.message}`);
    }
    setIsSaving(false);
  };

  return (
    <Section title="Web Search" description="Search SearXNG and summarize findings locally." >
      <form onSubmit={handleWebSearch} style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>
        <div>
          <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold'}}>Search Query:</label>
          <input
            type="text"
            value={webSearchQuery}
            onChange={e => setWebSearchQuery(e.target.value)}
            placeholder="Search the web for up-to-date documentation or fixes..."
            style={{width: '100%', padding: '10px', borderRadius: '4px', boxSizing: 'border-box'}}
          />
        </div>

        <div style={{display: 'flex', gap: '20px', alignItems: 'center'}}>
          <div>
            <label style={{marginRight: '10px', fontWeight: 'bold'}}>Max Results:</label>
            <input
              type="number"
              value={webSearchMax}
              onChange={e => setWebSearchMax(e.target.value)}
              min="1" max="20"
              style={{padding: '5px', borderRadius: '4px', width: '60px'}}
            />
          </div>
          <label style={{display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer'}}>
            <input
              type="checkbox"
              checked={webSearchSummarize}
              onChange={e => setWebSearchSummarize(e.target.checked)}
            />
            <strong>Summarize Results using LLM</strong>
          </label>
        </div>

        <TemplateSelector category="web_search" onTemplateChange={(id, vars, error) => setTemplateData({ id, vars, error })} />

        <div>
          <LoadingButton type="submit" loading={isSearching} loadingText="Searching..." text="Search Web" />
        </div>
      </form>

      {webSearchData && (
        <div style={{marginTop: '20px'}}>
          {webSearchData.status === 'error' ? (
            <div style={{padding: '10px', borderRadius: '4px'}}>
              <strong>Error:</strong> {webSearchData.message}
            </div>
          ) : (
            <div style={{padding: '20px', borderRadius: '8px'}}>
              {webSearchData.summary && (
                <div style={{marginBottom: '20px', padding: '15px', borderRadius: '6px'}}>
                  <h4 style={{margin: '0 0 10px 0'}}>AI Summary</h4>
                  <div style={{whiteSpace: 'pre-wrap', fontSize: '14px', lineHeight: '1.5', marginBottom: '15px'}}>
                    {webSearchData.summary}
                  </div>
                  <div style={{padding: '10px', borderRadius: '4px', display: 'flex', gap: '15px', alignItems: 'center', flexWrap: 'wrap'}}>
                    <select value={saveKbId} onChange={e => setSaveKbId(e.target.value)} style={{padding: '6px', borderRadius: '4px'}}>
                      <option value="">Any KB</option>
                      {(kbs || []).map(k => <option key={k.id} value={k.id}>{k.name}</option>)}
                    </select>
                    <label style={{display: 'flex', alignItems: 'center', gap: '5px'}}>
                      <input type="checkbox" checked={createJob} onChange={e => setCreateJob(e.target.checked)} />
                      Create Ingestion Job
                    </label>
                    <LoadingButton loading={isSaving} onClick={handleSaveSummary} text="Save Summary to Knowledge Base"  />
                  </div>
                  {saveResult && (
                    <div style={{marginTop: '10px', fontSize: '13px', padding: '10px', borderRadius: '4px'}}>
                      Successfully saved! Document ID: {saveResult.document_id} {saveResult.job_id && `| Job ID: ${saveResult.job_id}`}
                    </div>
                  )}
                </div>
              )}

              <h4 style={{margin: '0 0 10px 0'}}>Search Results ({webSearchData.results?.length || 0})</h4>
              <div style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>
                {webSearchData.results?.map((res, idx) => (
                  <div key={idx} style={{padding: '15px', borderRadius: '6px'}}>
                    <div style={{fontWeight: 'bold', fontSize: '16px', marginBottom: '5px'}}>
                      <a href={res.url} target="_blank" rel="noopener noreferrer" style={{textDecoration: 'none'}}>
                        {res.title}
                      </a>
                    </div>
                    <div style={{fontSize: '12px', marginBottom: '8px'}}>
                      {res.url}
                    </div>
                    <div style={{fontSize: '14px'}}>
                      {res.snippet}
                    </div>
                    <div style={{fontSize: '11px', marginTop: '8px'}}>
                      Source: {res.source}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}


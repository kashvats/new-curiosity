import React, { useState } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function KnowledgeSearch({ kbs }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchDocId, setSearchDocId] = useState('');
  const [searchKbId, setSearchKbId] = useState('');
  const [searchMode, setSearchMode] = useState('vector');
  const [rerank, setRerank] = useState(false);
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setIsSearching(true);
    setSearchResults([]);
    try {
      let url = `/search?q=${encodeURIComponent(searchQuery)}&search_mode=${encodeURIComponent(searchMode)}`;
      if (searchDocId) url += `&document_id=${encodeURIComponent(searchDocId)}`;
      if (searchKbId) url += `&knowledge_base_id=${encodeURIComponent(searchKbId)}`;
      if (rerank) url += `&rerank=true`;
      
      const data = await apiClient.getJson(url);
      setSearchResults(data.results || []);
    } catch (err) {
      alert(`Search failed: ${err.message}`);
    }
    setIsSearching(false);
  };

  return (
    <Section title="Knowledge Base Search" description="Semantic search over indexed chunks in Qdrant.">
      <form onSubmit={handleSearch} style={{display: 'flex', gap: '10px', marginBottom: '20px', flexWrap: 'wrap'}}>
        <input 
          type="text" 
          className="form-input"
          value={searchQuery} 
          onChange={e => setSearchQuery(e.target.value)} 
          placeholder="Ask something..." 
          style={{flex: 1, minWidth: '200px'}}
        />
        <input 
          type="text" 
          className="form-input"
          value={searchDocId} 
          onChange={e => setSearchDocId(e.target.value)} 
          placeholder="Document ID (Optional)" 
          style={{width: '180px'}}
        />
        <select 
          className="form-input"
          value={searchKbId} 
          onChange={e => setSearchKbId(e.target.value)} 
          style={{width: '180px'}}
        >
          <option value="">Any KB</option>
          {(kbs || []).map(k => <option key={k.id} value={k.id}>{k.name}</option>)}
        </select>
        <select 
          className="form-input"
          value={searchMode} 
          onChange={e => setSearchMode(e.target.value)} 
          style={{width: '120px'}}
        >
          <option value="vector">Vector</option>
          <option value="keyword">Keyword</option>
          <option value="hybrid">Hybrid</option>
        </select>
        <label style={{display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', fontWeight: 'bold', cursor: 'pointer'}}>
          <input type="checkbox" checked={rerank} onChange={e => setRerank(e.target.checked)} />
          Rerank
        </label>
        <LoadingButton type="submit" loading={isSearching} loadingText="Searching..." text="Search" />
      </form>

      {searchResults.length > 0 && (
        <div style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>
          <h4 style={{margin: '0 0 10px 0'}}>Results ({searchResults.length}):</h4>
          {searchResults.map((res, idx) => (
            <div key={idx} style={{padding: '15px', borderRadius: '6px'}}>
              <div style={{fontSize: '12px', marginBottom: '8px', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px'}}>
                <span><strong >File:</strong> {res.filename} (Page {res.page_start})</span>
                <span style={{display: 'flex', gap: '10px'}}>
                  {res.rerank_score !== undefined && <span style={{fontWeight: 'bold'}}>Rerank: {res.rerank_score.toFixed(4)}</span>}
                  {res.vector_score !== undefined && <span >Vec: {res.vector_score.toFixed(4)}</span>}
                  {res.keyword_score !== undefined && <span >Key: {res.keyword_score.toFixed(4)}</span>}
                  <strong >Score:</strong> {res.score.toFixed(4)}
                </span>
              </div>
              <div style={{fontSize: '14px', lineHeight: '1.5'}}>{res.text_preview || res.text}</div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

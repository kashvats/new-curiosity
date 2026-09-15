import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function RagEvalPanel() {
  const [sets, setSets] = useState([]);
  const [selectedSetId, setSelectedSetId] = useState('');
  
  const [newSetName, setNewSetName] = useState('');
  const [newSetDesc, setNewSetDesc] = useState('');
  
  const [questions, setQuestions] = useState([]);
  const [newQuestion, setNewQuestion] = useState('');
  const [newKeywords, setNewKeywords] = useState('');
  const [newPatterns, setNewPatterns] = useState('');
  
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  
  const [searchMode, setSearchMode] = useState('vector');
  const [retrievalStrategy, setRetrievalStrategy] = useState('chunk');
  const [rerank, setRerank] = useState(false);
  
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    fetchSets();
  }, []);

  useEffect(() => {
    if (selectedSetId) {
      fetchQuestions(selectedSetId);
      fetchRuns(selectedSetId);
      setSelectedRun(null);
    } else {
      setQuestions([]);
      setRuns([]);
    }
  }, [selectedSetId]);

  const fetchSets = async () => {
    try {
      const data = await apiClient.getJson('/rag-eval/sets');
      setSets(data.sets || []);
    } catch (err) {
      console.error(err);
    }
  };

  const fetchQuestions = async (setId) => {
    try {
      const data = await apiClient.getJson(`/rag-eval/sets/${setId}/questions`);
      setQuestions(data.questions || []);
    } catch (err) {
      console.error(err);
    }
  };

  const fetchRuns = async (setId) => {
    try {
      const data = await apiClient.getJson(`/rag-eval/runs?eval_set_id=${setId}`);
      setRuns(data.runs || []);
    } catch (err) {
      console.error(err);
    }
  };

  const handleCreateSet = async (e) => {
    e.preventDefault();
    try {
      const res = await apiClient.postJson('/rag-eval/sets', { name: newSetName, description: newSetDesc });
      setNewSetName('');
      setNewSetDesc('');
      await fetchSets();
      setSelectedSetId(res.id);
    } catch (err) {
      alert("Failed to create set: " + err.message);
    }
  };

  const handleAddQuestion = async (e) => {
    e.preventDefault();
    try {
      const keywords = newKeywords ? JSON.stringify(newKeywords.split(',').map(s => s.trim()).filter(Boolean)) : null;
      const patterns = newPatterns ? JSON.stringify(newPatterns.split(',').map(s => s.trim()).filter(Boolean)) : null;
      
      await apiClient.postJson(`/rag-eval/sets/${selectedSetId}/questions`, {
        question: newQuestion,
        expected_keywords_json: keywords,
        expected_source_patterns_json: patterns
      });
      setNewQuestion('');
      setNewKeywords('');
      setNewPatterns('');
      fetchQuestions(selectedSetId);
    } catch (err) {
      alert("Failed to add question: " + err.message);
    }
  };

  const handleDeleteQuestion = async (qId) => {
    try {
      await apiClient.delete(`/rag-eval/questions/${qId}`);
      fetchQuestions(selectedSetId);
    } catch (err) {
      console.error(err);
    }
  };

  const handleRunEval = async () => {
    if (!selectedSetId) return;
    setIsRunning(true);
    try {
      const res = await apiClient.postJson(`/rag-eval/sets/${selectedSetId}/run`, {
        search_mode: searchMode,
        retrieval_strategy: retrievalStrategy,
        rerank: rerank,
        limit: 5,
        score_threshold: 0.55
      });
      await fetchRuns(selectedSetId);
      loadRunDetails(res.run_id);
    } catch (err) {
      alert("Failed to run eval: " + err.message);
    }
    setIsRunning(false);
  };

  const loadRunDetails = async (runId) => {
    try {
      const data = await apiClient.getJson(`/rag-eval/runs/${runId}`);
      setSelectedRun(data);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <Section title="RAG Evaluation (Phase 48)" description="Test RAG retrieval against expected answers and sources.">
      
      <div style={{display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '20px'}}>
        
        {/* Left Column: Setup */}
        <div>
          <div style={{marginBottom: '20px', padding: '15px', borderRadius: '4px'}}>
            <h4>Eval Sets</h4>
            <select value={selectedSetId} onChange={e => setSelectedSetId(e.target.value)} style={{width: '100%', padding: '8px', marginBottom: '10px'}}>
              <option value="">-- Select a Set --</option>
              {sets.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            
            <hr />
            
            <form onSubmit={handleCreateSet}>
              <input placeholder="New Set Name" value={newSetName} onChange={e=>setNewSetName(e.target.value)} required style={{width: '100%', padding: '5px', marginBottom: '5px'}} />
              <input placeholder="Description" value={newSetDesc} onChange={e=>setNewSetDesc(e.target.value)} style={{width: '100%', padding: '5px', marginBottom: '5px'}} />
              <button type="submit" style={{width: '100%'}}>Create Set</button>
            </form>
          </div>

          {selectedSetId && (
            <div style={{padding: '15px', borderRadius: '4px'}}>
              <h4>Run Eval</h4>
              
              <div style={{marginBottom: '10px'}}>
                <label style={{display: 'block', fontSize: '12px'}}>Search Mode:</label>
                <select value={searchMode} onChange={e => setSearchMode(e.target.value)} style={{width: '100%', padding: '5px'}}>
                  <option value="vector">Vector</option>
                  <option value="keyword">Keyword</option>
                  <option value="hybrid">Hybrid</option>
                </select>
              </div>

              <div style={{marginBottom: '10px'}}>
                <label style={{display: 'block', fontSize: '12px'}}>Strategy:</label>
                <select value={retrievalStrategy} onChange={e => setRetrievalStrategy(e.target.value)} style={{width: '100%', padding: '5px'}}>
                  <option value="chunk">Basic Chunk</option>
                  <option value="parent">Parent Section</option>
                </select>
              </div>

              <div style={{marginBottom: '15px'}}>
                <label style={{display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px'}}>
                  <input type="checkbox" checked={rerank} onChange={e => setRerank(e.target.checked)} />
                  Enable Reranking
                </label>
              </div>

              <LoadingButton onClick={handleRunEval} loading={isRunning} loadingText="Running..." text="Run Eval Set" style={{width: '100%'}} />
            </div>
          )}
        </div>

        {/* Right Column: Questions & Results */}
        <div>
          {selectedSetId ? (
            <div>
              <div style={{marginBottom: '20px', padding: '15px', borderRadius: '4px'}}>
                <h4>Questions ({questions.length})</h4>
                <div style={{maxHeight: '200px', overflowY: 'auto', marginBottom: '10px'}}>
                  {questions.map(q => (
                    <div key={q.id} style={{fontSize: '13px', padding: '8px', position: 'relative'}}>
                      <button onClick={() => handleDeleteQuestion(q.id)} style={{position: 'absolute', right: '5px', top: '5px', cursor: 'pointer'}}>X</button>
                      <strong>Q:</strong> {q.question}<br/>
                      <span style={{fontSize: '11px'}}>
                        Keywords: {q.expected_keywords_json || 'None'} | Patterns: {q.expected_source_patterns_json || 'None'}
                      </span>
                    </div>
                  ))}
                </div>
                <form onSubmit={handleAddQuestion}>
                  <input placeholder="Question" value={newQuestion} onChange={e=>setNewQuestion(e.target.value)} required style={{width: '100%', padding: '5px', marginBottom: '5px'}} />
                  <input placeholder="Expected Keywords (comma separated)" value={newKeywords} onChange={e=>setNewKeywords(e.target.value)} style={{width: '100%', padding: '5px', marginBottom: '5px'}} />
                  <input placeholder="Expected Source Patterns (regex or text, comma separated)" value={newPatterns} onChange={e=>setNewPatterns(e.target.value)} style={{width: '100%', padding: '5px', marginBottom: '5px'}} />
                  <button type="submit">Add Question</button>
                </form>
              </div>

              <div style={{padding: '15px', borderRadius: '4px'}}>
                <h4>Evaluation Runs</h4>
                <div style={{display: 'flex', gap: '10px', overflowX: 'auto', marginBottom: '15px'}}>
                  {runs.map(r => (
                    <div key={r.id} onClick={() => loadRunDetails(r.id)} style={{padding: '10px', borderRadius: '4px', cursor: 'pointer', minWidth: '150px'}}>
                      <div style={{fontSize: '12px', fontWeight: 'bold'}}>{new Date(r.created_at).toLocaleString()}</div>
                      <div style={{fontSize: '12px'}}>Pass: <span >{r.passed}</span> | Warn: <span >{r.warnings}</span> | Fail: <span >{r.failed}</span></div>
                    </div>
                  ))}
                </div>

                {selectedRun && (
                  <div style={{paddingTop: '15px'}}>
                    <h5>Run Details</h5>
                    {selectedRun.results.map(res => (
                      <div key={res.id} style={{marginBottom: '15px', padding: '10px', borderRadius: '4px'}}>
                        <div style={{fontWeight: 'bold', fontSize: '14px'}}>Q: {res.question}</div>
                        <div style={{fontSize: '12px', margin: '5px 0'}}>
                          <strong>Score:</strong> {res.score.toFixed(2)} ({res.status})
                        </div>
                        <div style={{fontSize: '12px', fontStyle: 'italic', marginBottom: '5px'}}>
                          A: {res.answer}
                        </div>
                        {res.issues_json && JSON.parse(res.issues_json).length > 0 && (
                          <div style={{fontSize: '12px'}}>
                            <strong>Issues:</strong> {JSON.parse(res.issues_json).join('; ')}
                          </div>
                        )}
                        <div style={{fontSize: '11px', marginTop: '5px'}}>
                          <strong>Sources Used:</strong> {res.sources_json ? JSON.parse(res.sources_json).length : 0}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div style={{fontStyle: 'italic'}}>Select or create an Evaluation Set to continue.</div>
          )}
        </div>
      </div>
    </Section>
  );
}

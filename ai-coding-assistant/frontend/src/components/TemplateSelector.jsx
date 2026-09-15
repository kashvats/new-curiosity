import React, { useState, useEffect } from 'react';
import { apiClient } from '../api/client';

export default function TemplateSelector({ category, onTemplateChange }) {
  const [prompts, setPrompts]           = useState([]);
  const [selectedId, setSelectedId]     = useState('');
  const [variablesJson, setVariablesJson] = useState('{\n  \n}');
  const [error, setError]               = useState(null);

  useEffect(() => {
    const fetchPrompts = async () => {
      try {
        const data = await apiClient.getJson(`/prompts?category=${category}&limit=50`);
        setPrompts(data.prompts || []);
      } catch (err) {
        console.error('Failed to fetch templates', err);
      }
    };
    fetchPrompts();
  }, [category]);

  useEffect(() => {
    if (!selectedId) {
      setError(null);
      onTemplateChange(null, null);
      return;
    }
    try {
      const vars = JSON.parse(variablesJson);
      setError(null);
      onTemplateChange(selectedId, vars);
    } catch (e) {
      setError('Invalid JSON format for variables');
      onTemplateChange(selectedId, null, true);
    }
  }, [selectedId, variablesJson]);

  const handleSelect = (e) => {
    const id = e.target.value;
    setSelectedId(id);
    if (id) {
      const p = prompts.find(x => x.id === id);
      if (p && p.variables && p.variables.length > 0) {
        setVariablesJson('{\n  ' + p.variables.map(v => `"${v}": ""`).join(',\n  ') + '\n}');
      } else {
        setVariablesJson('{\n  \n}');
      }
    }
  };

  // ── shared input styles ──────────────────────────────────────────────────
  const inputStyle = {
    width: '100%',
    padding: '7px 10px',
    boxSizing: 'border-box',
    background: '#0d1117',
    border: '1px solid #30363d',
    borderRadius: '6px',
    color: '#e6edf3',
    fontSize: '13px',
    outline: 'none',
  };

  return (
    <div style={{
      marginTop: '14px',
      padding: '14px',
      border: '1px solid #21262d',
      borderRadius: '8px',
      backgroundColor: '#0d1117',
    }}>
      <div style={{ fontSize: '12px', fontWeight: 700, color: '#7d8590', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        Template — {category}
      </div>

      <select
        value={selectedId}
        onChange={handleSelect}
        style={{ ...inputStyle, marginBottom: '10px', cursor: 'pointer' }}
      >
        <option value="">— No Template —</option>
        {prompts.map(p => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>

      {selectedId && (
        <>
          <div style={{ fontSize: '11px', color: '#7d8590', marginBottom: '4px' }}>Variables (JSON)</div>
          <textarea
            value={variablesJson}
            onChange={e => setVariablesJson(e.target.value)}
            rows={4}
            style={{
              ...inputStyle,
              fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
              fontSize: '12px',
              border: error ? '1px solid #f85149' : '1px solid #30363d',
              resize: 'vertical',
            }}
          />
          {error && <div style={{ color: '#f85149', fontSize: '11px', marginTop: '4px' }}>{error}</div>}
        </>
      )}
    </div>
  );
}

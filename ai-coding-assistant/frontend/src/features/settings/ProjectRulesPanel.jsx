import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function ProjectRulesPanel() {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filterCategory, setFilterCategory] = useState('');

  const [isEditing, setIsEditing] = useState(false);
  const [currentRule, setCurrentRule] = useState({ title: '', content: '', category: 'general', priority: 100, enabled: true });

  const [enabledPreview, setEnabledPreview] = useState('');

  const CATEGORIES = ["general", "backend", "frontend", "rag", "agents", "safety", "docker", "style"];

  const fetchRules = async () => {
    setLoading(true);
    try {
      const url = filterCategory ? `/rules?category=${filterCategory}` : '/rules';
      const res = await apiClient.getJson(url);
      setRules(res.rules || []);
    } catch (err) {
      console.error("Failed to fetch rules", err);
    }
    setLoading(false);
  };

  const fetchPreview = async () => {
    try {
      const res = await apiClient.getJson('/rules/enabled-text');
      setEnabledPreview(res.text || 'No enabled rules.');
    } catch (err) {
      console.error("Failed to fetch preview", err);
    }
  };

  useEffect(() => {
    fetchRules();
    fetchPreview();
  }, [filterCategory]);

  const handleSeedDefaults = async () => {
    try {
      await apiClient.postJson('/rules/seed-defaults', {});
      fetchRules();
      fetchPreview();
    } catch (err) {
      alert(`Seed failed: ${err.message}`);
    }
  };

  const handleToggleEnabled = async (ruleId, currentEnabled) => {
    try {
      await apiClient.postJson(`/rules/${ruleId}?_method=PUT`, { enabled: !currentEnabled }, 'PUT');
      fetchRules();
      fetchPreview();
    } catch (err) {
      alert(`Toggle failed: ${err.message}`);
    }
  };

  const handleDelete = async (ruleId) => {
    if (!window.confirm("Are you sure you want to delete this rule?")) return;
    try {
      await apiClient.deleteJson(`/rules/${ruleId}`);
      fetchRules();
      fetchPreview();
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  const handleSaveRule = async (e) => {
    e.preventDefault();
    try {
      if (currentRule.id) {
        await apiClient.postJson(`/rules/${currentRule.id}?_method=PUT`, currentRule, 'PUT');
      } else {
        await apiClient.postJson('/rules', currentRule);
      }
      setIsEditing(false);
      setCurrentRule({ title: '', content: '', category: 'general', priority: 100, enabled: true });
      fetchRules();
      fetchPreview();
    } catch (err) {
      alert(`Save failed: ${err.message}`);
    }
  };

  const openEditor = (rule = { title: '', content: '', category: 'general', priority: 100, enabled: true }) => {
    setCurrentRule({ ...rule });
    setIsEditing(true);
  };

  return (
    <Section title="Project Rules & Guardrails" description="Define rules that agents must strictly follow when planning, coding, or reviewing.">
      
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '24px', alignItems: 'start' }}>
        
        {/* LEFT COLUMN: RULES LIST & EDITOR */}
        <div style={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '12px', overflow: 'hidden' }}>
          
          {/* Header & Controls */}
          <div style={{ padding: '20px', borderBottom: '1px solid #30363d', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0, fontSize: '18px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span>📜</span> Active Rules
              <span style={{ fontSize: '12px', padding: '2px 8px', backgroundColor: '#3fb95022', color: '#3fb950', borderRadius: '12px' }}>{rules.length}</span>
            </h3>
            <div style={{ display: 'flex', gap: '12px' }}>
              <select 
                value={filterCategory} 
                onChange={e => setFilterCategory(e.target.value)} 
                className="form-input"
                style={{ padding: '6px 12px', width: 'auto', backgroundColor: '#0d1117' }}
              >
                <option value="">All Categories</option>
                {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <button onClick={() => openEditor()} className="btn btn-primary" style={{ padding: '6px 14px' }}>+ New Rule</button>
              <button onClick={handleSeedDefaults} className="btn" style={{ padding: '6px 14px' }}>Seed Defaults</button>
            </div>
          </div>

          {/* Editor Inline Form */}
          {isEditing && (
            <div style={{ padding: '24px', backgroundColor: '#0d1117', borderBottom: '1px solid #30363d', animation: 'slideDown 0.3s ease-out' }}>
              <h4 style={{ margin: '0 0 16px 0', fontSize: '16px', color: '#58a6ff' }}>{currentRule.id ? '✨ Edit Rule' : '✨ Create New Rule'}</h4>
              <form onSubmit={handleSaveRule} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <input 
                  required 
                  placeholder="Rule Title (e.g., Do not log secrets)" 
                  value={currentRule.title} 
                  onChange={e => setCurrentRule({ ...currentRule, title: e.target.value })} 
                  className="form-input" 
                  style={{ fontSize: '15px', fontWeight: 500 }}
                />
                <textarea 
                  required 
                  placeholder="Detailed rule instructions..." 
                  value={currentRule.content} 
                  onChange={e => setCurrentRule({ ...currentRule, content: e.target.value })} 
                  className="form-input" 
                  style={{ minHeight: '100px', resize: 'vertical', fontFamily: 'monospace' }} 
                />

                <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
                  <label style={{ fontSize: '13px', color: '#8b949e', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    Category
                    <select 
                      value={currentRule.category} 
                      onChange={e => setCurrentRule({ ...currentRule, category: e.target.value })} 
                      className="form-input"
                    >
                      {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </label>
                  <label style={{ fontSize: '13px', color: '#8b949e', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    Priority (Lower = First)
                    <input 
                      type="number" 
                      value={currentRule.priority} 
                      onChange={e => setCurrentRule({ ...currentRule, priority: parseInt(e.target.value) || 100 })} 
                      className="form-input"
                      style={{ width: '80px' }} 
                    />
                  </label>
                  <label style={{ fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', marginTop: '22px' }}>
                    <input 
                      type="checkbox" 
                      checked={currentRule.enabled} 
                      onChange={e => setCurrentRule({ ...currentRule, enabled: e.target.checked })} 
                      style={{ accentColor: '#58a6ff', width: '16px', height: '16px' }}
                    />
                    Enabled
                  </label>
                </div>

                <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                  <button type="submit" className="btn btn-primary">Save Rule</button>
                  <button type="button" onClick={() => setIsEditing(false)} className="btn">Cancel</button>
                </div>
              </form>
            </div>
          )}

          {/* Rules List */}
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {rules.map((rule, idx) => (
              <div key={rule.id} style={{ 
                display: 'flex', justifyContent: 'space-between', padding: '20px', 
                borderBottom: idx !== rules.length - 1 ? '1px solid #21262d' : 'none',
                opacity: rule.enabled ? 1 : 0.5,
                transition: 'all 0.2s',
                backgroundColor: rule.enabled ? 'transparent' : '#0d1117'
              }}>
                <div style={{ flex: 1, paddingRight: '20px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                    <span style={{ fontWeight: 600, fontSize: '15px', color: rule.enabled ? '#e6edf3' : '#8b949e' }}>{rule.title}</span>
                    <span style={{ fontSize: '10px', padding: '2px 8px', borderRadius: '12px', backgroundColor: '#30363d', color: '#c9d1d9', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      {rule.category}
                    </span>
                    <span style={{ fontSize: '11px', color: '#8b949e' }}>Pri: {rule.priority}</span>
                  </div>
                  <div style={{ fontSize: '13px', color: '#8b949e', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                    {rule.content}
                  </div>
                </div>
                
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>
                  <button 
                    onClick={() => handleToggleEnabled(rule.id, rule.enabled)} 
                    style={{ 
                      fontSize: '11px', padding: '4px 10px', borderRadius: '12px', cursor: 'pointer', border: 'none', fontWeight: 600,
                      backgroundColor: rule.enabled ? '#3fb95022' : '#30363d', color: rule.enabled ? '#3fb950' : '#8b949e',
                      transition: 'all 0.2s'
                    }}
                  >
                    {rule.enabled ? 'Enabled' : 'Disabled'}
                  </button>
                  <div style={{ display: 'flex', gap: '8px', marginTop: 'auto' }}>
                    <button onClick={() => openEditor(rule)} className="btn" style={{ padding: '4px 10px', fontSize: '11px' }}>Edit</button>
                    <button onClick={() => handleDelete(rule.id)} className="btn" style={{ padding: '4px 10px', fontSize: '11px', color: '#f85149', borderColor: '#f8514944' }}>Delete</button>
                  </div>
                </div>
              </div>
            ))}
            
            {rules.length === 0 && !loading && (
              <div style={{ padding: '40px 20px', textAlign: 'center', color: '#8b949e', fontStyle: 'italic' }}>
                <div style={{ fontSize: '32px', marginBottom: '12px', opacity: 0.5 }}>🍃</div>
                No rules found. Click 'Seed Defaults' to populate recommended guardrails.
              </div>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN: PREVIEW */}
        <div style={{ backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '12px', padding: '20px', position: 'sticky', top: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <span style={{ fontSize: '18px' }}>👁️</span>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>Context Preview</h3>
          </div>
          <p style={{ fontSize: '12px', color: '#8b949e', marginBottom: '16px', lineHeight: 1.5 }}>
            This represents the exact raw text block injected dynamically into the system prompts of active agents. 
            Only <strong>enabled</strong> rules are injected.
          </p>
          <div style={{ 
            position: 'relative',
            borderRadius: '8px',
            background: 'linear-gradient(180deg, #0d1117 0%, #161b22 100%)',
            border: '1px solid #30363d',
            padding: '16px',
            height: '400px',
            overflowY: 'auto'
          }}>
            <pre style={{ 
              margin: 0, 
              fontFamily: '"Fira Code", monospace', 
              fontSize: '12px', 
              color: '#c9d1d9',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              lineHeight: 1.6
            }}>
              {enabledPreview}
            </pre>
          </div>
        </div>

      </div>
    </Section>
  );
}

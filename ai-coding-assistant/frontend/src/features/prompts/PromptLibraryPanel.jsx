import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function PromptLibraryPanel() {
  const [prompts, setPrompts] = useState([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('custom');
  const [template, setTemplate] = useState('');
  const [variablesInput, setVariablesInput] = useState('');
  const [tagsInput, setTagsInput] = useState('');

  const [filterCategory, setFilterCategory] = useState('');
  const [editingId, setEditingId] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  const [renderVariablesJson, setRenderVariablesJson] = useState('{\n  \n}');
  const [renderedPrompt, setRenderedPrompt] = useState(null);
  const [renderError, setRenderError] = useState(null);

  const categories = ["planner", "coder", "reviewer", "rag", "web_search", "browser", "custom"];

  const fetchPrompts = async () => {
    try {
      let url = '/prompts?limit=50';
      if (filterCategory) url += `&category=${filterCategory}`;
      const data = await apiClient.getJson(url);
      setPrompts(data.prompts || []);
    } catch (err) {
      console.error("Failed to fetch prompts", err);
    }
  };

  useEffect(() => {
    fetchPrompts();
  }, [filterCategory]);

  const handleSave = async () => {
    if (!name || !template) return alert("Name and template are required");
    setIsSaving(true);

    const vars = variablesInput.split(',').map(v => v.trim()).filter(v => v);
    const tags = tagsInput.split(',').map(t => t.trim()).filter(t => t);

    const payload = {
      name, description, category, template, variables: vars, tags
    };

    try {
      if (editingId) {
        await apiClient.putJson(`/prompts/${editingId}`, payload);
        alert("Prompt updated!");
      } else {
        await apiClient.postJson('/prompts', payload);
        alert("Prompt saved!");
      }
      resetForm();
      fetchPrompts();
    } catch (err) {
      alert(`Save failed: ${err.message}`);
    }
    setIsSaving(false);
  };

  const handleEdit = (p) => {
    setEditingId(p.id);
    setName(p.name);
    setDescription(p.description || '');
    setCategory(p.category);
    setTemplate(p.template);
    setVariablesInput((p.variables || []).join(', '));
    setTagsInput((p.tags || []).join(', '));
    setRenderVariablesJson('{\n  ' + (p.variables || []).map(v => `"${v}": ""`).join(',\n  ') + '\n}');
    setRenderedPrompt(null);
    setRenderError(null);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this prompt template?")) return;
    try {
      await apiClient.deleteJson(`/prompts/${id}`);
      fetchPrompts();
      if (editingId === id) resetForm();
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  const handleRender = async () => {
    if (!editingId) return alert("Select or save a prompt first");
    setRenderedPrompt(null);
    setRenderError(null);
    try {
      const vars = JSON.parse(renderVariablesJson);
      const res = await apiClient.postJson(`/prompts/${editingId}/render`, { variables: vars });
      setRenderedPrompt(res.rendered_prompt);
    } catch (err) {
      setRenderError(err.message);
    }
  };

  const resetForm = () => {
    setEditingId(null);
    setName('');
    setDescription('');
    setCategory('custom');
    setTemplate('');
    setVariablesInput('');
    setTagsInput('');
    setRenderVariablesJson('{\n  \n}');
    setRenderedPrompt(null);
    setRenderError(null);
  };

  return (
    <Section title="Prompt Library" description="Manage reusable prompt templates." >

      <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px'}}>
        <div>
          <div style={{padding: '15px', borderRadius: '6px', marginBottom: '20px'}}>
            <h4>{editingId ? 'Edit Prompt' : 'Create Prompt'}</h4>
            <input type="text" placeholder="Name" value={name} onChange={e => setName(e.target.value)} style={{width: '100%', marginBottom: '10px', padding: '8px', boxSizing: 'border-box'}} />
            <input type="text" placeholder="Description" value={description} onChange={e => setDescription(e.target.value)} style={{width: '100%', marginBottom: '10px', padding: '8px', boxSizing: 'border-box'}} />

            <div style={{display: 'flex', gap: '10px', marginBottom: '10px'}}>
              <select value={category} onChange={e => setCategory(e.target.value)} style={{padding: '8px', flex: 1}}>
                {categories.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>

            <textarea placeholder="Template content... Use {{var_name}} for variables." value={template} onChange={e => setTemplate(e.target.value)} rows={8} style={{width: '100%', marginBottom: '10px', padding: '8px', boxSizing: 'border-box', fontFamily: 'monospace'}} />

            <input type="text" placeholder="Variables (comma separated, e.g., url, expected_text)" value={variablesInput} onChange={e => setVariablesInput(e.target.value)} style={{width: '100%', marginBottom: '10px', padding: '8px', boxSizing: 'border-box'}} />
            <input type="text" placeholder="Tags (comma separated, e.g., bugfix, test)" value={tagsInput} onChange={e => setTagsInput(e.target.value)} style={{width: '100%', marginBottom: '10px', padding: '8px', boxSizing: 'border-box'}} />

            <div style={{display: 'flex', gap: '10px'}}>
              <LoadingButton loading={isSaving} onClick={handleSave} text={editingId ? "Update Prompt" : "Save Prompt"}  />
              {editingId && <button onClick={resetForm} style={{padding: '8px 12px'}}>Cancel</button>}
            </div>
          </div>

          {editingId && (
            <div style={{padding: '15px', borderRadius: '6px'}}>
              <h4 style={{margin: '0 0 10px 0'}}>Render Test</h4>
              <textarea value={renderVariablesJson} onChange={e => setRenderVariablesJson(e.target.value)} rows={5} style={{width: '100%', marginBottom: '10px', padding: '8px', boxSizing: 'border-box', fontFamily: 'monospace'}} />
              <button onClick={handleRender} style={{padding: '8px 12px', borderRadius: '4px', cursor: 'pointer', marginBottom: '10px'}}>Render</button>

              {renderError && <div style={{fontSize: '12px', marginBottom: '10px'}}>{renderError}</div>}
              {renderedPrompt && (
                <div>
                  <label style={{fontSize: '12px', fontWeight: 'bold'}}>Rendered Output:</label>
                  <div style={{padding: '10px', borderRadius: '4px', whiteSpace: 'pre-wrap', fontSize: '13px', fontFamily: 'monospace', maxHeight: '200px', overflowY: 'auto'}}>
                    {renderedPrompt}
                  </div>
                  <button onClick={() => navigator.clipboard.writeText(renderedPrompt)} style={{marginTop: '5px', fontSize: '11px', padding: '3px 8px'}}>Copy Output</button>
                </div>
              )}
            </div>
          )}
        </div>

        <div>
          <div style={{display: 'flex', gap: '10px', marginBottom: '15px'}}>
            <select value={filterCategory} onChange={e => setFilterCategory(e.target.value)} style={{padding: '6px'}}>
              <option value="">All Categories</option>
              {categories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          <div style={{display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '600px', overflowY: 'auto'}}>
            {prompts.map(p => (
              <div key={p.id} style={{padding: '10px', borderRadius: '4px'}}>
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start'}}>
                  <div>
                    <h5 style={{margin: '0 0 5px 0', fontSize: '15px'}}>{p.name}</h5>
                    <div style={{fontSize: '12px', marginBottom: '5px'}}>{p.description}</div>
                  </div>
                  <div>
                    <button onClick={() => handleEdit(p)} style={{marginRight: '5px', padding: '3px 8px', fontSize: '11px'}}>Edit</button>
                    <button onClick={() => handleDelete(p.id)} style={{padding: '3px 8px', fontSize: '11px'}}>Delete</button>
                  </div>
                </div>
                <div style={{fontSize: '11px', marginTop: '5px'}}>
                  <span style={{padding: '2px 6px', borderRadius: '3px', marginRight: '5px'}}>{p.category}</span>
                  Tags: {(p.tags || []).join(', ') || 'none'}
                </div>
              </div>
            ))}
            {prompts.length === 0 && <p style={{fontSize: '13px'}}>No prompts found.</p>}
          </div>
        </div>
      </div>

    </Section>
  );
}

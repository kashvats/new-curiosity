import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function ManualNotesPanel({ kbs, fetchDocuments }) {
  const [notes, setNotes] = useState([]);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [tagsInput, setTagsInput] = useState('');
  const [kbId, setKbId] = useState('');
  const [createJob, setCreateJob] = useState(false);
  const [editingNoteId, setEditingNoteId] = useState(null);
  const [isSaving, setIsSaving] = useState(false);

  const fetchNotes = async () => {
    try {
      const data = await apiClient.getJson('/memory/manual-notes');
      setNotes(data.notes || []);
    } catch (err) {
      console.error("Failed to fetch notes", err);
    }
  };

  useEffect(() => {
    fetchNotes();
  }, []);

  const handleSave = async () => {
    if (!title || !content) return alert("Title and content are required");
    setIsSaving(true);
    
    const tags = tagsInput.split(',').map(t => t.trim()).filter(t => t);
    
    try {
      if (editingNoteId) {
        await apiClient.putJson(`/memory/manual-notes/${editingNoteId}`, {
          title, content, tags
        });
        alert("Note updated. Please re-run chunking and indexing.");
      } else {
        await apiClient.postJson('/memory/manual-note', {
          title, content, tags, knowledge_base_id: kbId || null, create_job: createJob
        });
        alert("Note saved!");
      }
      
      setTitle('');
      setContent('');
      setTagsInput('');
      setKbId('');
      setCreateJob(false);
      setEditingNoteId(null);
      fetchNotes();
      if (fetchDocuments) fetchDocuments();
    } catch (err) {
      alert(`Save failed: ${err.message}`);
    }
    setIsSaving(false);
  };

  const handleEdit = (note) => {
    setEditingNoteId(note.id);
    setTitle(note.title);
    setContent(note.content);
    setTagsInput((note.tags || []).join(', '));
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this manual note forever?")) return;
    try {
      await apiClient.deleteJson(`/memory/manual-notes/${id}`);
      fetchNotes();
      if (fetchDocuments) fetchDocuments();
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  const cancelEdit = () => {
    setEditingNoteId(null);
    setTitle('');
    setContent('');
    setTagsInput('');
  };

  return (
    <Section title="Manual Notes" description="Add plain-text notes to your knowledge base." >
      
      <div style={{padding: '15px', borderRadius: '6px', marginBottom: '20px'}}>
        <h4>{editingNoteId ? 'Edit Note' : 'Create New Note'}</h4>
        <input
          type="text"
          placeholder="Title (e.g., Coding Standards)"
          value={title}
          onChange={e => setTitle(e.target.value)}
          style={{width: '100%', marginBottom: '10px', padding: '8px', boxSizing: 'border-box'}}
        />
        <textarea
          placeholder="Note content..."
          value={content}
          onChange={e => setContent(e.target.value)}
          rows={6}
          style={{width: '100%', marginBottom: '10px', padding: '8px', boxSizing: 'border-box'}}
        />
        <input
          type="text"
          placeholder="Tags (comma separated, e.g., rules, python)"
          value={tagsInput}
          onChange={e => setTagsInput(e.target.value)}
          style={{width: '100%', marginBottom: '10px', padding: '8px', boxSizing: 'border-box'}}
        />
        
        {!editingNoteId && (
          <div style={{display: 'flex', gap: '15px', marginBottom: '10px', alignItems: 'center'}}>
            <select value={kbId} onChange={e => setKbId(e.target.value)} style={{padding: '6px'}}>
              <option value="">Any KB (Default)</option>
              {(kbs || []).map(k => <option key={k.id} value={k.id}>{k.name}</option>)}
            </select>
            <label style={{display: 'flex', alignItems: 'center', gap: '5px'}}>
              <input type="checkbox" checked={createJob} onChange={e => setCreateJob(e.target.checked)} />
              Create Ingestion Job
            </label>
          </div>
        )}
        
        <div style={{display: 'flex', gap: '10px'}}>
          <LoadingButton loading={isSaving} onClick={handleSave} text={editingNoteId ? "Update Note" : "Save Note"}  />
          {editingNoteId && (
            <button onClick={cancelEdit} style={{padding: '8px 12px'}}>Cancel</button>
          )}
        </div>
      </div>

      <div>
        <h4>Saved Notes</h4>
        {notes.length === 0 ? <p>No notes saved.</p> : (
          <div style={{display: 'flex', flexDirection: 'column', gap: '10px'}}>
            {notes.map(note => (
              <div key={note.id} style={{padding: '10px', borderRadius: '4px'}}>
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                  <h5 style={{margin: '0 0 5px 0', fontSize: '15px'}}>{note.title}</h5>
                  <div>
                    <button onClick={() => handleEdit(note)} style={{marginRight: '5px'}}>Edit</button>
                    <button onClick={() => handleDelete(note.id)} >Delete</button>
                  </div>
                </div>
                <div style={{fontSize: '12px', marginBottom: '5px'}}>
                  Tags: {(note.tags || []).join(', ') || 'none'} | Updated: {new Date(note.updated_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

    </Section>
  );
}

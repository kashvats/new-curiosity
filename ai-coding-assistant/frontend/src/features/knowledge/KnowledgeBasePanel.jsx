import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import { apiClient } from '../../api/client';

export default function KnowledgeBasePanel({ documents, onKbChange }) {
  const [kbs, setKbs] = useState([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [selectedKb, setSelectedKb] = useState(null);

  const [assignKbId, setAssignKbId] = useState('');
  const [assignDocId, setAssignDocId] = useState('');

  const fetchKbs = async () => {
    try {
      const data = await apiClient.getJson('/knowledge-bases');
      setKbs(data);
      if (onKbChange) onKbChange(data);
    } catch (err) {
      console.error("Failed to fetch KBs", err);
    }
  };

  useEffect(() => {
    fetchKbs();
  }, []);

  const handleCreateKb = async () => {
    if (!name) return alert("Name is required");
    try {
      await apiClient.postJson('/knowledge-bases', { name, description });
      setName('');
      setDescription('');
      fetchKbs();
    } catch (err) {
      alert(`Create failed: ${err.message}`);
    }
  };

  const handleUpdateKb = async () => {
    if (!selectedKb) return;
    try {
      await apiClient.putJson(`/knowledge-bases/${selectedKb.id}`, { name, description });
      setSelectedKb(null);
      setName('');
      setDescription('');
      fetchKbs();
    } catch (err) {
      alert(`Update failed: ${err.message}`);
    }
  };

  const handleDeleteKb = async (id) => {
    if (id === 'default') return alert("Cannot delete default KB");
    if (!window.confirm("Are you sure you want to delete this KB mapping?")) return;
    try {
      await apiClient.deleteJson(`/knowledge-bases/${id}`);
      fetchKbs();
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  const handleAssignDoc = async () => {
    if (!assignKbId || !assignDocId) return alert("Select both KB and Document");
    try {
      await apiClient.postJson(`/knowledge-bases/${assignKbId}/documents/${assignDocId}`, {});
      alert("Assigned successfully");
      fetchKbs(); // Trigger reload if passed up
      if (onKbChange) onKbChange(kbs);
    } catch (err) {
      alert(`Assign failed: ${err.message}`);
    }
  };

  const handleRemoveDoc = async (kbId, docId) => {
    try {
      await apiClient.deleteJson(`/knowledge-bases/${kbId}/documents/${docId}`);
      alert("Removed successfully");
      if (onKbChange) onKbChange(kbs);
    } catch (err) {
      alert(`Remove failed: ${err.message}`);
    }
  };

  return (
    <Section title="Knowledge Bases" description="Manage collections of documents for scoped searching and chatting.">
      <div style={{display: 'flex', gap: '20px', flexWrap: 'wrap'}}>

        {/* Create / Edit KB */}
        <div style={{flex: '1', minWidth: '300px', padding: '15px', borderRadius: '4px'}}>
          <h4>{selectedKb ? 'Edit Knowledge Base' : 'Create Knowledge Base'}</h4>
          <input
            type="text"
            placeholder="Name (e.g., programming)"
            value={name}
            onChange={e => setName(e.target.value)}
            style={{width: '100%', marginBottom: '10px', padding: '6px'}}
          />
          <input
            type="text"
            placeholder="Description (optional)"
            value={description}
            onChange={e => setDescription(e.target.value)}
            style={{width: '100%', marginBottom: '10px', padding: '6px'}}
          />
          {selectedKb ? (
            <div style={{display: 'flex', gap: '10px'}}>
              <button onClick={handleUpdateKb} style={{padding: '6px 12px'}}>Update</button>
              <button onClick={() => { setSelectedKb(null); setName(''); setDescription(''); }} style={{padding: '6px 12px'}}>Cancel</button>
            </div>
          ) : (
            <button onClick={handleCreateKb} style={{padding: '6px 12px'}}>Create</button>
          )}
        </div>

        {/* Assign Documents */}
        <div style={{flex: '1', minWidth: '300px', padding: '15px', borderRadius: '4px'}}>
          <h4>Assign Document to KB</h4>
          <select value={assignKbId} onChange={e => setAssignKbId(e.target.value)} style={{width: '100%', marginBottom: '10px', padding: '6px'}}>
            <option value="">-- Select KB --</option>
            {kbs.map(k => <option key={k.id} value={k.id}>{k.name}</option>)}
          </select>
          <select value={assignDocId} onChange={e => setAssignDocId(e.target.value)} style={{width: '100%', marginBottom: '10px', padding: '6px'}}>
            <option value="">-- Select Document --</option>
            {(documents || []).filter(d => d.status !== 'duplicate').map(d => (
              <option key={d.id} value={d.id}>{d.original_filename}</option>
            ))}
          </select>
          <button onClick={handleAssignDoc} style={{padding: '6px 12px'}}>Assign</button>
        </div>
      </div>

      {/* List KBs */}
      <div style={{marginTop: '20px'}}>
        <h4>Existing Knowledge Bases</h4>
        <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '13px'}}>
          <thead>
            <tr style={{textAlign: 'left'}}>
              <th style={{padding: '8px'}}>Name</th>
              <th style={{padding: '8px'}}>Description</th>
              <th style={{padding: '8px'}}>Created</th>
              <th style={{padding: '8px'}}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {kbs.map(kb => (
              <tr key={kb.id} >
                <td style={{padding: '8px', fontWeight: 'bold'}}>{kb.name}</td>
                <td style={{padding: '8px'}}>{kb.description || '-'}</td>
                <td style={{padding: '8px'}}>{new Date(kb.created_at).toLocaleDateString()}</td>
                <td style={{padding: '8px'}}>
                  <button onClick={() => { setSelectedKb(kb); setName(kb.name); setDescription(kb.description || ''); }} style={{marginRight: '5px'}}>Edit</button>
                  {kb.id !== 'default' && (
                    <button onClick={() => handleDeleteKb(kb.id)} >Delete</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

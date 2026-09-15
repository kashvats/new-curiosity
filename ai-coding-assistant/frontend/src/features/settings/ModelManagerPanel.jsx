import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function ModelManagerPanel() {
  const [ollamaStatus, setOllamaStatus] = useState(null);
  const [availableModels, setAvailableModels] = useState([]);
  const [settings, setSettings] = useState([]);

  const [pullModelName, setPullModelName] = useState('');
  const [isPulling, setIsPulling] = useState(false);
  const [pullResult, setPullResult] = useState(null);

  const [deletePreview, setDeletePreview] = useState(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleteForce, setDeleteForce] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteResult, setDeleteResult] = useState(null);

  const [recommended, setRecommended] = useState([]);

  const ROLES = ["planner", "coder", "reviewer", "chat", "embedding"];

  const fetchData = async () => {
    try {
      const ollamaData = await apiClient.getJson('/models/ollama');
      if (ollamaData.status === 'ok') {
        setOllamaStatus('online');
        setAvailableModels(ollamaData.models);
      } else {
        setOllamaStatus('offline');
      }

      const settingsData = await apiClient.getJson('/models/settings');
      setSettings(settingsData.settings || []);

      const recData = await apiClient.getJson('/models/recommended');
      setRecommended(recData.recommended || []);
    } catch (err) {
      console.error(err);
      setOllamaStatus('offline');
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const getSettingForRole = (role) => {
    return settings.find(s => s.role === role) || { model_name: '', source: 'unknown' };
  };

  const handleSetModel = async (role, modelName) => {
    try {
      const res = await apiClient.postJson(`/models/settings/${role}?validate=true`, { model_name: modelName }, 'PUT');
      if (res.status === 'ok') {
        fetchData();
      }
    } catch (err) {
      alert(`Failed to set model: ${err.message}`);
    }
  };

  const handleResetModel = async (role) => {
    try {
      const res = await apiClient.deleteJson(`/models/settings/${role}`);
      if (res.status === 'ok') {
        fetchData();
      }
    } catch (err) {
      alert(`Failed to reset model: ${err.message}`);
    }
  };

  const handlePullModel = async (e, overrideName = null) => {
    if (e) e.preventDefault();
    const nameToPull = overrideName || pullModelName.trim();
    if (!nameToPull) return;

    setIsPulling(true);
    setPullResult(null);
    try {
      const res = await apiClient.postJson('/models/pull', { model_name: nameToPull });
      setPullResult(res);
      if (res.status === 'pulled') {
        setPullModelName('');
        fetchData();
      }
    } catch (err) {
      setPullResult({ status: 'error', message: err.message });
    }
    setIsPulling(false);
  };

  const handlePreviewDelete = async (modelName) => {
    setDeletePreview(null);
    setDeleteConfirm(false);
    setDeleteForce(false);
    setDeleteResult(null);
    try {
      const res = await apiClient.postJson('/models/delete/preview', { model_name: modelName });
      setDeletePreview(res);
    } catch (err) {
      alert(`Preview failed: ${err.message}`);
    }
  };

  const handleDeleteModel = async () => {
    if (!deletePreview || !deleteConfirm) return;
    setIsDeleting(true);
    setDeleteResult(null);
    try {
      const res = await apiClient.postJson('/models/delete', {
        model_name: deletePreview.model_name,
        confirm: deleteConfirm,
        force: deleteForce
      });
      setDeleteResult(res);
      if (res.status === 'deleted') {
        setDeletePreview(null);
        fetchData();
      }
    } catch (err) {
      setDeleteResult({ status: 'error', message: err.message });
    }
    setIsDeleting(false);
  };

  return (
    <Section title="Local Model Manager" description="Configure models used by specific agent roles and pull new models.">
      
      {/* OLLAMA STATUS BAR */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '16px 20px',
        backgroundColor: '#161b22',
        border: '1px solid #30363d',
        borderRadius: '12px',
        marginBottom: '24px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '12px',
            height: '12px',
            borderRadius: '50%',
            backgroundColor: ollamaStatus === 'online' ? '#3fb950' : '#f85149',
            boxShadow: ollamaStatus === 'online' ? '0 0 12px rgba(63, 185, 80, 0.6)' : '0 0 12px rgba(248, 81, 73, 0.6)',
            animation: ollamaStatus === 'online' ? 'pulse 2s infinite' : 'none'
          }} />
          <div>
            <h3 style={{ margin: 0, fontSize: '16px', color: '#e6edf3' }}>Ollama Local Server</h3>
            <div style={{ fontSize: '13px', color: '#8b949e', marginTop: '2px' }}>
              {ollamaStatus === 'online' ? 'Connected and actively serving models' : 'Offline or unreachable'}
            </div>
          </div>
        </div>
        <div style={{ fontSize: '24px', opacity: 0.5 }}>🦙</div>
      </div>

      {/* AVAILABLE MODELS TAGS */}
      {ollamaStatus === 'online' && availableModels.length > 0 && (
        <div style={{ marginBottom: '30px' }}>
          <h4 style={{ margin: '0 0 12px 0', fontSize: '14px', color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Locally Available Models
          </h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
            {availableModels.map(m => (
              <div key={m.name} style={{
                display: 'flex', alignItems: 'center', gap: '8px',
                padding: '6px 12px', backgroundColor: '#0d1117',
                border: '1px solid #30363d', borderRadius: '20px',
                fontSize: '13px', color: '#c9d1d9', transition: 'all 0.2s',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#58a6ff'; e.currentTarget.style.color = '#58a6ff'; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#30363d'; e.currentTarget.style.color = '#c9d1d9'; }}>
                <span>{m.name}</span>
                <div 
                  onClick={() => handlePreviewDelete(m.name)} 
                  style={{ cursor: 'pointer', padding: '2px', opacity: 0.6, transition: 'opacity 0.2s' }}
                  onMouseEnter={(e) => e.currentTarget.style.opacity = 1}
                  onMouseLeave={(e) => e.currentTarget.style.opacity = 0.6}
                  title="Delete Model"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* DELETE PREVIEW MODAL/INLINE */}
      {deletePreview && (
        <div style={{
          padding: '20px', backgroundColor: 'rgba(248, 81, 73, 0.1)', 
          border: '1px solid rgba(248, 81, 73, 0.4)', borderRadius: '12px',
          marginBottom: '24px', animation: 'fadeIn 0.3s ease-out'
        }}>
          <h4 style={{ margin: '0 0 8px 0', color: '#f85149', fontSize: '16px' }}>Delete {deletePreview.model_name}?</h4>
          <p style={{ fontSize: '14px', color: '#c9d1d9', margin: '0 0 16px 0' }}>{deletePreview.reason}</p>
          
          {deletePreview.roles_using_model.length > 0 && (
            <div style={{ marginBottom: '16px', fontSize: '13px', backgroundColor: '#161b22', padding: '10px', borderRadius: '8px' }}>
              <strong style={{ color: '#d29922' }}>Warning:</strong> Roles currently using this model: {deletePreview.roles_using_model.join(', ')}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '20px' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input type="checkbox" checked={deleteConfirm} onChange={e => setDeleteConfirm(e.target.checked)} style={{ accentColor: '#f85149' }}/>
              <span style={{ fontSize: '14px' }}>I confirm I want to delete this model.</span>
            </label>
            {!deletePreview.safe_to_delete && (
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                <input type="checkbox" checked={deleteForce} onChange={e => setDeleteForce(e.target.checked)} style={{ accentColor: '#f85149' }}/>
                <span style={{ fontSize: '14px', color: '#f85149' }}>Force delete (breaks active roles)</span>
              </label>
            )}
          </div>

          <div style={{ display: 'flex', gap: '12px' }}>
            <LoadingButton
              onClick={handleDeleteModel}
              loading={isDeleting}
              text="Delete Permanently"
              style={{ backgroundColor: '#f85149', color: '#fff', border: 'none' }}
              disabled={!deleteConfirm || (!deletePreview.safe_to_delete && !deleteForce)}
            />
            <button onClick={() => { setDeletePreview(null); setDeleteResult(null); }} className="btn">Cancel</button>
          </div>
          
          {deleteResult && (
            <div style={{ marginTop: '12px', fontSize: '13px', color: deleteResult.status === 'error' ? '#f85149' : '#3fb950' }}>
              {deleteResult.message || deleteResult.status}
            </div>
          )}
        </div>
      )}

      {/* ROLE SETTINGS GRID */}
      <h3 style={{ margin: '0 0 16px 0', fontSize: '18px', fontWeight: 600 }}>Active Role Assignments</h3>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '16px', marginBottom: '32px'
      }}>
        {ROLES.map(role => {
          const setting = getSettingForRole(role);
          const isDb = setting.source === 'database';
          return (
            <div key={role} style={{
              padding: '16px', backgroundColor: '#161b22', 
              border: `1px solid ${isDb ? '#58a6ff44' : '#30363d'}`, borderRadius: '12px',
              position: 'relative', overflow: 'hidden'
            }}>
              {isDb && <div style={{ position: 'absolute', top: 0, left: 0, width: '4px', height: '100%', backgroundColor: '#58a6ff' }}/>}
              
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                <h4 style={{ margin: 0, fontSize: '15px', textTransform: 'capitalize' }}>{role}</h4>
                <span style={{ 
                  fontSize: '10px', padding: '2px 6px', borderRadius: '4px', textTransform: 'uppercase', fontWeight: 600,
                  backgroundColor: isDb ? '#58a6ff22' : '#30363d', color: isDb ? '#58a6ff' : '#8b949e'
                }}>
                  {setting.source}
                </span>
              </div>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <select
                  value={isDb ? setting.model_name : ''}
                  onChange={(e) => handleSetModel(role, e.target.value)}
                  className="form-input"
                  style={{ padding: '8px', fontSize: '13px', backgroundColor: '#0d1117' }}
                >
                  <option value="" disabled>{setting.model_name || 'Select a model...'}</option>
                  {availableModels.map(m => <option key={m.name} value={m.name}>{m.name}</option>)}
                </select>
                
                {isDb && (
                  <button onClick={() => handleResetModel(role)} style={{
                    background: 'none', border: 'none', color: '#f85149', fontSize: '12px', 
                    cursor: 'pointer', textAlign: 'right', padding: 0, marginTop: '-4px'
                  }}>
                    Reset to env default
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* PULL NEW & RECCOMENDATIONS */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))', gap: '24px' }}>
        
        <div style={{ padding: '24px', backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <span style={{ fontSize: '20px' }}>☁️</span>
            <h3 style={{ margin: 0, fontSize: '16px' }}>Pull New Model</h3>
          </div>
          <form onSubmit={e => handlePullModel(e)} style={{ display: 'flex', gap: '12px' }}>
            <input
              type="text"
              value={pullModelName}
              onChange={e => setPullModelName(e.target.value)}
              placeholder="e.g. llama3:8b"
              className="form-input"
              style={{ flex: 1 }}
            />
            <LoadingButton type="submit" loading={isPulling} loadingText="Pulling..." text="Pull" className="btn btn-primary" />
          </form>
          {pullResult && (
            <div style={{ 
              marginTop: '16px', fontSize: '13px', padding: '12px', borderRadius: '8px',
              backgroundColor: pullResult.status === 'error' ? 'rgba(248, 81, 73, 0.1)' : 'rgba(63, 185, 80, 0.1)',
              color: pullResult.status === 'error' ? '#f85149' : '#3fb950',
              border: `1px solid ${pullResult.status === 'error' ? '#f8514944' : '#3fb95044'}`
            }}>
              {pullResult.message}
            </div>
          )}
        </div>

        <div style={{ padding: '24px', backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <span style={{ fontSize: '20px' }}>⭐</span>
            <h3 style={{ margin: 0, fontSize: '16px' }}>Hardware Recommendations</h3>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {recommended.map((rec, i) => (
              <div key={i} style={{ 
                padding: '12px', backgroundColor: '#0d1117', border: '1px solid #30363d', 
                borderRadius: '8px', transition: 'border-color 0.2s' 
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <div style={{ fontWeight: 600, color: '#e6edf3', fontSize: '14px' }}>{rec.model_name}</div>
                    <div style={{ fontSize: '11px', color: '#8b949e', textTransform: 'uppercase', marginTop: '2px' }}>{rec.role}</div>
                  </div>
                  <LoadingButton
                    loading={isPulling && pullModelName === rec.model_name}
                    onClick={() => { setPullModelName(rec.model_name); handlePullModel(null, rec.model_name); }}
                    text="Install"
                    style={{ padding: '4px 10px', fontSize: '12px' }}
                  />
                </div>
                <div style={{ marginTop: '8px', fontSize: '13px', color: '#8b949e', lineHeight: 1.4 }}>
                  {rec.reason}
                </div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </Section>
  );
}

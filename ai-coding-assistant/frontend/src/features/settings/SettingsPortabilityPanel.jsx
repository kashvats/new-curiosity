import React, { useState } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function SettingsPortabilityPanel() {
  const [exportData, setExportData] = useState(null);
  const [isExporting, setIsExporting] = useState(false);

  const [importJson, setImportJson] = useState('');
  const [previewData, setPreviewData] = useState(null);
  const [isPreviewing, setIsPreviewing] = useState(false);

  const [confirmImport, setConfirmImport] = useState(false);
  const [overwriteConflicts, setOverwriteConflicts] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);

  const [apiKey, setApiKey] = useState(localStorage.getItem('ai_assistant_api_key') || '');
  const [apiSaveStatus, setApiSaveStatus] = useState(null);

  const handleSaveApiKey = () => {
    localStorage.setItem('ai_assistant_api_key', apiKey.trim());
    setApiKey(apiKey.trim());
    setApiSaveStatus('Saved!');
    setTimeout(() => setApiSaveStatus(null), 2000);
  };

  const handleClearApiKey = () => {
    localStorage.removeItem('ai_assistant_api_key');
    setApiKey('');
    setApiSaveStatus('Cleared!');
    setTimeout(() => setApiSaveStatus(null), 2000);
  };

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const res = await apiClient.getJson('/settings/export');
      setExportData(res.export);
    } catch (err) {
      alert(`Export failed: ${err.message}`);
    }
    setIsExporting(false);
  };

  const downloadExport = () => {
    if (!exportData) return;
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(exportData, null, 2));
    const downloadAnchorNode = document.createElement('a');
    downloadAnchorNode.setAttribute("href", dataStr);
    downloadAnchorNode.setAttribute("download", `ai_assistant_settings_${new Date().toISOString().slice(0, 10)}.json`);
    document.body.appendChild(downloadAnchorNode);
    downloadAnchorNode.click();
    downloadAnchorNode.remove();
  };

  const handlePreviewImport = async () => {
    if (!importJson.trim()) return;
    setIsPreviewing(true);
    setPreviewData(null);
    setImportResult(null);
    setConfirmImport(false);
    try {
      const parsed = JSON.parse(importJson);
      const res = await apiClient.postJson('/settings/import/preview', { export: parsed });
      setPreviewData(res);
    } catch (err) {
      alert(err instanceof SyntaxError ? "Invalid JSON formatting." : `Preview failed: ${err.message}`);
    }
    setIsPreviewing(false);
  };

  const handleImport = async () => {
    if (!previewData || !confirmImport || !previewData.valid) return;
    setIsImporting(true);
    setImportResult(null);
    try {
      const parsed = JSON.parse(importJson);
      const res = await apiClient.postJson('/settings/import', {
        export: parsed,
        overwrite: overwriteConflicts,
        confirm: confirmImport
      });
      setImportResult(res);
    } catch (err) {
      alert(`Import failed: ${err.message}`);
    }
    setIsImporting(false);
  };

  return (
    <Section title="Settings & Auth" description="Manage your API keys, export configuration, and import settings.">
      
      {/* AUTHENTICATION */}
      <div style={{ marginBottom: '32px', padding: '24px', backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
          <span style={{ fontSize: '20px' }}>🔐</span>
          <h3 style={{ margin: 0, fontSize: '16px' }}>API Key Authentication</h3>
        </div>
        <p style={{ fontSize: '13px', color: '#8b949e', marginBottom: '16px' }}>
          If your backend is protected by an API key, enter it below. The key is stored securely in your browser's local storage and attached to requests.
        </p>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Enter API Key..."
            className="form-input"
            style={{ width: '300px' }}
          />
          <button onClick={handleSaveApiKey} className="btn btn-primary" style={{ padding: '8px 16px' }}>Save Key</button>
          <button onClick={handleClearApiKey} className="btn" style={{ padding: '8px 16px' }}>Clear Key</button>
          {apiSaveStatus && (
            <span style={{ fontSize: '13px', fontWeight: 600, color: '#3fb950', animation: 'fadeIn 0.3s ease-out' }}>
              {apiSaveStatus}
            </span>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))', gap: '24px' }}>
        
        {/* EXPORT PANEL */}
        <div style={{ padding: '24px', backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '12px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <span style={{ fontSize: '20px' }}>📤</span>
            <h3 style={{ margin: 0, fontSize: '16px' }}>Export Settings</h3>
          </div>
          <p style={{ fontSize: '13px', color: '#8b949e', marginBottom: '24px' }}>
            Exports model roles, prompt templates, and knowledge base metadata. Does NOT export your private documents, vector chunks, or model weights.
          </p>
          <div style={{ marginBottom: '20px' }}>
            <LoadingButton onClick={handleExport} loading={isExporting} text="Generate Export" className="btn btn-primary" style={{ width: '100%' }} />
          </div>

          {exportData && (
            <div style={{ marginTop: 'auto', animation: 'slideUp 0.3s ease-out' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#8b949e', textTransform: 'uppercase', letterSpacing: '0.05em' }}>JSON Output</span>
                <button onClick={downloadExport} className="btn" style={{ padding: '4px 10px', fontSize: '12px', borderColor: '#58a6ff44', color: '#58a6ff' }}>
                  Download .json
                </button>
              </div>
              <textarea
                readOnly
                value={JSON.stringify(exportData, null, 2)}
                className="form-input"
                style={{ width: '100%', height: '200px', fontFamily: '"Fira Code", monospace', fontSize: '12px', resize: 'none', backgroundColor: '#0d1117' }}
              />
            </div>
          )}
        </div>

        {/* IMPORT PANEL */}
        <div style={{ padding: '24px', backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '12px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
            <span style={{ fontSize: '20px' }}>📥</span>
            <h3 style={{ margin: 0, fontSize: '16px' }}>Import Settings</h3>
          </div>
          <p style={{ fontSize: '13px', color: '#8b949e', marginBottom: '16px' }}>
            Paste the exported JSON payload below to import settings. A backup of current settings will be automatically saved before changes are applied.
          </p>
          
          <textarea
            value={importJson}
            onChange={(e) => setImportJson(e.target.value)}
            placeholder="{ ...paste JSON export here... }"
            className="form-input"
            style={{ width: '100%', height: '140px', fontFamily: '"Fira Code", monospace', fontSize: '12px', resize: 'none', backgroundColor: '#0d1117', marginBottom: '16px' }}
          />
          
          <LoadingButton 
            onClick={handlePreviewImport} 
            loading={isPreviewing} 
            text="Preview Import" 
            className="btn" 
            disabled={!importJson.trim()} 
          />

          {previewData && (
            <div style={{ marginTop: '20px', padding: '16px', backgroundColor: '#0d1117', border: '1px solid #30363d', borderRadius: '8px', animation: 'slideUp 0.3s ease-out' }}>
              <h4 style={{ margin: '0 0 12px 0', fontSize: '14px', color: previewData.valid ? '#58a6ff' : '#f85149' }}>
                Preview Result: {previewData.valid ? 'Valid Payload' : 'Invalid Payload'}
              </h4>
              
              <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '13px', color: '#c9d1d9', marginBottom: '16px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <li>Rules found: {previewData.summary?.rules_count || 0}</li>
                <li>Role settings found: {previewData.summary?.settings_count || 0}</li>
                {previewData.conflicts && previewData.conflicts.length > 0 && (
                  <li style={{ color: '#d29922', marginTop: '4px' }}>
                    <strong>Conflicts detected:</strong> {previewData.conflicts.length} items exist.
                  </li>
                )}
              </ul>


              <LoadingButton onClick={handleImport} loading={isImporting} text="Apply Settings"  disabled={!confirmImport} />
            </div>
          )}

          {importResult && importResult.status === 'imported' && (
            <div style={{marginTop: '15px', padding: '15px', borderRadius: '8px'}}>
              <h4 style={{margin: '0 0 10px 0'}}>Import Successful!</h4>
              <div style={{fontSize: '12px', marginBottom: '10px'}}>
                <strong>Backup created:</strong> <span style={{fontFamily: 'monospace'}}>{importResult.backup_id}</span>
              </div>
              <table style={{width: '100%', fontSize: '12px', textAlign: 'center', borderCollapse: 'collapse'}}>
                <thead>
                  <tr >
                    <th style={{textAlign: 'left', paddingBottom: '4px'}}>Category</th>
                    <th style={{paddingBottom: '4px'}}>Created</th>
                    <th style={{paddingBottom: '4px'}}>Updated</th>
                    <th style={{paddingBottom: '4px'}}>Skipped</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.keys(importResult.created).map(key => (
                    <tr key={key} >
                      <td style={{textAlign: 'left', padding: '4px 0', textTransform: 'capitalize'}}>{key.replace('_', ' ')}</td>
                      <td style={{fontWeight: 'bold'}}>{importResult.created[key]}</td>
                      <td style={{fontWeight: 'bold'}}>{importResult.updated[key]}</td>
                      <td style={{fontWeight: 'bold'}}>{importResult.skipped[key]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </Section>
  );
}

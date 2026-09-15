import React, { useState } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function DocsGeneratorPanel() {
  const [preview, setPreview] = useState(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [confirmSave, setConfirmSave] = useState(false);
  const [saveResult, setSaveResult] = useState(null);

  const handlePreviewDocs = async () => {
    setIsPreviewing(true);
    setSaveResult(null);
    try {
      const data = await apiClient.getJson('/docs-generator/preview');
      setPreview(data);
    } catch (err) {
      alert(`Failed to generate docs preview: ${err.message}`);
    }
    setIsPreviewing(false);
  };

  const handleSaveDocs = async () => {
    if (!confirmSave) return alert("You must check the confirm box to save the documentation files.");
    setIsSaving(true);
    try {
      const data = await apiClient.postJson('/docs-generator/save', { confirm: confirmSave });
      setSaveResult(data);
      setConfirmSave(false);
    } catch (err) {
      alert(`Failed to save docs: ${err.message}`);
    }
    setIsSaving(false);
  };

  return (
    <Section title="Documentation Generator" description="Automatically scan your local workspace to generate technical Markdown docs covering components, routes, and architecture." >

      <div style={{display: 'flex', gap: '20px', flexWrap: 'wrap'}}>

        <div style={{flex: 1, minWidth: '300px', padding: '15px', borderRadius: '8px'}}>
          <h3 style={{margin: '0 0 10px 0', fontSize: '16px'}}>Generate Documentation</h3>
          <p style={{fontSize: '13px', marginBottom: '15px'}}>
            Click preview to perform a read-only scan. This will extract backend FastAPI routes and frontend React components safely without transmitting data to an LLM.
          </p>

          <LoadingButton
            loading={isPreviewing}
            loadingText="Scanning Workspace..."
            text="Preview Documentation"
            onClick={handlePreviewDocs}
            style={{marginBottom: '20px'}}
          />

          {preview && (
            <div style={{paddingTop: '15px'}}>
              <h4 style={{margin: '0 0 10px 0'}}>Scan Summary</h4>
              <ul style={{fontSize: '13px', margin: '0 0 15px 0', paddingLeft: '20px'}}>
                <li><strong>Backend Files:</strong> {preview.summary.backend_files}</li>
                <li><strong>Frontend Files:</strong> {preview.summary.frontend_files}</li>
                <li><strong>API Routes Detected:</strong> {preview.summary.routes_found}</li>
                <li><strong>React Components Detected:</strong> {preview.summary.components_found}</li>
              </ul>

              <div style={{padding: '10px', borderRadius: '4px', marginBottom: '15px'}}>
                <label style={{display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '13px', fontWeight: 'bold'}}>
                  <input type="checkbox" checked={confirmSave} onChange={e => setConfirmSave(e.target.checked)} />
                  Confirm saving documentation files to disk
                </label>
              </div>

              <LoadingButton
                loading={isSaving}
                loadingText="Saving..."
                text="Save Docs to Workspace"
                disabled={!confirmSave}
                onClick={handleSaveDocs}
                
              />
            </div>
          )}

          {saveResult && (
            <div style={{marginTop: '15px', padding: '15px', borderRadius: '4px'}}>
              <strong style={{display: 'block', marginBottom: '5px'}}>{saveResult.message}</strong>
              <ul style={{margin: 0, paddingLeft: '20px', fontSize: '12px', fontFamily: 'monospace'}}>
                {saveResult.files.map((f, i) => <li key={i}>{f}</li>)}
              </ul>
            </div>
          )}
        </div>

        {preview && (
          <div style={{flex: 1, minWidth: '300px', padding: '15px', borderRadius: '8px', maxHeight: '400px', overflowY: 'auto'}}>
            <h3 style={{margin: '0 0 10px 0', fontSize: '16px'}}>Documentation Preview</h3>

            <div style={{marginBottom: '15px'}}>
              <h4 style={{margin: '0 0 5px 0', fontSize: '14px'}}>Project Overview</h4>
              <p style={{fontSize: '12px', margin: 0}}>{preview.documentation.project_overview}</p>
            </div>

            <div style={{marginBottom: '15px'}}>
              <h4 style={{margin: '0 0 5px 0', fontSize: '14px'}}>Backend API Routes</h4>
              <ul style={{fontSize: '12px', margin: 0, paddingLeft: '20px', fontFamily: 'monospace'}}>
                {preview.documentation.backend_routes.slice(0, 10).map((r, i) => <li key={i}>{r}</li>)}
                {preview.documentation.backend_routes.length > 10 && <li>...and {preview.documentation.backend_routes.length - 10} more</li>}
              </ul>
            </div>

            <div style={{marginBottom: '15px'}}>
              <h4 style={{margin: '0 0 5px 0', fontSize: '14px'}}>Frontend Components</h4>
              <ul style={{fontSize: '12px', margin: 0, paddingLeft: '20px', fontFamily: 'monospace'}}>
                {preview.documentation.frontend_components.slice(0, 10).map((c, i) => <li key={i}>{c}</li>)}
                {preview.documentation.frontend_components.length > 10 && <li>...and {preview.documentation.frontend_components.length - 10} more</li>}
              </ul>
            </div>
          </div>
        )}

      </div>
    </Section>
  );
}

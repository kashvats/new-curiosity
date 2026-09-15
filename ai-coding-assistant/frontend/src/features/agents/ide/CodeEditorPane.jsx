import React, { useState, useEffect, useRef } from 'react';
import Editor from '@monaco-editor/react';
import { apiClient } from '../../../api/client';

export default function CodeEditorPane({ selectedFile }) {
  const [content, setContent] = useState('');
  const [originalContent, setOriginalContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!selectedFile) {
      setContent('');
      setOriginalContent('');
      return;
    }

    const fetchFile = async () => {
      setLoading(true);
      try {
        const res = await apiClient.getJson(`/workspace/fs/file?path=${encodeURIComponent(selectedFile)}`);
        if (res.status === 'ok') {
          setContent(res.content);
          setOriginalContent(res.content);
        }
      } catch (e) {
        setContent(`Error loading file: ${e.message}`);
        setOriginalContent('');
      } finally {
        setLoading(false);
      }
    };

    fetchFile();
  }, [selectedFile]);

  const handleEditorChange = (value) => {
    setContent(value);
  };

  const handleSave = async () => {
    if (!selectedFile || content === originalContent) return;
    
    setSaving(true);
    try {
      const res = await apiClient.putJson('/workspace/fs/file', {
        path: selectedFile,
        content: content
      });
      if (res.status === 'ok') {
        setOriginalContent(content);
        // Could show a subtle toast here
      }
    } catch (e) {
      console.error("Failed to save", e);
    } finally {
      setSaving(false);
    }
  };

  const isDirty = content !== originalContent;

  const getLanguageFromPath = (path) => {
    if (!path) return 'plaintext';
    const ext = path.split('.').pop().toLowerCase();
    const map = {
      'js': 'javascript',
      'jsx': 'javascript',
      'ts': 'typescript',
      'tsx': 'typescript',
      'py': 'python',
      'json': 'json',
      'md': 'markdown',
      'html': 'html',
      'css': 'css',
      'sql': 'sql',
      'yaml': 'yaml',
      'yml': 'yaml'
    };
    return map[ext] || 'plaintext';
  };

  if (!selectedFile) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)' }}>
        Select a file from the explorer to view or edit.
      </div>
    );
  }

  const filename = selectedFile.split(/[/\\]/).pop();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Editor Tabs / Header */}
      <div className="editor-header">
        <div className="editor-tab">
          <span style={{ marginRight: '8px' }}>📄</span>
          {filename}
        </div>
        <div style={{ marginLeft: '15px', fontSize: '11px', color: '#64748b' }}>
          {isDirty ? '● Unsaved changes' : ''}
        </div>
        <button 
          className="editor-action-btn"
          onClick={handleSave} 
          disabled={saving || !isDirty}
        >
          {saving ? 'Saving...' : 'Save File'}
        </button>
      </div>

      {/* Editor Body */}
      <div style={{ flex: 1, position: 'relative' }}>
        {loading ? (
          <div style={{ padding: '20px', color: '#888' }}>Loading file...</div>
        ) : (
          <Editor
            height="100%"
            language={getLanguageFromPath(selectedFile)}
            theme="vs-dark"
            value={content}
            onChange={handleEditorChange}
            options={{
              minimap: { enabled: true },
              fontSize: 14,
              wordWrap: 'on',
              scrollBeyondLastLine: false,
            }}
            onMount={(editor, monaco) => {
              // Add Command+S / Ctrl+S binding
              editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
                handleSave();
              });
            }}
          />
        )}
      </div>
    </div>
  );
}

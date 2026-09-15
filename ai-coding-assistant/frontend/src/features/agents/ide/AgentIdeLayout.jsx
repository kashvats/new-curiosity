import React, { useState, useEffect } from 'react';
import FileTree from './FileTree';
import CodeEditorPane from './CodeEditorPane';
import AiSidebar from './AiSidebar';
import { apiClient } from '../../../api/client';
import './AgentIde.css';

export default function AgentIdeLayout({ activeProject, setPage, onClose }) {
  const [fileTree, setFileTree] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [rootPath, setRootPath] = useState('');

  const fetchTree = async () => {
    try {
      const url = activeProject?.path 
        ? `/workspace/fs/tree?project_path=${encodeURIComponent(activeProject.path)}` 
        : '/workspace/fs/tree';
      const res = await apiClient.getJson(url);
      if (res.status === 'ok') {
        setFileTree(res.tree);
        setRootPath(res.root_path);
      }
    } catch (e) {
      console.error("Failed to load file tree", e);
    }
  };

  useEffect(() => {
    fetchTree();
  }, [activeProject]);

  return (
    <div className="ide-container">
      {/* Left Sidebar: File Tree */}
      <div className="ide-sidebar">
        <div style={{ padding: '10px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
          <button 
            onClick={onClose} 
            className="btn btn-primary" 
            style={{ width: '100%', fontSize: '12px', background: 'rgba(255,255,255,0.05)', color: '#94a3b8', border: '1px solid rgba(255,255,255,0.1)' }}
          >
            ← Back to Projects
          </button>
        </div>
        <h3 className="explorer-header">EXPLORER {activeProject ? `- ${activeProject.name}` : ''}</h3>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <FileTree tree={fileTree} onSelectFile={setSelectedFile} selectedFile={selectedFile} />
        </div>
      </div>

      {/* Center Pane: Editor */}
      <div className="ide-editor-container">
        <CodeEditorPane selectedFile={selectedFile} />
      </div>

      {/* Right Sidebar: AI Chat */}
      <div className="ide-ai-panel">
        <AiSidebar selectedFile={selectedFile} onFileChanged={fetchTree} />
      </div>
    </div>
  );
}

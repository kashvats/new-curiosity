import React, { useState } from 'react';
import ProjectAuditorPanel from '../maintenance/ProjectAuditorPanel';
import ArchitecturePanel from '../knowledge/ArchitecturePanel';
import ImpactAnalysisPanel from '../knowledge/ImpactAnalysisPanel';
import ChangeTimelinePanel from '../maintenance/ChangeTimelinePanel';
import AuditFixWorkflowPanel from '../maintenance/AuditFixWorkflowPanel';
import VulnerabilityScannerPanel from '../security/VulnerabilityScannerPanel';

export default function ProjectWorkspace({ projectName, onBack }) {
  const [activeTab, setActiveTab] = useState('auditor');

  const tabs = [
    { id: 'auditor', label: '🛡️ Audit & Fixes' },
    { id: 'security', label: '🔒 Security Scan' },
    { id: 'architecture', label: '🏗️ Architecture Map' },
    { id: 'impact', label: '💥 Impact Analysis' },
    { id: 'timeline', label: '⏱️ Timeline' }
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Workspace Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px', borderBottom: '1px solid var(--border-color)', backgroundColor: 'var(--bg-secondary)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <button onClick={onBack} className="btn" style={{ padding: '6px 12px', fontSize: '12px' }}>
            ← Back to Projects
          </button>
          <h2 style={{ margin: 0, fontSize: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>Project Workspace /</span>
            <span style={{ color: 'var(--text-primary)' }}>{projectName}</span>
          </h2>
        </div>
      </div>

      {/* Local Tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)' }}>
        {tabs.map(tab => (
          <div 
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{ 
              padding: '12px 24px', 
              cursor: 'pointer', 
              borderBottom: activeTab === tab.id || (activeTab === 'auditfix' && tab.id === 'auditor') ? '2px solid #58a6ff' : '2px solid transparent',
              color: activeTab === tab.id || (activeTab === 'auditfix' && tab.id === 'auditor') ? '#c9d1d9' : '#8b949e',
              fontWeight: activeTab === tab.id || (activeTab === 'auditfix' && tab.id === 'auditor') ? 600 : 400,
              fontSize: '14px'
            }}
          >
            {tab.label}
          </div>
        ))}
      </div>

      {/* Workspace Content Area */}
      <div style={{ flex: 1, overflowY: 'auto', backgroundColor: 'var(--bg-primary)' }}>
        {activeTab === 'auditor' && <ProjectAuditorPanel setPage={setActiveTab} injectedProjectName={projectName} />}
        {activeTab === 'security' && <VulnerabilityScannerPanel projectName={projectName} />}
        {activeTab === 'auditfix' && <AuditFixWorkflowPanel setPage={setActiveTab} />}
        {activeTab === 'architecture' && <ArchitecturePanel injectedProjectName={projectName} />}
        {activeTab === 'impact' && <ImpactAnalysisPanel injectedProjectName={projectName} />}
        {activeTab === 'timeline' && <ChangeTimelinePanel injectedProjectName={projectName} />}
      </div>
    </div>
  );
}

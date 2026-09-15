import React, { useState, useEffect } from 'react';
import PromptLibraryPanel from './features/prompts/PromptLibraryPanel';
import PlannerPanel from './features/agents/PlannerPanel';
import WebSearchPanel from './features/tools/WebSearchPanel';
import SettingsContainer from './features/settings/SettingsContainer';
import ModelManagerPanel from './features/settings/ModelManagerPanel';
import ProjectRulesPanel from './features/settings/ProjectRulesPanel';
import SettingsPortabilityPanel from './features/settings/SettingsPortabilityPanel';
import BrowserControlPanel from './features/tools/BrowserControlPanel';
import AnalyticsPanel from './features/analytics/AnalyticsPanel';
import DocsGeneratorPanel from './features/docs/DocsGeneratorPanel';
import MaintenancePanel from './features/maintenance/MaintenancePanel';
import ProjectAuditorPanel from './features/maintenance/ProjectAuditorPanel';
import AuditFixWorkflowPanel from './features/maintenance/AuditFixWorkflowPanel';
import ChangeTimelinePanel from './features/maintenance/ChangeTimelinePanel';
import PerformancePanel from './features/maintenance/PerformancePanel';
import TestPlannerPanel from './features/tests/TestPlannerPanel';
import TestGenerationPanel from './features/tests/TestGenerationPanel';
import CoverageAnalysisPanel from './features/tests/CoverageAnalysisPanel';
import CommandSuggestionsPanel from './features/tools/CommandSuggestionsPanel';
import BackupPanel from './features/tools/BackupPanel';
import QualityCenterContainer from './features/quality/QualityCenterContainer';
import HistoryContainer from './features/history/HistoryContainer';
import ProjectsDashboardPanel from './features/projects/ProjectsDashboardPanel';
import ProjectWorkspace from './features/projects/ProjectWorkspace';
import DashboardPanel from './features/dashboard/DashboardPanel';
import ArchitecturePanel from './features/knowledge/ArchitecturePanel';
import ImpactAnalysisPanel from './features/knowledge/ImpactAnalysisPanel';
import { apiClient } from './api/client';
import './App.css';

// ─── Navigation structure ────────────────────────────────────────────────────
const NAV = [
  {
    section: 'Auditor Ecosystem',
    items: [
      { id: 'home',             icon: '⌂',  label: 'Dashboard' },
      { id: 'projects',         icon: '📁', label: 'Projects Workspace' },
    ],
  },
  {
    section: 'Legacy Tools',
    items: [
      { id: 'settings-hub',     icon: '⚙',  label: 'Settings' },
      { id: 'dev-tools',        icon: '🛠',  label: 'Developer Tools' },
    ],
  },
];

// ─── Page title map ───────────────────────────────────────────────────────────
const PAGE_META = {
  'agent-workspace': { title: 'Agent Workspace',  sub: 'End-to-end AI engineering workflow' },
  'knowledge-hub':   { title: 'Knowledge',        sub: 'Manage and interact with project context' },
  'quality-center':  { title: 'Quality Center',   sub: 'Project auditing, testing, and performance' },
  'history-center':  { title: 'History',          sub: 'Run history, timelines, and backups' },
  'settings-hub':    { title: 'Settings',         sub: 'Application and global configurations' },
  'dev-tools':       { title: 'Developer Tools',  sub: 'Low-level AI capabilities and tools' },
  home:         { title: 'Dashboard',        sub: 'System overview and quick access' },
  projects:     { title: 'Projects Workspace',sub: 'Manage and audit your coding projects' },
  planner:      { title: 'Task Planner',     sub: 'Break down tasks with AI planning' },
  backup:       { title: 'Backups & Snapshots', sub: 'Restore files or snapshot your project workspace' },
  rag:          { title: 'RAG Chat',         sub: 'Chat with your documents and codebase' },
  search:       { title: 'Knowledge Search', sub: 'Search across indexed knowledge' },
  kb:           { title: 'Knowledge Bases',  sub: 'Manage document collections' },
  documents:    { title: 'Documents',        sub: 'Upload and manage PDF documents' },
  websearch:    { title: 'Web Search',       sub: 'AI-assisted web research' },
  browser:      { title: 'Browser Control',  sub: 'Headless browser automation' },
  commands:     { title: 'Command AI',       sub: 'AI command suggestions for your project' },
  prompts:      { title: 'Prompt Library',   sub: 'Manage and reuse prompt templates' },
  testplanner:  { title: 'Test Planner',     sub: 'Plan test strategies with AI' },
  testgen:      { title: 'Test Generator',   sub: 'Auto-generate unit tests' },
  coverage:     { title: 'Coverage',         sub: 'Analyze test coverage reports' },
  maintenance:  { title: 'Maintenance',      sub: 'Project health and maintenance tools' },
  auditor:      { title: 'Project Auditor',  sub: 'Deep audit of project quality' },
  auditfix:     { title: 'Audit Fixes',      sub: 'Automated fix workflow for audit findings' },
  performance:  { title: 'Performance',      sub: 'Performance profiling agent' },
  timeline:     { title: 'Change Timeline',  sub: 'Chronological view of all changes' },
  models:       { title: 'Model Manager',    sub: 'Configure AI models for each role' },
  rules:        { title: 'Project Rules',    sub: 'Define coding standards and constraints' },
  settings:     { title: 'Settings',         sub: 'Export and import settings' },
  docs:         { title: 'Docs Generator',   sub: 'Auto-generate project documentation' },
  analytics:    { title: 'Analytics',        sub: 'Usage and performance analytics' },
};

// ─── Page renderer ───────────────────────────────────────────────────────────
function PageContent({ page, setPage, activeProject, setActiveProject }) {
  // If we are in the Projects Workspace tab and a project is selected, render the Workspace
  if (page === 'projects' && activeProject) {
    return <ProjectWorkspace projectName={activeProject} onBack={() => setActiveProject(null)} />;
  }

  switch (page) {
    case 'home':
      return (
        <div className="grid-1">
          <DashboardPanel setPage={setPage} />
        </div>
      );
    case 'projects':
      return <ProjectsDashboardPanel onOpenProject={(proj) => setActiveProject(proj.name)} />;
    // Agent pages
    case 'planner':   return <PlannerPanel />;
    case 'backup':    return <BackupPanel />;

    // Tool pages
    case 'websearch': return <WebSearchPanel />;
    case 'browser':   return <BrowserControlPanel />;
    case 'commands':  return <CommandSuggestionsPanel />;
    case 'prompts':   return <PromptLibraryPanel />;

    // Testing pages
    case 'testplanner': return <TestPlannerPanel />;
    case 'testgen':     return <TestGenerationPanel />;
    case 'coverage':    return <CoverageAnalysisPanel />;

    // Maintenance pages
    case 'quality-center': return <QualityCenterContainer setPage={setPage} />;
    case 'history-center': return <HistoryContainer setPage={setPage} />;
    case 'maintenance': return <MaintenancePanel />;
    case 'auditor':     return <ProjectAuditorPanel setPage={setPage} />;
    case 'auditfix':    return <AuditFixWorkflowPanel setPage={setPage} />;
    case 'performance': return <PerformancePanel />;
    case 'timeline':    return <ChangeTimelinePanel />;

    // Settings pages
    case 'settings-hub': return <SettingsContainer setPage={setPage} />;
    case 'models':    return <ModelManagerPanel />;
    case 'rules':     return <ProjectRulesPanel />;
    case 'settings':  return <SettingsPortabilityPanel />;
    case 'docs':      return <DocsGeneratorPanel />;
    case 'analytics': return <AnalyticsPanel />;

    // Knowledge and Analysis pages
    case 'architecture': return <ArchitecturePanel />;
    case 'impact': return <ImpactAnalysisPanel />;

    default: return <div style={{ color: '#7d8590', padding: '40px', textAlign: 'center' }}>Select a page from the sidebar.</div>;
  }
}

// ─── App ─────────────────────────────────────────────────────────────────────
function App() {
  const [page, setPage] = useState(() => localStorage.getItem('activePage') || 'home');
  const [activeProject, setActiveProject] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem('activePage', page);
  }, [page]);

  const meta = PAGE_META[page] || { title: page, sub: '' };
  const currentSection = NAV.find(s => s.items.some(i => i.id === page))?.section || '';

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <aside className={`sidebar${sidebarOpen ? ' open' : ''}`}>
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">A</div>
          <div className="sidebar-logo-text">
            <span className="sidebar-logo-name">AI Assistant</span>
            <span className="sidebar-logo-sub">Local · Offline · Private</span>
          </div>
        </div>

        <nav className="sidebar-nav">
          {NAV.map(({ section, items }) => (
            <div key={section}>
              <div className="sidebar-section-label">{section}</div>
              {items.map(({ id, icon, label, badge }) => (
                <div
                  key={id}
                  className={`sidebar-item${page === id ? ' active' : ''}`}
                  onClick={() => { setPage(id); setSidebarOpen(false); }}
                  title={label}
                >
                  <span className="nav-icon">{icon}</span>
                  <span className="nav-label">{label}</span>
                  {badge && <span className="nav-badge">{badge}</span>}
                </div>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      {/* ── Main ── */}
      <div className="main-content">
        {/* Topbar */}
        <div className="topbar">
          <button className="sidebar-toggle" onClick={() => setSidebarOpen(o => !o)}>☰</button>
          <div className="topbar-breadcrumb">
            {currentSection && <><span>{currentSection}</span><span className="topbar-sep">/</span></>}
            <span className="crumb-current">{meta.title}</span>
          </div>
          <div className="topbar-right">
            <div className="status-dot" title="Backend connected"></div>
            <span className="topbar-status-text">Connected</span>
          </div>
        </div>

        {/* Page */}
        <div className="page-content">
          <div className="page-header">
            <h1 className="page-title">{meta.title}</h1>
            <p className="page-subtitle">{meta.sub}</p>
          </div>
          <div className="main-scroll">
            <div className="page-container">
              <PageContent
                page={page}
                setPage={setPage}
                activeProject={activeProject}
                setActiveProject={setActiveProject}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;

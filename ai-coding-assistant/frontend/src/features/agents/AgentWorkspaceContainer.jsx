import React from 'react';
import AgentIdeLayout from './ide/AgentIdeLayout';

export default function AgentWorkspaceContainer({ setPage, activeProject, onClose }) {
  return <AgentIdeLayout activeProject={activeProject} setPage={setPage} onClose={onClose} />;
}

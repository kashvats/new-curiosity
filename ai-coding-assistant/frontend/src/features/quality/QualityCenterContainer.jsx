import React from 'react';
import './QualityCenter.css';

export default function QualityCenterContainer({ setPage }) {
  const links = [
    { id: 'auditor', icon: '🔬', label: 'Project Auditor', desc: 'Run deep AI-powered audits on your entire codebase to identify architectural flaws and code smells.' },
    { id: 'auditfix', icon: '🛠', label: 'Audit Fixes', desc: 'Automated workflow that reads audit reports and proactively applies intelligent fixes.' },
    { id: 'coverage', icon: '📈', label: 'Coverage', desc: 'Analyze test coverage reports and generate missing unit and integration tests.' },
    { id: 'performance', icon: '🚀', label: 'Performance', desc: 'Profile and trace performance bottlenecks across the stack.' },
    { id: 'architecture', icon: '🏗', label: 'Architecture', desc: 'Generate visual diagrams and architectural analysis of your components.' },
    { id: 'impact', icon: '⚡', label: 'Impact Analysis', desc: 'Assess how a proposed change will ripple through your codebase.' },
  ];

  return (
    <div className="quality-center-container">
      <div className="quality-header">
        <h1>Quality Center</h1>
        <p>Ensure your codebase remains robust, performant, and secure with our suite of intelligent AI analysis tools.</p>
      </div>
      
      <div className="quality-grid">
        {links.map(link => (
          <div key={link.id} className="quality-card" onClick={() => setPage(link.id)}>
            <div className="quality-icon-wrapper">
              {link.icon}
            </div>
            <div className="quality-card-content">
              <h3>{link.label}</h3>
              <p>{link.desc}</p>
            </div>
            <div className="quality-action">
              Launch tool <span style={{ fontSize: '16px' }}>→</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

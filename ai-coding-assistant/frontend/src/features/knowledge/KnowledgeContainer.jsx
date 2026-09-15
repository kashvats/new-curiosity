import React from 'react';

export default function KnowledgeContainer({ setPage }) {
  const links = [
    { id: 'documents', icon: '📄', label: 'Documents', desc: 'Upload and manage PDF documents' },
    { id: 'kb', icon: '🗂', label: 'Knowledge Bases', desc: 'Manage document collections' },
    { id: 'search', icon: '🔍', label: 'Knowledge Search', desc: 'Search across indexed knowledge' },
    { id: 'rag', icon: '💬', label: 'RAG Chat', desc: 'Chat with your documents and codebase' },
    { id: 'architecture', icon: '🏗', label: 'Architecture', desc: 'Visual codebase architecture analysis' },
    { id: 'impact', icon: '⚡', label: 'Impact Analysis', desc: 'Assess change impact on the codebase' },
    { id: 'notes', icon: '📝', label: 'Manual Notes', desc: 'Add manual context to knowledge base' },
  ];

  return (
    <div className="grid-3">
      {links.map(link => (
        <div key={link.id} className="panel" style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', padding: '30px', transition: 'transform 0.2s, box-shadow 0.2s' }} onClick={() => setPage(link.id)} onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-5px)'; e.currentTarget.style.boxShadow = '0 10px 20px rgba(0,0,0,0.1)'; }} onMouseLeave={e => { e.currentTarget.style.transform = 'none'; e.currentTarget.style.boxShadow = '0 1px 2px rgba(0,0,0,0.05)'; }}>
          <div style={{ fontSize: '40px', marginBottom: '15px' }}>{link.icon}</div>
          <h3 style={{ margin: '0 0 10px 0', fontSize: '18px' }}>{link.label}</h3>
          <p style={{ margin: 0, fontSize: '14px', color: 'var(--text-secondary)' }}>{link.desc}</p>
        </div>
      ))}
    </div>
  );
}

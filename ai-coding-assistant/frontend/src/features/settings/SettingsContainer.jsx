import React, { useState } from 'react';

export default function SettingsContainer({ setPage }) {
  const links = [
    { id: 'models', icon: '🤖', label: 'Model Manager', desc: 'Configure AI models for specific agent roles' },
    { id: 'rules', icon: '📜', label: 'Project Rules', desc: 'Define universal coding standards and constraints' },
    { id: 'settings', icon: '⚙️', label: 'Portability', desc: 'Export and import configurations instantly' },
    { id: 'docs', icon: '📚', label: 'Docs Generator', desc: 'Auto-generate project documentation (Coming Soon)' },
    { id: 'analytics', icon: '📈', label: 'Analytics', desc: 'Usage and performance analytics (Coming Soon)' },
  ];

  return (
    <div style={{
      maxWidth: '1000px',
      margin: '0 auto',
      animation: 'fadeIn 0.4s ease-out'
    }}>
      <div style={{ marginBottom: '30px' }}>
        <h2 style={{ 
          fontSize: '28px', 
          fontWeight: 800, 
          margin: '0 0 8px 0',
          background: 'linear-gradient(135deg, #e6edf3 0%, #8b949e 100%)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent'
        }}>
          System Configuration
        </h2>
        <p style={{ margin: 0, color: '#8b949e', fontSize: '15px' }}>
          Manage your AI models, workspace rules, and system settings in one place.
        </p>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
        gap: '20px'
      }}>
        {links.map((link, index) => {
          const isComingSoon = link.id === 'docs' || link.id === 'analytics';
          return <SettingsCard key={link.id} link={link} index={index} setPage={setPage} isComingSoon={isComingSoon} />;
        })}
      </div>
    </div>
  );
}

function SettingsCard({ link, index, setPage, isComingSoon }) {
  const [hover, setHover] = useState(false);

  return (
    <div
      onClick={() => !isComingSoon && setPage(link.id)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        padding: '24px',
        backgroundColor: hover && !isComingSoon ? '#161b22' : '#0d1117',
        border: `1px solid ${hover && !isComingSoon ? '#58a6ff55' : '#30363d'}`,
        borderRadius: '12px',
        cursor: isComingSoon ? 'not-allowed' : 'pointer',
        transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
        transform: hover && !isComingSoon ? 'translateY(-4px)' : 'translateY(0)',
        boxShadow: hover && !isComingSoon ? '0 12px 24px rgba(0,0,0,0.2)' : 'none',
        opacity: isComingSoon ? 0.5 : 1,
        position: 'relative',
        overflow: 'hidden',
        animation: `slideUp 0.4s ease-out ${index * 0.05}s both`
      }}
    >
      {hover && !isComingSoon && (
        <div style={{
          position: 'absolute',
          top: '-50px',
          right: '-50px',
          width: '100px',
          height: '100px',
          background: 'radial-gradient(circle, rgba(88,166,255,0.15) 0%, rgba(0,0,0,0) 70%)',
          borderRadius: '50%',
          pointerEvents: 'none'
        }} />
      )}

      <div style={{ fontSize: '32px', marginBottom: '16px', filter: hover && !isComingSoon ? 'drop-shadow(0 0 8px rgba(88,166,255,0.4))' : 'none', transition: 'filter 0.2s' }}>
        {link.icon}
      </div>
      <h3 style={{ 
        margin: '0 0 8px 0', 
        fontSize: '16px', 
        fontWeight: 600,
        color: hover && !isComingSoon ? '#58a6ff' : '#e6edf3',
        transition: 'color 0.2s'
      }}>
        {link.label}
        {isComingSoon && (
          <span style={{
            marginLeft: '8px',
            fontSize: '10px',
            padding: '2px 6px',
            backgroundColor: '#30363d',
            borderRadius: '10px',
            color: '#8b949e',
            verticalAlign: 'middle'
          }}>Soon</span>
        )}
      </h3>
      <p style={{ margin: 0, fontSize: '13px', color: '#8b949e', lineHeight: 1.5 }}>
        {link.desc}
      </p>
    </div>
  );
}

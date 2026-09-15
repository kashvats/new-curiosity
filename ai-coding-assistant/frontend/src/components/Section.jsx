import React from 'react';

export default function Section({ title, description, children, style = {} }) {
  return (
    <div style={{
      marginTop: 0,
      padding: '20px 24px',
      border: '1px solid #21262d',
      borderRadius: '10px',
      backgroundColor: '#161b22',
      color: '#e6edf3',
      ...style
    }}>
      {title && (
        <h2 style={{
          marginTop: 0,
          marginBottom: description ? '6px' : '18px',
          fontSize: '16px',
          fontWeight: 700,
          color: '#e6edf3',
          letterSpacing: '-0.01em',
        }}>{title}</h2>
      )}
      {description && (
        <p style={{
          color: '#7d8590',
          fontSize: '13px',
          marginTop: 0,
          marginBottom: '20px',
          lineHeight: 1.5,
        }}>{description}</p>
      )}
      <div>{children}</div>
    </div>
  );
}

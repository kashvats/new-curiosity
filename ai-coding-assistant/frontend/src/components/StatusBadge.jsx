import React from 'react';

export default function StatusBadge({ status, label, message }) {
  const getStatusColor = (s) => {
    if (s === 'ok' || s === 'applied') return '#3fb950'; // green
    if (s === 'error' || s === 'rejected') return '#f85149'; // red
    if (s === 'loading') return '#d29922'; // orange/yellow
    if (s === 'warning') return '#d29922';
    return '#7d8590'; // grey
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', marginBottom: '8px', padding: '10px', border: '1px solid #30363d', borderRadius: '6px', backgroundColor: '#0d1117' }}>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: getStatusColor(status), marginRight: '10px', boxShadow: `0 0 6px ${getStatusColor(status)}` }} />
        <span style={{ fontSize: '13px', color: '#c9d1d9' }}>{label}: <strong style={{ color: '#e6edf3' }}>{status ? status.toUpperCase() : 'UNKNOWN'}</strong></span>
      </div>
      {message && (
        <div style={{ marginTop: '5px', fontSize: '12px', color: '#7d8590', marginLeft: '20px' }}>
          {message}
        </div>
      )}
    </div>
  );
}

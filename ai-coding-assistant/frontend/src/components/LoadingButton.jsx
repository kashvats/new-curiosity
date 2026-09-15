import React from 'react';

export default function LoadingButton({ loading, loadingText, text, onClick, disabled, type = 'button', style = {} }) {
  const isDisabled = loading || disabled;
  return (
    <button
      type={type}
      disabled={isDisabled}
      onClick={onClick}
      style={{
        padding: '8px 18px',
        cursor: isDisabled ? 'not-allowed' : 'pointer',
        background: isDisabled
          ? '#21262d'
          : 'linear-gradient(135deg, #58a6ff, #bc8cff)',
        color: isDisabled ? '#7d8590' : '#0d1117',
        border: 'none',
        borderRadius: '7px',
        opacity: 1,
        fontWeight: 700,
        fontSize: '13px',
        transition: 'opacity .15s, filter .15s',
        filter: isDisabled ? 'none' : undefined,
        whiteSpace: 'nowrap',
        ...style,
      }}
      onMouseEnter={e => { if (!isDisabled) e.currentTarget.style.filter = 'brightness(1.1)'; }}
      onMouseLeave={e => { e.currentTarget.style.filter = 'none'; }}
    >
      {loading ? (loadingText || 'Loading…') : text}
    </button>
  );
}

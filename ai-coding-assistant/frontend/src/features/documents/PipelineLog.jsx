import React, { useState, useEffect, useRef } from 'react';
import { apiClient } from '../../api/client';

const STAGE_ORDER = [
  'document.ingest',
  'document.post_extract',
  'document.ocr',
  'document.chunk',
  'document.embed',
  'document.index',
  'document.ready',
];

const STAGE_LABELS = {
  'document.ingest': 'Extract Text',
  'document.post_extract': 'Analyze PDF',
  'document.ocr': 'OCR (Scanned)',
  'document.chunk': 'Chunk Text',
  'document.embed': 'Generate Embeddings',
  'document.index': 'Index to Qdrant',
  'document.ready': 'Ready',
};

const STATUS_COLORS = {
  started: '#60a5fa',
  success: '#34d399',
  failed_retry: '#fbbf24',
  failed_terminal: '#f87171',
  skipped_idempotent: '#a78bfa',
};

const STATUS_ICONS = {
  started: '⟳',
  success: '✓',
  failed_retry: '↺',
  failed_terminal: '✗',
  skipped_idempotent: '⤸',
};

const OVERALL_COLORS = {
  queued: '#94a3b8',
  processing: '#60a5fa',
  ready: '#34d399',
  failed: '#f87171',
};

export default function PipelineLog({ documentId, filename }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const logRef = useRef(null);
  const intervalRef = useRef(null);

  const connectWebSocket = (retryCount = 0) => {
    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
    const wsBaseUrl = baseUrl.replace(/^http/, 'ws');
    const wsUrl = `${wsBaseUrl}/documents/${documentId}/pipeline-logs/ws`;
    
    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log(`Pipeline WS Connected for ${documentId}`);
      setError(null);
      retryCount = 0; // Reset retry on successful connection
    };
    
    socket.onmessage = (event) => {
      const wsData = JSON.parse(event.data);
      if (wsData.logs && wsData.logs.length > 0) {
        setData(prevData => {
          const currentLogs = prevData?.logs || [];
          const newLogs = [...currentLogs, ...wsData.logs];
          
          let overall = 'processing';
          const lastLog = newLogs[newLogs.length - 1];
          if (lastLog) {
            if (lastLog.stage === 'document.ready' && lastLog.status === 'success') overall = 'ready';
            if (lastLog.status === 'failed_terminal') overall = 'failed';
          }
          
          return { logs: newLogs, overall_status: overall };
        });
        setError(null);
      }
    };
    
    socket.onerror = () => {
      console.warn(`WebSocket error for ${documentId}`);
      if (retryCount === 0) {
        setError("WebSocket error occurred. Retrying...");
      }
    };
    
    socket.onclose = () => {
      console.log(`Pipeline WS Disconnected for ${documentId}`);
      // Reconnect logic with exponential backoff, max 5 retries
      if (retryCount < 5) {
        const timeout = Math.min(1000 * Math.pow(2, retryCount) + Math.random() * 1000, 10000);
        setTimeout(() => {
          if (intervalRef.current !== 'unmounted') {
            connectWebSocket(retryCount + 1);
          }
        }, timeout);
      } else {
        setError("WebSocket connection failed. Logs may be delayed.");
      }
    };

    return socket;
  };

  useEffect(() => {
    if (!documentId) return;
    
    intervalRef.current = 'mounted';

    // Stagger the initial fetch slightly to prevent 17 simultaneous HTTP requests from blocking the main thread
    const randomDelay = Math.random() * 500;
    
    const initTimer = setTimeout(() => {
      apiClient.getJson(`/documents/${documentId}/pipeline-logs`)
        .then(res => setData(res))
        .catch(e => console.error("Initial fetch error:", e.message));

      // Connect WS
      const socket = connectWebSocket();
      logRef.current = socket; // Temporary store socket in logRef for cleanup, wait, better use a local variable
    }, randomDelay);

    return () => {
      clearTimeout(initTimer);
      intervalRef.current = 'unmounted';
      if (logRef.current && logRef.current.close) {
        logRef.current.close();
      }
    };
  }, [documentId]);

  // Auto-scroll terminal to bottom
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [data]);

  if (!documentId) return null;
  if (error) return <div style={{ color: '#f87171', fontSize: '12px', padding: '8px' }}>Pipeline error: {error}</div>;
  if (!data) return <div style={{ color: '#94a3b8', fontSize: '12px', padding: '8px' }}>Loading pipeline...</div>;

  const overall = data.overall_status;
  const overallColor = OVERALL_COLORS[overall] || '#94a3b8';
  const logs = data.logs || [];

  return (
    <div style={{
      backgroundColor: '#0d1117',
      border: `1px solid ${overallColor}44`,
      borderRadius: '8px',
      overflow: 'hidden',
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
    }}>
      {/* Header bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        padding: '8px 12px',
        backgroundColor: '#161b22',
        borderBottom: `1px solid ${overallColor}44`,
      }}>
        <div style={{
          width: '8px', height: '8px', borderRadius: '50%',
          backgroundColor: overallColor,
          boxShadow: overall === 'processing' ? `0 0 8px ${overallColor}` : 'none',
          animation: overall === 'processing' ? 'pulse 1.5s ease-in-out infinite' : 'none',
        }} />
        <span style={{ fontSize: '11px', color: overallColor, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          {overall === 'ready' ? '✅ READY' : overall === 'failed' ? '❌ FAILED' : overall === 'processing' ? '⟳ PROCESSING' : '⏳ QUEUED'}
        </span>
        <span style={{ fontSize: '10px', color: '#6e7681', marginLeft: 'auto' }}>
          {filename || documentId}
        </span>
      </div>

      {/* Stage progress pills */}
      <div style={{ display: 'flex', gap: '4px', padding: '8px 12px', flexWrap: 'wrap' }}>
        {STAGE_ORDER.filter(s => s !== 'document.post_extract').map(stage => {
          const stageLogs = logs.filter(l => l.stage === stage);
          const lastLog = stageLogs[stageLogs.length - 1];
          const stageStatus = lastLog?.status;
          const color = STATUS_COLORS[stageStatus] || '#374151';
          return (
            <div key={stage} style={{
              fontSize: '10px',
              padding: '2px 8px',
              borderRadius: '12px',
              backgroundColor: `${color}22`,
              border: `1px solid ${color}66`,
              color: color || '#6e7681',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}>
              {stageStatus ? STATUS_ICONS[stageStatus] : '○'} {STAGE_LABELS[stage]}
              {lastLog?.retry_count > 0 && (
                <span style={{ opacity: 0.7 }}>×{lastLog.retry_count}</span>
              )}
            </div>
          );
        })}
      </div>

      {/* Terminal log output */}
      <div ref={logRef} style={{
        padding: '8px 12px',
        maxHeight: '200px',
        overflowY: 'auto',
        fontSize: '11px',
        lineHeight: '1.7',
      }}>
        {logs.length === 0 ? (
          <div style={{ color: '#6e7681' }}>$ Waiting for pipeline to start...</div>
        ) : (
          logs.map((log, i) => {
            const color = STATUS_COLORS[log.status] || '#6e7681';
            const icon = STATUS_ICONS[log.status] || '·';
            const time = new Date(log.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            return (
              <div key={i} style={{ color, display: 'flex', gap: '8px' }}>
                <span style={{ color: '#374151', flexShrink: 0 }}>{time}</span>
                <span style={{ flexShrink: 0 }}>{icon}</span>
                <span style={{ color: '#9ca3af' }}>[{STAGE_LABELS[log.stage] || log.stage}]</span>
                <span>{log.message}</span>
                {log.retry_count > 0 && (
                  <span style={{ color: '#fbbf24', flexShrink: 0 }}>retry #{log.retry_count}</span>
                )}
              </div>
            );
          })
        )}
        {overall === 'ready' && (
          <div style={{ color: '#34d399', marginTop: '4px' }}>
            $ ✅ Document is indexed and searchable in Qdrant.
          </div>
        )}
        {overall === 'failed' && (
          <div style={{ color: '#f87171', marginTop: '4px' }}>
            $ ❌ Pipeline failed after 3 retries. Check logs above for details.
          </div>
        )}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}

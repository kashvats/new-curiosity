import React, { useState } from 'react';
import { apiClient } from '../../api/client';

export default function ProjectGenerator({ onComplete, onCancel }) {
  const [idea, setIdea] = useState('');
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  const handleGenerate = async () => {
    if (!idea.trim()) return;
    setGenerating(true);
    setError(null);
    
    try {
      const taskPrompt = `Initialize a new project in the workspace based on the following idea. Create a new root directory for it inside the current directory (.), name it appropriately based on the idea, set up all necessary boilerplate files, and ensure it's ready for development. Idea: ${idea}`;
      
      // Wait for the backend ReAct loop to generate the code
      await apiClient.postJson('/agent/code', { task: taskPrompt });
      
      if (onComplete) onComplete();
    } catch (err) {
      setError(err.message || 'Failed to generate project.');
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div style={{
      borderRadius: '16px',
      padding: '24px',
      marginBottom: '20px',
      background: 'linear-gradient(145deg, #161b22, #0d1117)',
      border: '1px solid #30363d',
      boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
      position: 'relative',
      overflow: 'hidden'
    }}>
      {/* Decorative background glow */}
      <div style={{
        position: 'absolute',
        top: '-50px',
        right: '-50px',
        width: '150px',
        height: '150px',
        background: 'radial-gradient(circle, rgba(88,166,255,0.15) 0%, rgba(0,0,0,0) 70%)',
        borderRadius: '50%',
        pointerEvents: 'none'
      }} />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#e6edf3', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '22px' }}>✨</span> AI Project Generator
        </h2>
        <button 
          onClick={onCancel}
          disabled={generating}
          style={{
            background: 'none', border: 'none', color: '#8b949e', cursor: generating ? 'not-allowed' : 'pointer', fontSize: '18px'
          }}
        >
          ✕
        </button>
      </div>

      <p style={{ margin: '0 0 16px 0', fontSize: '14px', color: '#8b949e' }}>
        Describe what you want to build. The AI agent will autonomously create the directory structure, install dependencies, and write the boilerplate code.
      </p>

      {error && (
        <div style={{ padding: '12px', borderRadius: '8px', backgroundColor: 'rgba(248, 81, 73, 0.1)', color: '#f85149', border: '1px solid rgba(248, 81, 73, 0.4)', marginBottom: '16px', fontSize: '13px' }}>
          {error}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <textarea
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          disabled={generating}
          placeholder="e.g., A fastify-based REST API for a blog with SQLite, or a simple Vite + React dashboard..."
          style={{
            width: '100%',
            height: '100px',
            padding: '12px 16px',
            borderRadius: '8px',
            border: '1px solid #30363d',
            backgroundColor: '#010409',
            color: '#c9d1d9',
            fontFamily: 'inherit',
            fontSize: '14px',
            resize: 'vertical',
            outline: 'none',
            transition: 'border-color 0.2s',
            boxSizing: 'border-box'
          }}
          onFocus={(e) => e.target.style.borderColor = '#58a6ff'}
          onBlur={(e) => e.target.style.borderColor = '#30363d'}
        />

        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button
            onClick={handleGenerate}
            disabled={generating || !idea.trim()}
            style={{
              padding: '10px 24px',
              borderRadius: '8px',
              backgroundColor: generating ? '#21262d' : '#238636',
              color: generating ? '#8b949e' : '#ffffff',
              border: '1px solid',
              borderColor: generating ? '#30363d' : 'rgba(240, 246, 252, 0.1)',
              fontWeight: '600',
              fontSize: '14px',
              cursor: generating || !idea.trim() ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              transition: 'all 0.2s'
            }}
          >
            {generating ? (
              <>
                <span className="spinner" style={{
                  display: 'inline-block',
                  width: '14px',
                  height: '14px',
                  border: '2px solid rgba(255,255,255,0.3)',
                  borderRadius: '50%',
                  borderTopColor: '#fff',
                  animation: 'spin 1s ease-in-out infinite'
                }} />
                Agent is building... (This may take a few minutes)
              </>
            ) : (
              <>🚀 Generate Project</>
            )}
          </button>
        </div>
      </div>
      
      <style dangerouslySetInnerHTML={{__html: `
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}} />
    </div>
  );
}

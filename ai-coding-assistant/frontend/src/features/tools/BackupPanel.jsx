import React, { useState, useEffect } from 'react';
import { apiClient } from '../../api/client';

const BackupPanel = () => {
    const [backups, setBackups] = useState([]);
    const [selectedBackup, setSelectedBackup] = useState(null);
    const [preview, setPreview] = useState(null);
    const [filePath, setFilePath] = useState('');
    const [loading, setLoading] = useState(false);
    const [snapshotName, setSnapshotName] = useState('');
    const [message, setMessage] = useState({ text: '', type: '' });

    useEffect(() => {
        loadBackups();
    }, []);

    const loadBackups = async () => {
        try {
            const data = await apiClient.getJson('/agent/backups');
            setBackups(data.backups || data);
        } catch (error) {
            console.error('Failed to load backups:', error);
        }
    };

    const handlePreview = async () => {
        if (!selectedBackup || !filePath) return;
        setLoading(true);
        setMessage({ text: '', type: '' });
        try {
            const data = await apiClient.getJson(`/agent/backups/${selectedBackup}/preview?path=${encodeURIComponent(filePath)}`);
            setPreview(data);
        } catch (error) {
            setMessage({ text: 'Failed to preview backup. Check path or backup ID.', type: 'error' });
            setPreview(null);
        } finally {
            setLoading(false);
        }
    };

    const handleRestore = async () => {
        if (!selectedBackup || !filePath) return;
        
        // Phase 16 strict requirement: Require confirmation
        const confirmed = window.confirm(`Are you sure you want to restore ${filePath} from backup ${selectedBackup}? This will overwrite the current file, but a new backup of the current state will be created first.`);
        if (!confirmed) return;

        setLoading(true);
        try {
            const res = await api.post(`/agent/backups/${selectedBackup}/restore`, {
                path: filePath,
                confirm: true
            });
            setMessage({ text: res.data.message, type: 'success' });
            setPreview(null);
            loadBackups(); // Refresh the list to show the new backup
        } catch (error) {
            setMessage({ text: 'Failed to restore backup.', type: 'error' });
        } finally {
            setLoading(false);
        }
    };

    const handleSnapshot = async () => {
        if (!snapshotName) {
            setMessage({ text: 'Please enter a snapshot name.', type: 'error' });
            return;
        }
        setLoading(true);
        setMessage({ text: 'Creating workspace snapshot...', type: 'info' });
        try {
            const res = await api.post('/agent/snapshots/create', { name: snapshotName });
            setMessage({ text: `Snapshot created: ${res.data.snapshot_id} (${res.data.file_count} files)`, type: 'success' });
            setSnapshotName('');
        } catch (error) {
            setMessage({ text: 'Failed to create snapshot.', type: 'error' });
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="card">
            <h2>Backup & Restore</h2>
            <p className="subtitle">Restore individual files from auto-backups or snapshot the entire workspace.</p>
            
            {message.text && (
                <div className={`message ${message.type}`} style={{ padding: '1rem', background: message.type === 'error' ? '#fee2e2' : '#d1fae5', color: message.type === 'error' ? '#991b1b' : '#065f46', borderRadius: '4px', marginBottom: '1rem' }}>
                    {message.text}
                </div>
            )}

            <div className="form-group" style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
                <input 
                    type="text" 
                    placeholder="Snapshot name (e.g. before-refactor)" 
                    value={snapshotName}
                    onChange={(e) => setSnapshotName(e.target.value)}
                    className="input-field"
                    style={{ flex: 1 }}
                />
                <button 
                    onClick={handleSnapshot} 
                    className="btn btn-primary"
                    disabled={loading || !snapshotName}
                >
                    Create Snapshot
                </button>
            </div>

            <hr style={{ margin: '1.5rem 0', borderColor: 'var(--border-color)' }} />

            <h3>Restore a File</h3>
            <div className="form-group" style={{ marginTop: '1rem' }}>
                <label>Select Backup File (.bak)</label>
                <select 
                    value={selectedBackup || ''} 
                    onChange={(e) => setSelectedBackup(e.target.value)}
                    className="input-field"
                >
                    <option value="">-- Select a backup --</option>
                    {backups.map(b => (
                        <option key={b.id} value={b.id}>
                            {b.id} ({new Date(b.created_at).toLocaleString()})
                        </option>
                    ))}
                </select>
            </div>

            <div className="form-group" style={{ marginTop: '1rem' }}>
                <label>Target Workspace File Path</label>
                <input 
                    type="text" 
                    placeholder="e.g. frontend/src/App.jsx" 
                    value={filePath}
                    onChange={(e) => setFilePath(e.target.value)}
                    className="input-field"
                />
            </div>

            <button 
                onClick={handlePreview} 
                className="btn btn-secondary"
                disabled={loading || !selectedBackup || !filePath}
                style={{ marginTop: '1rem' }}
            >
                Preview Diff
            </button>

            {preview && (
                <div style={{ marginTop: '1rem' }}>
                    <h4>Diff Preview</h4>
                    <pre style={{ 
                        background: 'var(--bg-secondary)', 
                        padding: '1rem', 
                        borderRadius: '4px',
                        overflowX: 'auto',
                        fontSize: '0.9rem'
                    }}>
                        {preview.current_diff || "No differences found or file is new."}
                    </pre>
                    
                    <button 
                        onClick={handleRestore} 
                        className="btn btn-primary"
                        style={{ marginTop: '1rem', backgroundColor: '#e74c3c' }}
                        disabled={loading}
                    >
                        Restore Backup
                    </button>
                </div>
            )}
        </div>
    );
};

export default BackupPanel;

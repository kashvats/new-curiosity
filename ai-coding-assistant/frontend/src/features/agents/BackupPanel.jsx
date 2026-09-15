import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import LoadingButton from '../../components/LoadingButton';
import { apiClient } from '../../api/client';

export default function BackupPanel() {
  const [backups, setBackups] = useState([]);
  const [snapshots, setSnapshots] = useState([]);
  const [snapshotName, setSnapshotName] = useState('');
  const [isSnapshotting, setIsSnapshotting] = useState(false);

  const [previewData, setPreviewData] = useState(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [restoreConfirm, setRestoreConfirm] = useState(false);
  const [isRestoring, setIsRestoring] = useState(false);

  const [snapshotPreview, setSnapshotPreview] = useState(null);
  const [snapshotRestoreConfirm, setSnapshotRestoreConfirm] = useState(false);
  const [snapshotDryRun, setSnapshotDryRun] = useState(true);
  const [snapshotDeleteExtra, setSnapshotDeleteExtra] = useState(false);
  const [isSnapshotRestoring, setIsSnapshotRestoring] = useState(false);

  const fetchBackups = async () => {
    try {
      const data = await apiClient.getJson('/agent/backups');
      setBackups(data.backups || []);
      const snapData = await apiClient.getJson('/agent/snapshots');
      setSnapshots(snapData.snapshots || []);
    } catch (err) {
      console.error("Failed to fetch backups/snapshots", err);
    }
  };

  useEffect(() => {
    fetchBackups();
  }, []);

  const handleCreateSnapshot = async (e) => {
    e.preventDefault();
    if (!snapshotName.trim()) return alert("Snapshot name is required");
    setIsSnapshotting(true);
    try {
      const data = await apiClient.postJson('/agent/snapshots/create', { name: snapshotName });
      alert(`Snapshot ${data.snapshot_id} created with ${data.file_count} files.`);
      setSnapshotName('');
      fetchBackups();
    } catch (err) {
      alert(`Failed to create snapshot: ${err.message}`);
    }
    setIsSnapshotting(false);
  };

  const handlePreview = async (backupId, path) => {
    setIsPreviewing(true);
    setPreviewData(null);
    setRestoreConfirm(false);
    try {
      const data = await apiClient.getJson(`/agent/backups/${backupId}/preview?path=${encodeURIComponent(path)}`);
      setPreviewData(data);
    } catch (err) {
      alert(`Failed to preview backup: ${err.message}`);
    }
    setIsPreviewing(false);
  };

  const handleRestore = async () => {
    if (!previewData) return;
    if (!restoreConfirm) return alert("You must check confirm.");
    setIsRestoring(true);
    try {
      const data = await apiClient.postJson(`/agent/backups/${previewData.backup_id}/restore`, {
        path: previewData.path,
        confirm: restoreConfirm
      });
      alert(`File restored safely. A new backup was created.\nStatus: ${data.status}`);
      setPreviewData(null);
      setRestoreConfirm(false);
      fetchBackups();
    } catch (err) {
      alert(`Failed to restore backup: ${err.message}`);
    }
    setIsRestoring(false);
  };

  const handlePreviewSnapshot = async (snapshotId) => {
    setSnapshotPreview(null);
    setSnapshotRestoreConfirm(false);
    setSnapshotDryRun(true);
    setSnapshotDeleteExtra(false);
    try {
      const data = await apiClient.postJson(`/agent/snapshots/${snapshotId}/restore-preview`, {});
      setSnapshotPreview(data);
    } catch (err) {
      alert(`Preview failed: ${err.message}`);
    }
  };

  const handleRestoreSnapshot = async () => {
    if (!snapshotPreview) return;
    if (!snapshotRestoreConfirm) return alert("You must confirm the restore.");
    setIsSnapshotRestoring(true);
    try {
      const data = await apiClient.postJson(`/agent/snapshots/${snapshotPreview.snapshot_id}/restore`, {
        confirm: snapshotRestoreConfirm,
        dry_run: snapshotDryRun,
        delete_extra_files: snapshotDeleteExtra
      });

      if (snapshotDryRun) {
        setSnapshotPreview(data);
      } else {
        alert(`Snapshot Restored!\nNew Pre-Restore Backup: ${data.pre_restore_snapshot_id}\nCreated: ${data.created.length}, Modified: ${data.modified.length}, Deleted: ${data.deleted.length}`);
        setSnapshotPreview(null);
        setSnapshotRestoreConfirm(false);
        fetchBackups();
      }
    } catch (err) {
      alert(`Restore failed: ${err.message}`);
    }
    setIsSnapshotRestoring(false);
  };

  return (
    <Section title="Project Backups & Snapshots" description="Safely preview and restore files overwritten by Apply operations, or create manual snapshots." >

      <div style={{marginBottom: '20px', padding: '15px', borderRadius: '8px'}}>
        <h3 style={{margin: '0 0 10px 0'}}>Create Manual Snapshot</h3>
        <form onSubmit={handleCreateSnapshot} style={{display: 'flex', gap: '10px'}}>
          <input
            type="text"
            value={snapshotName}
            onChange={e => setSnapshotName(e.target.value)}
            placeholder="before-phase-17"
            style={{padding: '8px', borderRadius: '4px', flex: 1}}
          />
          <LoadingButton type="submit" loading={isSnapshotting} loadingText="Snapshotting..." text="Create Snapshot"  />
        </form>
      </div>

      <div style={{display: 'flex', gap: '20px'}}>
        <div style={{flex: 1, padding: '15px', borderRadius: '8px', maxHeight: '400px', overflowY: 'auto'}}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px'}}>
            <h3 style={{margin: 0}}>Available Backups</h3>
            <button onClick={fetchBackups} style={{padding: '4px 8px', fontSize: '12px'}}>↻ Refresh</button>
          </div>

          {backups.length === 0 ? <p style={{fontSize: '13px'}}>No backups found.</p> : (
            <div style={{display: 'flex', flexDirection: 'column', gap: '10px'}}>
              {backups.map(b => (
                <div key={b.id} style={{padding: '10px', borderRadius: '4px'}}>
                  <div style={{fontWeight: 'bold', fontSize: '13px', marginBottom: '5px'}}>{b.created_at}</div>
                  <div style={{fontSize: '12px', marginBottom: '8px'}}>{b.files.length} file(s) backed up</div>
                  <ul style={{margin: 0, paddingLeft: '15px', fontSize: '12px', fontFamily: 'monospace'}}>
                    {b.files.map((f, i) => (
                      <li key={i} style={{marginBottom: '3px'}}>
                        <span style={{cursor: 'pointer', textDecoration: 'underline'}} onClick={() => handlePreview(b.id, f)}>
                          {f}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>

        {previewData && (
          <div style={{flex: 1, padding: '15px', borderRadius: '8px', display: 'flex', flexDirection: 'column'}}>
            <h3 style={{margin: '0 0 10px 0'}}>Preview File Restore</h3>
            <p style={{margin: '0 0 5px 0', fontSize: '13px'}}><strong>Backup ID:</strong> {previewData.backup_id}</p>
            <p style={{margin: '0 0 15px 0', fontSize: '13px'}}><strong>File:</strong> <code style={{userSelect: 'all'}}>{previewData.path}</code></p>

            <div style={{flex: 1, padding: '10px', borderRadius: '4px', overflowY: 'auto', marginBottom: '15px', maxHeight: '200px'}}>
              <pre style={{margin: 0, fontFamily: 'Consolas, Monaco, monospace', fontSize: '12px', whiteSpace: 'pre-wrap'}}>
                {previewData.current_diff || "No diff generated. File might not exist currently."}
              </pre>
            </div>

            <div style={{display: 'flex', alignItems: 'center', gap: '15px'}}>
              <label style={{display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: 'bold'}}>
                <input
                  type="checkbox"
                  checked={restoreConfirm}
                  onChange={e => setRestoreConfirm(e.target.checked)}
                />
                Confirm Overwrite
              </label>

              <LoadingButton
                loading={isRestoring}
                loadingText="Restoring..."
                text="Restore File"
                disabled={!restoreConfirm}
                onClick={handleRestore}
                
              />
            </div>
          </div>
        )}
      </div>

      <div style={{display: 'flex', gap: '20px', marginTop: '20px'}}>
        <div style={{flex: 1, padding: '15px', borderRadius: '8px', maxHeight: '400px', overflowY: 'auto'}}>
          <h3 style={{margin: '0 0 10px 0'}}>Full Project Snapshots</h3>
          {snapshots.length === 0 ? <p style={{fontSize: '13px'}}>No snapshots found.</p> : (
            <div style={{display: 'flex', flexDirection: 'column', gap: '10px'}}>
              {snapshots.map(s => (
                <div key={s.id} style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px', borderRadius: '4px'}}>
                  <div style={{fontWeight: 'bold', fontSize: '13px'}}>{s.id}</div>
                  <button onClick={() => handlePreviewSnapshot(s.id)} style={{fontSize: '12px', padding: '4px 8px', borderRadius: '4px', cursor: 'pointer'}}>Preview Restore</button>
                </div>
              ))}
            </div>
          )}
        </div>

        {snapshotPreview && (
          <div style={{flex: 1, padding: '15px', borderRadius: '8px', display: 'flex', flexDirection: 'column'}}>
            <h3 style={{margin: '0 0 10px 0'}}>Full Snapshot Restore Preview</h3>
            <p style={{margin: '0 0 10px 0', fontSize: '13px'}}><strong>Snapshot:</strong> {snapshotPreview.snapshot_id}</p>

            <div style={{flex: 1, overflowY: 'auto', marginBottom: '15px', fontSize: '12px'}}>
              <div style={{marginBottom: '5px'}}><strong>Create ({snapshotPreview.files_to_create?.length || 0}):</strong> {snapshotPreview.files_to_create?.slice(0, 5).join(', ')}{snapshotPreview.files_to_create?.length > 5 ? '...' : ''}</div>
              <div style={{marginBottom: '5px'}}><strong>Modify ({snapshotPreview.files_to_modify?.length || 0}):</strong> {snapshotPreview.files_to_modify?.slice(0, 5).join(', ')}{snapshotPreview.files_to_modify?.length > 5 ? '...' : ''}</div>
              <div style={{marginBottom: '5px'}}><strong>Delete (if enabled) ({snapshotPreview.deleted?.length || 0}):</strong> {snapshotPreview.deleted?.slice(0, 5).join(', ')}{snapshotPreview.deleted?.length > 5 ? '...' : ''}</div>
              <div style={{marginBottom: '5px'}}><strong>Unchanged ({snapshotPreview.files_unchanged?.length || 0})</strong></div>
              <div style={{marginBottom: '5px'}}><strong>Excluded ({snapshotPreview.excluded_files?.length || 0})</strong></div>
              {snapshotPreview.warnings?.length > 0 && (
                <div style={{marginTop: '10px'}}><strong>Warnings:</strong> {snapshotPreview.warnings.join(' | ')}</div>
              )}
            </div>

            <div style={{display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '15px', padding: '10px', borderRadius: '4px'}}>
              <label style={{fontSize: '13px', display: 'flex', alignItems: 'center', gap: '5px'}}>
                <input type="checkbox" checked={snapshotDryRun} onChange={e => setSnapshotDryRun(e.target.checked)} />
                Dry Run (Preview only)
              </label>
              <label style={{fontSize: '13px', display: 'flex', alignItems: 'center', gap: '5px'}}>
                <input type="checkbox" checked={snapshotDeleteExtra} onChange={e => setSnapshotDeleteExtra(e.target.checked)} />
                Delete extra files not in snapshot (Excluded folders are NEVER deleted)
              </label>
              <label style={{fontSize: '13px', display: 'flex', alignItems: 'center', gap: '5px', fontWeight: 'bold'}}>
                <input type="checkbox" checked={snapshotRestoreConfirm} onChange={e => setSnapshotRestoreConfirm(e.target.checked)} />
                Confirm Restore (A new snapshot will be created before restoring)
              </label>
            </div>

            <LoadingButton
              loading={isSnapshotRestoring}
              loadingText="Executing..."
              text={snapshotDryRun ? "Run Preview Request" : "RESTORE FULL SNAPSHOT"}
              disabled={!snapshotRestoreConfirm}
              onClick={handleRestoreSnapshot}
              style={{alignSelf: 'flex-start'}}
            />
          </div>
        )}
      </div>
    </Section>
  );
}

import React, { useState, useEffect } from 'react';
import { apiClient } from '../../api/client';

export default function ChangeTimelinePanel() {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  const [filters, setFilters] = useState({
    event_type: '',
    status: '',
    phase_number: ''
  });

  const fetchEvents = async () => {
    setLoading(true);
    setError(null);
    try {
      let url = '/timeline/events?limit=50';
      if (filters.event_type) url += `&event_type=${filters.event_type}`;
      if (filters.status) url += `&status=${filters.status}`;
      if (filters.phase_number) url += `&phase_number=${filters.phase_number}`;
      
      const data = await apiClient.getJson(url);
      setEvents(data.events || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvents();
  }, [filters]);

  return (
    <div style={{padding: '20px', borderRadius: '8px', marginBottom: '20px'}}>
      <h2>Change Timeline</h2>
      <p style={{fontSize: '14px'}}>View a unified history of system events.</p>
      
      <div style={{display: 'flex', gap: '10px', marginBottom: '15px'}}>
        <input 
          type="text" 
          placeholder="Filter by Phase #" 
          value={filters.phase_number} 
          onChange={e => setFilters({...filters, phase_number: e.target.value})}
          style={{padding: '8px', borderRadius: '4px'}}
        />
        <select 
          value={filters.event_type} 
          onChange={e => setFilters({...filters, event_type: e.target.value})}
          style={{padding: '8px', borderRadius: '4px'}}
        >
          <option value="">All Event Types</option>
          <option value="apply_dry_run">apply_dry_run</option>
          <option value="apply_completed">apply_completed</option>
          <option value="backup_created">backup_created</option>
          <option value="snapshot_created">snapshot_created</option>
          <option value="test_run">test_run</option>
          <option value="debug_report">debug_report</option>
          <option value="restore_point_created">restore_point_created</option>
          <option value="restore_completed">restore_completed</option>
        </select>
        <select 
          value={filters.status} 
          onChange={e => setFilters({...filters, status: e.target.value})}
          style={{padding: '8px', borderRadius: '4px'}}
        >
          <option value="">All Statuses</option>
          <option value="info">info</option>
          <option value="success">success</option>
          <option value="warning">warning</option>
          <option value="failed">failed</option>
        </select>
        <button onClick={fetchEvents} style={{padding: '8px 12px'}}>Refresh</button>
      </div>

      {error && <p >{error}</p>}
      
      <div style={{maxHeight: '400px', overflowY: 'auto', borderRadius: '4px'}}>
        {loading && <p style={{padding: '10px'}}>Loading timeline...</p>}
        {!loading && events.length === 0 && <p style={{padding: '10px'}}>No events found.</p>}
        {!loading && events.map(ev => {
          let relatedText = [];
          if (ev.related_snapshot_id) relatedText.push(`Snapshot: ${ev.related_snapshot_id}`);
          if (ev.related_backup_id) relatedText.push(`Backup: ${ev.related_backup_id}`);
          if (ev.related_debug_report_path) relatedText.push(`Debug Report: ${ev.related_debug_report_path}`);
          if (ev.related_test_run_id) relatedText.push(`Test Run: ${ev.related_test_run_id}`);
          
          let color = '#555';
          if (ev.status === 'success') color = 'green';
          if (ev.status === 'warning') color = 'orange';
          if (ev.status === 'failed') color = 'red';
          
          let files = [];
          try {
            files = JSON.parse(ev.files_json);
          } catch(e) {}
          
          return (
            <div key={ev.id} style={{padding: '10px 15px'}}>
              <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: '5px'}}>
                <strong style={{color}}>[{ev.status.toUpperCase()}] {ev.event_type}</strong>
                <span style={{fontSize: '12px'}}>{new Date(ev.created_at).toLocaleString()}</span>
              </div>
              <div style={{fontWeight: 'bold'}}>{ev.title}</div>
              {ev.description && <div style={{fontSize: '13px', marginTop: '5px'}}>{ev.description}</div>}
              {relatedText.length > 0 && <div style={{fontSize: '12px', marginTop: '5px'}}>{relatedText.join(' | ')}</div>}
              {files && files.length > 0 && (
                <div style={{fontSize: '11px', marginTop: '5px'}}>
                  Files: {files.slice(0, 3).join(', ')} {files.length > 3 ? `(+${files.length - 3} more)` : ''}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

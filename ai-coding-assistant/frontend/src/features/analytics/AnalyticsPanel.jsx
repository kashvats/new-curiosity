import React, { useState, useEffect } from 'react';
import Section from '../../components/Section';
import { apiClient } from '../../api/client';

export default function AnalyticsPanel() {
  const [overview, setOverview] = useState(null);
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchAnalytics = async () => {
    setLoading(true);
    setError(null);
    try {
      const overRes = await apiClient.getJson('/analytics/overview');
      setOverview(overRes);

      const actRes = await apiClient.getJson('/analytics/recent-activity?limit=20');
      setActivity(actRes.activity || []);
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchAnalytics();
  }, []);

  const Card = ({ title, value, subtext }) => (
    <div style={{flex: '1 1 150px', padding: '15px', borderRadius: '8px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)'}}>
      <div style={{fontSize: '13px', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '5px'}}>{title}</div>
      <div style={{fontSize: '24px', fontWeight: 'bold'}}>{value}</div>
      {subtext && <div style={{fontSize: '11px', marginTop: '5px'}}>{subtext}</div>}
    </div>
  );

  return (
    <Section title="Local Analytics Dashboard" description="Track your local usage and recent AI assistant activity." >

      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px'}}>
        <h3 style={{margin: 0, fontSize: '16px'}}>Overview</h3>
        <button onClick={fetchAnalytics} disabled={loading} style={{padding: '6px 12px', borderRadius: '4px', cursor: 'pointer'}}>
          {loading ? 'Refreshing...' : 'Refresh Data'}
        </button>
      </div>

      {error && <div style={{padding: '10px', borderRadius: '4px', marginBottom: '15px', fontSize: '13px'}}>Error: {error}</div>}

      {overview && (
        <div style={{display: 'flex', flexWrap: 'wrap', gap: '15px', marginBottom: '30px'}}>
          <Card
            title="Documents"
            value={overview.documents.total}
            subtext={`PDFs: ${overview.documents.pdf} | Web: ${overview.documents.web_summary} | Notes: ${overview.documents.manual_note}`}
          />
          <Card
            title="Vector Chunks"
            value={overview.chunks.total}
            subtext={`Embedded: ${overview.chunks.embedded} | Indexed: ${overview.chunks.indexed}`}
          />
          <Card
            title="Ingestion Jobs"
            value={overview.ingestion.completed}
            subtext={`Failed: ${overview.ingestion.failed} | Running: ${overview.ingestion.running} | Queued: ${overview.ingestion.queued}`}
          />
          <Card
            title="Agent Runs"
            value={overview.agents.total_runs}
            subtext={`Failed: ${overview.agents.failed_runs}`}
          />
          <Card
            title="Local Storage"
            value={`${overview.storage.total_mb} MB`}
            subtext={`Uploads: ${overview.storage.uploads_mb}MB | Extracted: ${overview.storage.extracted_mb}MB | DB/Backups: ${overview.storage.backups_mb}MB`}
          />
          {overview.models.most_used.length > 0 && (
            <Card
              title="Top Model"
              value={overview.models.most_used[0].model_name}
              subtext={`${overview.models.most_used[0].count} invocations`}
            />
          )}
        </div>
      )}

      <div style={{padding: '15px', borderRadius: '8px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)'}}>
        <h3 style={{margin: '0 0 15px 0', fontSize: '16px'}}>Recent Activity</h3>
        {activity.length === 0 ? (
          <p style={{fontSize: '13px'}}>No recent activity found.</p>
        ) : (
          <table style={{width: '100%', borderCollapse: 'collapse', fontSize: '13px'}}>
            <thead>
              <tr style={{textAlign: 'left'}}>
                <th style={{padding: '8px'}}>Time</th>
                <th style={{padding: '8px'}}>Type</th>
                <th style={{padding: '8px'}}>Activity</th>
                <th style={{padding: '8px'}}>Status</th>
              </tr>
            </thead>
            <tbody>
              {activity.map((act, i) => (
                <tr key={i} >
                  <td style={{padding: '8px'}}>{new Date(act.created_at).toLocaleString()}</td>
                  <td style={{padding: '8px'}}>
                    <span style={{padding: '2px 6px', borderRadius: '10px', fontSize: '11px', textTransform: 'capitalize'}}>
                      {act.type.replace('_', ' ')}
                    </span>
                  </td>
                  <td style={{padding: '8px'}}>{act.title}</td>
                  <td style={{padding: '8px'}}>
                    <span style={{fontWeight: 'bold',
                      textTransform: 'capitalize'}}>
                      {act.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

    </Section>
  );
}

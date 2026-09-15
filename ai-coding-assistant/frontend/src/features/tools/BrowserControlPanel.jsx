import React, { useState } from 'react';
import Section from '../../components/Section';
import { apiClient } from '../../api/client';

export default function BrowserControlPanel() {
  const [browserUrl, setBrowserUrl] = useState('');
  const [browserSelector, setBrowserSelector] = useState('');
  const [browserText, setBrowserText] = useState('');
  const [browserConfirm, setBrowserConfirm] = useState(false);
  const [browserData, setBrowserData] = useState(null);
  const [isBrowsing, setIsBrowsing] = useState(false);

  const executeBrowserAction = async (endpoint, payload) => {
    if (!browserUrl.trim()) return alert("URL is required");
    setIsBrowsing(true);
    setBrowserData(null);
    try {
      const data = await apiClient.postJson(endpoint, payload);
      setBrowserData(data);
    } catch (err) {
      setBrowserData({ status: 'error', message: err.message });
    }
    setIsBrowsing(false);
  };

  return (
    <Section title="Browser Control (Playwright)" description="Safely open URLs, extract text, take screenshots, and interact." >
      <div style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>
        <div>
          <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold'}}>Target URL:</label>
          <input
            type="text"
            value={browserUrl}
            onChange={e => setBrowserUrl(e.target.value)}
            placeholder="http://host.docker.internal:3000"
            style={{width: '100%', padding: '10px', borderRadius: '4px', boxSizing: 'border-box'}}
          />
        </div>

        <div style={{display: 'flex', gap: '10px'}}>
          <button disabled={isBrowsing} onClick={() => executeBrowserAction('/tools/browser/open', { url: browserUrl })} style={{padding: '8px 15px', cursor: 'pointer', borderRadius: '4px'}}>Open URL</button>
          <button disabled={isBrowsing} onClick={() => executeBrowserAction('/tools/browser/text', { url: browserUrl, max_chars: 5000 })} style={{padding: '8px 15px', cursor: 'pointer', borderRadius: '4px'}}>Extract Text</button>
          <button disabled={isBrowsing} onClick={() => executeBrowserAction('/tools/browser/screenshot', { url: browserUrl, full_page: true })} style={{padding: '8px 15px', cursor: 'pointer', borderRadius: '4px'}}>Take Screenshot</button>
        </div>

        <hr style={{borderColor: '#ccc', margin: '15px 0'}} />

        <div style={{display: 'flex', gap: '20px'}}>
          <div style={{flex: 1}}>
            <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold'}}>CSS Selector:</label>
            <input
              type="text"
              value={browserSelector}
              onChange={e => setBrowserSelector(e.target.value)}
              placeholder="button#submit or input[name='search']"
              style={{width: '100%', padding: '10px', borderRadius: '4px', boxSizing: 'border-box'}}
            />
          </div>
          <div style={{flex: 1}}>
            <label style={{display: 'block', marginBottom: '5px', fontWeight: 'bold'}}>Text to Type (optional):</label>
            <input
              type="text"
              value={browserText}
              onChange={e => setBrowserText(e.target.value)}
              placeholder="Hello world..."
              style={{width: '100%', padding: '10px', borderRadius: '4px', boxSizing: 'border-box'}}
            />
          </div>
        </div>

        <div style={{display: 'flex', alignItems: 'center', gap: '15px'}}>
          <label style={{display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer'}}>
            <input
              type="checkbox"
              checked={browserConfirm}
              onChange={e => setBrowserConfirm(e.target.checked)}
            />
            <strong>Confirm Action (Required)</strong>
          </label>

          <button disabled={isBrowsing} onClick={() => executeBrowserAction('/tools/browser/click', { url: browserUrl, selector: browserSelector, confirm: browserConfirm })} style={{padding: '8px 15px', cursor: 'pointer', borderRadius: '4px', fontWeight: 'bold'}}>Click Selector</button>
          <button disabled={isBrowsing} onClick={() => executeBrowserAction('/tools/browser/type', { url: browserUrl, selector: browserSelector, text: browserText, confirm: browserConfirm })} style={{padding: '8px 15px', cursor: 'pointer', borderRadius: '4px', fontWeight: 'bold'}}>Type Text</button>
        </div>
      </div>

      {browserData && (
        <div style={{marginTop: '20px', padding: '15px', borderRadius: '8px'}}>
          {browserData.status === 'error' ? (
            <div ><strong>Error:</strong> {browserData.message}</div>
          ) : (
            <div>
              <h4 style={{margin: '0 0 10px 0'}}>Action Successful</h4>
              {browserData.title && <p style={{margin: '5px 0'}}><strong>Title:</strong> {browserData.title}</p>}
              {browserData.final_url && <p style={{margin: '5px 0'}}><strong>Final URL:</strong> {browserData.final_url}</p>}

              {browserData.screenshot_path && (
                <p style={{margin: '5px 0'}}><strong>Screenshot Path:</strong> <code style={{userSelect: 'all'}}>{browserData.screenshot_path}</code></p>
              )}

              {browserData.text && (
                <div style={{marginTop: '10px'}}>
                  <strong>Extracted Text:</strong>
                  <div style={{maxHeight: '200px', overflowY: 'auto', padding: '10px', borderRadius: '4px', fontSize: '13px', marginTop: '5px'}}>
                    {browserData.text}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

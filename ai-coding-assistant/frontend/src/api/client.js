const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

async function handleResponse(res) {
  if (!res.ok) {
    let errDetail = 'Unknown error';
    try {
      const errData = await res.json();
      errDetail = errData.detail || errData.message || JSON.stringify(errData);
    } catch(e) {
      errDetail = res.statusText;
    }
    throw new Error(errDetail);
  }
  return res.json();
}

function getHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  const envKey = import.meta.env.VITE_API_KEY;
  const localKey = localStorage.getItem('ai_assistant_api_key');
  const apiKey = localKey || envKey;
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }
  return headers;
}

export const apiClient = {
  getJson: async (path) => {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      headers: getHeaders()
    });
    return handleResponse(res);
  },
  postJson: async (path, body, method = 'POST') => {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      method: method,
      headers: getHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body)
    });
    return handleResponse(res);
  },
  postForm: async (path, formData, method = 'POST') => {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      method: method,
      headers: getHeaders(),
      body: formData
    });
    return handleResponse(res);
  },
  deleteJson: async (path) => {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      method: 'DELETE',
      headers: getHeaders()
    });
    return handleResponse(res);
  }
};

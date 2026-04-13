/**
 * API service layer for NexusSentry backend communication.
 */

const API_BASE = '';  // Same origin; Vite proxy handles /api in dev

export async function checkHealth() {
  const resp = await fetch(`${API_BASE}/api/health`);
  return resp.json();
}

export async function loadSessions() {
  const resp = await fetch(`${API_BASE}/api/sessions`);
  const data = await resp.json();
  return data.sessions || [];
}

export async function deleteSession(sessionId) {
  await fetch(`${API_BASE}/api/sessions/${sessionId}`, { method: 'DELETE' });
}

export async function loadSessionManifest(sessionId) {
  const resp = await fetch(`${API_BASE}/api/sessions/${sessionId}/manifest`);
  return resp.json();
}

export async function loadArtifact(sessionId, filename) {
  const resp = await fetch(`${API_BASE}/api/sessions/${sessionId}/artifacts/${filename}`);
  if (resp.ok) return resp.text();
  return null;
}

export function getArtifactUrl(sessionId, filename) {
  return `${API_BASE}/api/sessions/${sessionId}/artifacts/${filename}`;
}

export async function optimizePrompt(prompt) {
  const resp = await fetch(`${API_BASE}/api/optimize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  });

  if (!resp.ok) {
    let detail = 'Prompt optimization failed';
    try {
      const data = await resp.json();
      detail = data.detail || detail;
    } catch {
      try {
        detail = await resp.text();
      } catch {
        // keep default message
      }
    }
    throw new Error(detail);
  }

  return resp.json();
}

/**
 * Execute a swarm run. Returns a function to read SSE events.
 * @param {string} goal
 * @param {(event: object) => void} onEvent - called for each SSE event
 * @returns {Promise<void>}
 */
export async function executeSwarm(goal, onEvent) {
  const response = await fetch(`${API_BASE}/api/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ goal }),
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          onEvent(JSON.parse(line.slice(6)));
        } catch { /* ignore parse errors */ }
      }
    }
  }
}

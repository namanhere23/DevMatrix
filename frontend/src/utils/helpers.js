/**
 * Utility helpers for the NexusSentry frontend.
 */

/** Safely escape HTML to prevent XSS */
export function escapeHtml(text) {
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

/** Escape characters for HTML attributes */
export function escapeAttr(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/** Format current time as HH:MM:SS */
export function formatTimestamp(date = new Date()) {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:${String(date.getSeconds()).padStart(2, '0')}`;
}

export function formatJsonLog(text) {
  const firstBrace = text.indexOf('{');
  const firstBracket = text.indexOf('[');
  
  if (firstBrace === -1 && firstBracket === -1) return escapeHtml(text);

  const startIdx = firstBrace >= 0 && firstBracket >= 0 
    ? Math.min(firstBrace, firstBracket)
    : Math.max(firstBrace, firstBracket);
    
  const prefix = text.substring(0, startIdx);
  const potentialJson = text.substring(startIdx);

  try {
    const parsed = JSON.parse(potentialJson);
    const highlighted = syntaxHighlight(parsed);
    return escapeHtml(prefix) + '<br/><pre class="json-block">' + highlighted + '</pre>';
  } catch (e) {
    try {
       const trimmed = potentialJson.trim();
       if (trimmed.endsWith('}') || trimmed.endsWith(']')) {
           const parsed2 = JSON.parse(trimmed);
           const highlighted2 = syntaxHighlight(parsed2);
           return escapeHtml(prefix) + '<br/><pre class="json-block">' + highlighted2 + '</pre>';
       }
    } catch(e2) {}
    return escapeHtml(text);
  }
}

function syntaxHighlight(json) {
    if (typeof json != 'string') {
         json = JSON.stringify(json, undefined, 2);
    }
    json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
        var cls = 'json-number';
        if (/^"/.test(match)) {
            if (/:$/.test(match)) {
                cls = 'json-key';
            } else {
                cls = 'json-string';
            }
        } else if (/true|false/.test(match)) {
            cls = 'json-boolean';
        } else if (/null/.test(match)) {
            cls = 'json-null';
        }
        return '<span class="' + cls + '">' + match + '</span>';
    });
}

/** Classify a log line text into a terminal CSS class */
export function classifyLogLine(text) {
  if (text.includes('✅') || text.includes('complete') || text.includes('APPROVED')) return 'event-success';
  if (text.includes('❌') || text.includes('Error') || text.includes('FAILED') || text.includes('failed')) return 'event-error';
  if (text.includes('⚠️') || text.includes('WARNING') || text.includes('Retrying')) return 'event-warning';
  if (text.includes('🛡️') || text.includes('Guardian') || text.includes('Security') || text.includes('Constitutional')) return 'event-security';
  if (text.includes('Scout') || text.includes('Architect') || text.includes('Builder') || text.includes('Critic') || text.includes('Agent') || text.includes('📌') || text.includes('🔀')) return 'event-agent';
  return 'event-log';
}

/** Get score color class */
export function scoreClass(score) {
  if (score >= 70) return '';
  if (score >= 50) return 'mid';
  return 'low';
}

/** Map task status to emoji */
export function statusIcon(status) {
  const icons = { done: '✅', failed: '❌', partial_output: '⏹️', skipped: '⏭️', human_approved: '👤' };
  return icons[status] || '❓';
}

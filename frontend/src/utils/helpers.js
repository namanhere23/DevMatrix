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

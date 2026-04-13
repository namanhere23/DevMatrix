import React, { useState } from 'react';
import { escapeHtml } from '../utils/helpers';

export default function Sidebar({
  sessions,
  activeSessionId,
  onLoadSession,
  onDeleteSession,
  onNewSession,
}) {
  const [filter, setFilter] = useState('');

  const filtered = filter
    ? sessions.filter(s => (s.goal || s.session_id).toLowerCase().includes(filter.toLowerCase()))
    : sessions;

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-label">Sessions</div>
        <button className="sidebar-new-btn" onClick={onNewSession}>+ New</button>
      </div>
      <div className="sidebar-search-wrap">
        <input
          type="text"
          className="sidebar-search"
          placeholder="Filter sessions…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
        />
      </div>
      <ul className="session-list">
        {filtered.length === 0 ? (
          <li className="sidebar-empty">
            {sessions.length === 0 ? 'No sessions yet.\nRun your first goal!' : 'No matching sessions'}
          </li>
        ) : (
          filtered.map(s => {
            const score = s.avg_score ?? 0;
            const dotClass = score >= 70 ? '' : score >= 50 ? ' mid' : ' low';
            return (
              <li
                key={s.session_id}
                className={`session-item${s.session_id === activeSessionId ? ' active' : ''}`}
                onClick={() => onLoadSession(s.session_id)}
              >
                <div className="session-item-top">
                  <div className="session-item-title">{s.goal || s.session_id}</div>
                  <button
                    className="session-delete"
                    onClick={e => { e.stopPropagation(); onDeleteSession(s.session_id); }}
                  >✕</button>
                </div>
                <div className="session-item-meta">
                  <span className={`session-score-dot${dotClass}`} />
                  <span>⏱ {s.total_time_s || '?'}s</span>
                  <span>📄 {(s.final_artifacts || []).length} files</span>
                </div>
              </li>
            );
          })
        )}
      </ul>
    </aside>
  );
}

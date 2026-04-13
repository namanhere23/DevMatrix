import React from 'react';

export default function Header({
  systemStatus,
  onToggleSidebar,
  onOpenShortcuts,
  onExportSession,
  onCopyLog,
}) {
  const isOffline = systemStatus?.offline;

  return (
    <header className="header">
      <div className="header-left">
        <button className="sidebar-toggle" onClick={onToggleSidebar} title="Toggle sidebar (Ctrl+B)">
          ☰
        </button>
        <div className="header-logo">N</div>
        <div className="header-brand-text">
          <div className="header-title"><span>NexusSentry</span> v3.1</div>
          <div className="header-subtitle">Multi-Agent Command Center</div>
        </div>
      </div>
      <div className="header-right">
        <div className={`status-badge${isOffline ? ' offline' : ''}`}>
          <div className="status-dot" />
          <span>{systemStatus?.text || 'System Ready'}</span>
        </div>
        <button className="icon-btn" onClick={onOpenShortcuts} title="Keyboard Shortcuts">
          ⌨️
          <span className="tooltip">Shortcuts (?)</span>
        </button>
        <button className="icon-btn" onClick={onExportSession} title="Export Session">
          ⬇️
          <span className="tooltip">Export JSON</span>
        </button>
        <button className="icon-btn" onClick={onCopyLog} title="Copy Terminal Log">
          📋
          <span className="tooltip">Copy Log</span>
        </button>
      </div>
    </header>
  );
}

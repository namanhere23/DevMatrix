import React from 'react';

const SHORTCUTS = [
  { label: 'Execute swarm', keys: ['Ctrl', 'Enter'] },
  { label: 'Focus prompt', keys: ['/'] },
  { label: 'Search terminal', keys: ['Ctrl', 'F'] },
  { label: 'Clear terminal', keys: ['Ctrl', 'L'] },
  { label: 'Toggle sidebar', keys: ['Ctrl', 'B'] },
  { label: 'Show shortcuts', keys: ['?'] },
  { label: 'Close modal / search', keys: ['Esc'] },
];

export default function ShortcutsModal({ open, onClose }) {
  if (!open) return null;

  return (
    <div className="modal-overlay open" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">⌨️ Keyboard Shortcuts</div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        {SHORTCUTS.map((s, i) => (
          <div className="shortcut-row" key={i}>
            <span className="shortcut-label">{s.label}</span>
            <span className="shortcut-keys">
              {s.keys.map((k, j) => <kbd key={j}>{k}</kbd>)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

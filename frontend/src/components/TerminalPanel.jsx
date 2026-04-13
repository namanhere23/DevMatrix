import React, { useState, useRef, useEffect, useCallback, forwardRef } from 'react';
import { escapeHtml, formatTimestamp } from '../utils/helpers';

const AGENT_NAMES = ['Scout', 'Architect', 'Builder', 'Critic', 'Guardian'];

const TerminalPanel = forwardRef(function TerminalPanel({
  terminalLines,
  agentStates,
  isRunning,
  onClear,
  panelRef,
}, ref) {
  const [autoScroll, setAutoScroll] = useState(true);
  const [currentFilter, setCurrentFilter] = useState('all');
  const [searchVisible, setSearchVisible] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchMatches, setSearchMatches] = useState([]);
  const [searchIdx, setSearchIdx] = useState(-1);
  const terminalBodyRef = useRef(null);
  const searchInputRef = useRef(null);

  // Filter lines based on current filter
  const visibleLines = currentFilter === 'all'
    ? terminalLines
    : terminalLines.filter(l => l.className === `event-${currentFilter}`);

  // Auto-scroll on new lines
  useEffect(() => {
    if (autoScroll && terminalBodyRef.current) {
      terminalBodyRef.current.scrollTop = terminalBodyRef.current.scrollHeight;
    }
  }, [visibleLines.length, autoScroll]);

  // Search logic
  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchMatches([]);
      setSearchIdx(-1);
      return;
    }
    const q = searchQuery.toLowerCase();
    const matches = [];
    visibleLines.forEach((line, i) => {
      if (line.text.toLowerCase().includes(q)) matches.push(i);
    });
    setSearchMatches(matches);
    setSearchIdx(matches.length > 0 ? 0 : -1);
  }, [searchQuery, visibleLines]);

  // Scroll to current match
  useEffect(() => {
    if (searchIdx >= 0 && searchMatches[searchIdx] !== undefined) {
      const lineEls = terminalBodyRef.current?.querySelectorAll('.terminal-line');
      const target = lineEls?.[searchMatches[searchIdx]];
      target?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [searchIdx, searchMatches]);

  const navSearch = (dir) => {
    if (!searchMatches.length) return;
    setSearchIdx(prev => (prev + dir + searchMatches.length) % searchMatches.length);
  };

  const toggleSearch = useCallback((forceOpen) => {
    const next = forceOpen !== undefined ? forceOpen : !searchVisible;
    setSearchVisible(next);
    if (next) {
      setTimeout(() => searchInputRef.current?.focus(), 50);
    } else {
      setSearchQuery('');
    }
  }, [searchVisible]);

  // Expose toggleSearch to parent (for keyboard shortcut)
  useEffect(() => {
    if (ref) {
      ref.current = { toggleSearch, clear: onClear };
    }
  }, [ref, toggleSearch, onClear]);

  const handleSearchKeyDown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); navSearch(e.shiftKey ? -1 : 1); }
    if (e.key === 'Escape') toggleSearch(false);
  };

  return (
    <div className="terminal-panel" ref={panelRef} style={{ width: '50%' }}>
      {/* Panel header */}
      <div className="panel-header">
        <div className="panel-title">
          <div className={`panel-title-dot${isRunning ? ' running' : ''}`} />
          Terminal
        </div>
        <div className="panel-actions">
          <button className="panel-btn" onClick={() => toggleSearch()} title="Ctrl+F">🔍</button>
          <button className="panel-btn" onClick={onClear} title="Ctrl+L">Clear</button>
          <button
            className={`panel-btn${autoScroll ? ' active' : ''}`}
            onClick={() => setAutoScroll(v => !v)}
          >↓ {autoScroll ? 'Auto' : 'Off'}</button>
          <button
            className={`panel-btn${currentFilter === 'all' ? ' active' : ''}`}
            onClick={() => setCurrentFilter('all')}
          >All</button>
          <button
            className={`panel-btn${currentFilter === 'error' ? ' active' : ''}`}
            onClick={() => setCurrentFilter('error')}
          >Errors</button>
        </div>
      </div>

      {/* Search bar */}
      <div className={`terminal-search-bar${searchVisible ? ' visible' : ''}`}>
        <input
          ref={searchInputRef}
          type="text"
          className="terminal-search-input"
          placeholder="Search terminal…"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          onKeyDown={handleSearchKeyDown}
        />
        <span className="search-count">
          {searchMatches.length === 0 ? '0 matches' : `${searchIdx + 1} / ${searchMatches.length}`}
        </span>
        <button className="search-nav-btn" onClick={() => navSearch(-1)}>↑</button>
        <button className="search-nav-btn" onClick={() => navSearch(1)}>↓</button>
        <button className="panel-btn" onClick={() => toggleSearch(false)}>✕</button>
      </div>

      {/* Agent cards */}
      <div className="agent-cards">
        {AGENT_NAMES.map((name, i) => (
          <div key={name} className={`agent-card ${agentStates[i] || 'idle'}`}>
            <span className="agent-indicator" />
            {name}
          </div>
        ))}
      </div>

      {/* Terminal body */}
      <div className="terminal-body" ref={terminalBodyRef}>
        {visibleLines.length === 0 ? (
          <div className="terminal-welcome">
            <div className="tw-icon">⚡</div>
            <h3>Agent Terminal Ready</h3>
            <p>Execute a goal to see real-time output from the swarm.</p>
            <div className="kbd-hints">
              <div className="kbd-hint"><kbd>Ctrl</kbd><kbd>Enter</kbd> Execute</div>
              <div className="kbd-hint"><kbd>Ctrl</kbd><kbd>F</kbd> Search terminal</div>
              <div className="kbd-hint"><kbd>?</kbd> All shortcuts</div>
            </div>
          </div>
        ) : (
          visibleLines.map((line, i) => {
            const isMatch = searchMatches.includes(i);
            const isCurrent = searchIdx >= 0 && searchMatches[searchIdx] === i;
            let cls = `terminal-line ${line.className}`;
            if (isMatch) cls += ' highlight-match';
            if (isCurrent) cls += ' highlight-current';

            return (
              <div key={line.id || i} className={cls}>
                <span className="terminal-timestamp">{line.ts}</span>
                <span dangerouslySetInnerHTML={{ __html: escapeHtml(line.text) }} />
              </div>
            );
          })
        )}
      </div>
    </div>
  );
});

export default TerminalPanel;

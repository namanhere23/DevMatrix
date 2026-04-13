import React, { useState, useEffect, useCallback, useRef } from 'react';
import { ToastProvider, useToast } from './components/Toast';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import PromptPanel from './components/PromptPanel';
import ProgressBar from './components/ProgressBar';
import TerminalPanel from './components/TerminalPanel';
import ResultsPanel from './components/ResultsPanel';
import ArtifactsView from './components/ArtifactsView';
import ResizeDivider from './components/ResizeDivider';
import ShortcutsModal from './components/ShortcutsModal';
import * as api from './services/api';
import { classifyLogLine, formatTimestamp } from './utils/helpers';

function App() {
  return (
    <ToastProvider>
      <div className="bg-mesh" />
      <AppInner />
    </ToastProvider>
  );
}

let lineIdCounter = 0;

function AppInner() {
  const toast = useToast();

  // ── State ──
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [systemStatus, setSystemStatus] = useState({ text: 'System Ready', offline: false });
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [progressComplete, setProgressComplete] = useState(false);
  const [terminalLines, setTerminalLines] = useState([]);
  const [agentStates, setAgentStates] = useState(['idle', 'idle', 'idle', 'idle', 'idle']);
  const [scorecard, setScorecard] = useState(null);
  const [tasks, setTasks] = useState(null);
  const [currentArtifacts, setCurrentArtifacts] = useState({});
  const [resultView, setResultView] = useState('results');

  const terminalRef = useRef(null);
  const terminalPanelRef = useRef(null);
  const outputAreaRef = useRef(null);

  // ── Init ──
  useEffect(() => {
    fetchSessions();
    fetchHealth();
  }, []);

  // ── Health check ──
  const fetchHealth = async () => {
    try {
      const data = await api.checkHealth();
      if (data.status === 'ok') {
        const prov = data.mock_mode ? 'Mock Mode' : `${data.providers.length} Providers`;
        setSystemStatus({ text: `Online · ${prov}`, offline: false });
      }
    } catch {
      setSystemStatus({ text: 'Offline', offline: true });
    }
  };

  // ── Sessions ──
  const fetchSessions = async () => {
    try {
      const data = await api.loadSessions();
      setSessions(data);
    } catch {
      setSessions([]);
    }
  };

  const handleDeleteSession = async (id) => {
    try {
      await api.deleteSession(id);
      toast('info', 'Session deleted');
      fetchSessions();
    } catch {
      toast('warning', 'Could not delete session');
    }
  };

  const handleLoadSession = async (sessionId) => {
    setCurrentSessionId(sessionId);
    try {
      const manifest = await api.loadSessionManifest(sessionId);
      const taskList = manifest.tasks || [];
      const artifacts = {};
      for (const fname of (manifest.final_artifacts || [])) {
        const content = await api.loadArtifact(sessionId, fname);
        if (content) artifacts[fname] = content;
      }

      const done = taskList.filter(t => t.status === 'done').length;
      const failed = taskList.filter(t => t.status === 'failed').length;
      const scores = taskList.filter(t => typeof t.score === 'number').map(t => t.score);
      const avg = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;

      setScorecard({ total_tasks: taskList.length, completed: done, failed, avg_score: Math.round(avg * 10) / 10 });
      setTasks(taskList);
      setCurrentArtifacts(artifacts);

      // Show summary in terminal
      clearTerminal();
      addLine(`📂 Session: ${sessionId}`, 'event-agent');
      addLine(`🎯 Goal: ${manifest.goal || 'N/A'}`, 'event-log');
      addLine(`⏱ Time: ${manifest.summary?.total_time_s || '?'}s`, 'event-log');
      addLine(`📄 Artifacts: ${(manifest.final_artifacts || []).join(', ') || 'none'}`, 'event-success');
      toast('success', 'Session loaded');
    } catch {
      toast('error', 'Load failed', 'Could not fetch session data');
    }
  };

  const handleNewSession = () => {
    setCurrentSessionId(null);
    setScorecard(null);
    setTasks(null);
    setCurrentArtifacts({});
    clearTerminal();
  };

  // ── Terminal helpers ──
  const addLine = useCallback((text, className = 'event-log') => {
    setTerminalLines(prev => [...prev, {
      id: ++lineIdCounter,
      text,
      className,
      ts: formatTimestamp(),
    }]);
  }, []);

  const clearTerminal = useCallback(() => {
    setTerminalLines([]);
  }, []);

  // ── Agent card helpers ──
  const AGENT_NAMES = ['Scout', 'Architect', 'Builder', 'Critic', 'Guardian'];

  const updateAgentFromLog = useCallback((text) => {
    setAgentStates(prev => {
      const next = [...prev];
      AGENT_NAMES.forEach((name, idx) => {
        if (text.includes(name)) {
          if (text.includes('✅') || text.includes('complete')) next[idx] = 'done';
          else if (text.includes('❌') || text.includes('failed')) next[idx] = 'error';
          else next[idx] = 'active';
        }
      });
      return next;
    });
  }, []);

  const markAllDone = useCallback(() => {
    setAgentStates(prev => prev.map(s => (s === 'active' || s === 'idle') ? 'done' : s));
  }, []);

  // ── Execute Swarm ──
  const handleExecute = useCallback(async (goal) => {
    if (isRunning) return;
    setIsRunning(true);
    setProgressComplete(false);
    setAgentStates(['idle', 'idle', 'idle', 'idle', 'idle']);
    clearTerminal();
    setScorecard(null);
    setTasks(null);

    addLine('🚀 NexusSentry swarm initializing…', 'event-agent');
    addLine(`🎯 Goal: ${goal}`, 'event-log');
    addLine('─'.repeat(52), 'event-log');

    try {
      await api.executeSwarm(goal, (event) => {
        switch (event.type) {
          case 'start':
            addLine(`✅ Run started (id: ${event.run_id})`, 'event-success');
            break;
          case 'log': {
            const cls = classifyLogLine(event.data);
            addLine(event.data, cls);
            updateAgentFromLog(event.data);
            break;
          }
          case 'heartbeat':
            break;
          case 'complete':
            addLine('─'.repeat(52), 'event-log');
            addLine('✅ Swarm complete!', 'event-success');
            addLine(`📊 Score: ${event.scorecard.avg_score}/100 | Tasks: ${event.scorecard.completed}/${event.scorecard.total_tasks}`, 'event-success');
            setCurrentArtifacts(event.artifacts || {});
            setCurrentSessionId(event.session_id);
            setScorecard(event.scorecard);
            setTasks(event.tasks);
            toast('success', 'Swarm complete!', `Score: ${event.scorecard.avg_score}/100`);
            markAllDone();
            break;
          case 'error':
            addLine(`❌ Error: ${event.error}`, 'event-error');
            if (event.traceback) addLine(event.traceback, 'event-error');
            toast('error', 'Swarm error', event.error?.substring(0, 80));
            break;
        }
      });
    } catch (e) {
      addLine(`❌ Connection error: ${e.message}`, 'event-error');
      toast('error', 'Connection failed', e.message);
    } finally {
      setIsRunning(false);
      setProgressComplete(true);
      setTimeout(() => setProgressComplete(false), 600);
      fetchSessions();
    }
  }, [isRunning, addLine, clearTerminal, updateAgentFromLog, markAllDone, toast]);

  // ── Export / Copy ──
  const handleExportSession = () => {
    const lines = terminalLines.map(l => `[${l.className.replace('event-', '')}] ${l.text}`).join('\n');
    const data = {
      session_id: currentSessionId,
      exported_at: new Date().toISOString(),
      terminal_log: lines,
      artifacts: Object.keys(currentArtifacts),
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `nexussentry-session-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast('success', 'Session exported');
  };

  const handleCopyLog = () => {
    const log = terminalLines.map(l => l.text).join('\n');
    if (!log) { toast('warning', 'Terminal is empty'); return; }
    navigator.clipboard.writeText(log)
      .then(() => toast('success', 'Terminal log copied!'))
      .catch(() => toast('error', 'Copy failed'));
  };

  // ── Global Keyboard Shortcuts ──
  useEffect(() => {
    const handler = (e) => {
      const tag = document.activeElement.tagName;
      const isInput = (tag === 'TEXTAREA' || tag === 'INPUT');

      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); /* handled by PromptPanel */ return; }
      if (e.key === 'Escape') {
        setShortcutsOpen(false);
        terminalRef.current?.toggleSearch?.(false);
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') { e.preventDefault(); terminalRef.current?.toggleSearch?.(true); return; }
      if ((e.ctrlKey || e.metaKey) && e.key === 'l') { e.preventDefault(); clearTerminal(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key === 'b') { e.preventDefault(); setSidebarCollapsed(v => !v); return; }

      if (isInput) return;
      if (e.key === '/') { e.preventDefault(); document.querySelector('.prompt-textarea')?.focus(); }
      if (e.key === '?') setShortcutsOpen(true);
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [clearTerminal]);

  // ── Render ──
  return (
    <>
      <ShortcutsModal open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />

      <div className={`app-container${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
        <Header
          systemStatus={systemStatus}
          onToggleSidebar={() => setSidebarCollapsed(v => !v)}
          onOpenShortcuts={() => setShortcutsOpen(true)}
          onExportSession={handleExportSession}
          onCopyLog={handleCopyLog}
        />

        <Sidebar
          sessions={sessions}
          activeSessionId={currentSessionId}
          onLoadSession={handleLoadSession}
          onDeleteSession={handleDeleteSession}
          onNewSession={handleNewSession}
        />

        <main className="main-content">
          <PromptPanel onExecute={handleExecute} isRunning={isRunning} />
          <ProgressBar running={isRunning} complete={progressComplete} />

          <div className="output-area" ref={outputAreaRef}>
            <TerminalPanel
              ref={terminalRef}
              panelRef={terminalPanelRef}
              terminalLines={terminalLines}
              agentStates={agentStates}
              isRunning={isRunning}
              onClear={clearTerminal}
            />
            <ResizeDivider
              terminalPanelRef={terminalPanelRef}
              outputAreaRef={outputAreaRef}
            />
            <ResultsPanel
              scorecard={scorecard}
              tasks={tasks}
              resultView={resultView}
              onSwitchView={setResultView}
              artifactsContent={
                <ArtifactsView artifacts={currentArtifacts} sessionId={currentSessionId} />
              }
            />
          </div>
        </main>
      </div>
    </>
  );
}

export default App;

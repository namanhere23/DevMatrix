import React, { useRef, useEffect, useState } from 'react';
import { useToast } from './Toast';
import * as api from '../services/api';

const PRESETS = [
  'Portfolio website',
  'Todo app single HTML',
  'SQL injection audit',
  'Dashboard with charts',
  'REST API design doc',
];

export default function PromptPanel({ onExecute, isRunning }) {
  const [value, setValue] = useState('');
  const [isOptimizing, setIsOptimizing] = useState(false);
  const textareaRef = useRef(null);
  const toast = useToast();

  const charCount = value.length;
  const isWarn = charCount > 1800;

  // Auto-grow textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = '44px';
      ta.style.height = Math.min(ta.scrollHeight, 140) + 'px';
    }
  }, [value]);

  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleExecute();
    }
  };

  const handleExecute = () => {
    const goal = value.trim();
    if (!goal || isRunning) return;
    onExecute(goal);
  };

  const handleOptimize = async () => {
    const prompt = value.trim();
    if (!prompt || isRunning || isOptimizing) return;

    setIsOptimizing(true);
    try {
      const response = await api.optimizePrompt(prompt);
      const optimized = response?.result?.optimized_prompt || response?.optimized_prompt;
      if (optimized) {
        setValue(optimized);
        textareaRef.current?.focus();
        toast('success', 'Prompt optimized', 'The refined version is ready to run.');
      } else {
        throw new Error('Optimizer returned no optimized prompt');
      }
    } catch (error) {
      toast('error', 'Optimization failed', error.message || 'Could not optimize this prompt');
    } finally {
      setIsOptimizing(false);
    }
  };

  const usePreset = (text) => {
    setValue(text);
    textareaRef.current?.focus();
  };

  return (
    <div className="prompt-panel">
      <div className="prompt-label">
        <span>🎯</span> Goal for the AI agent swarm
      </div>
      <div className="prompt-input-group">
        <div className="prompt-textarea-wrap">
          <textarea
            ref={textareaRef}
            className="prompt-textarea"
            placeholder="e.g. Create a modern portfolio website with dark theme, animations, and a contact form…"
            rows={1}
            maxLength={2000}
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <span className={`char-count${isWarn ? ' warn' : ''}`}>{charCount} / 2000</span>
        </div>
        <div className="prompt-action-stack">
          <button
            className={`btn-optimize${isOptimizing ? ' running' : ''}`}
            onClick={handleOptimize}
            disabled={isRunning || isOptimizing || !value.trim()}
          >
            <span className="spinner" />
            {isOptimizing ? 'Optimizing' : 'Optimize'}
          </button>
          <button
            className={`btn-execute${isRunning ? ' running' : ''}`}
            onClick={handleExecute}
            disabled={isRunning}
          >
            <span className="spinner" />
            Execute
          </button>
        </div>
      </div>
      <div className="prompt-presets">
        {PRESETS.map((p, i) => (
          <span key={i} className="preset-chip" onClick={() => usePreset(p)}>{p}</span>
        ))}
      </div>
    </div>
  );
}

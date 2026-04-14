import React from 'react';
import { escapeHtml, scoreClass, statusIcon } from '../utils/helpers';

export default function ResultsPanel({
  scorecard,
  tasks,
  resultView,
  onSwitchView,
  artifactsContent,
}) {
  const hasResults = scorecard && tasks;

  return (
    <div className="results-panel">
      <div className="panel-header">
        <div className="panel-title">📊 Results</div>
        <div className="panel-actions">
          <div className="view-toggle">
            <button
              className={`view-toggle-btn${resultView === 'results' ? ' active' : ''}`}
              onClick={() => onSwitchView('results')}
            >Results</button>
            <button
              className={`view-toggle-btn${resultView === 'artifacts' ? ' active' : ''}`}
              onClick={() => onSwitchView('artifacts')}
            >Artifacts</button>
          </div>
        </div>
      </div>
      <div className="results-body">
        {!hasResults ? (
          <div className="results-welcome">
            <div className="icon">✨</div>
            <h3>Results will appear here</h3>
            <p>Execute a goal to see the scorecard, task results, and generated artifacts.</p>
          </div>
        ) : (
          <>
            {resultView === 'results' && (
              <div>
                {/* Scorecard */}
                <div className="scorecard">
                  <div className="score-card">
                    <div className="score-value">{scorecard.total_tasks || 0}</div>
                    <div className="score-label">Total Tasks</div>
                  </div>
                  <div className="score-card">
                    <div className="score-value">{scorecard.completed || 0}</div>
                    <div className="score-label">Completed</div>
                  </div>
                  <div className="score-card">
                    <div className="score-value">{scorecard.failed || 0}</div>
                    <div className="score-label">Failed</div>
                  </div>
                  <div className="score-card">
                    <div className="score-value">{scorecard.avg_score || 0}</div>
                    <div className="score-label">Avg Score</div>
                  </div>
                  {scorecard.estimated_cost && (
                    <div className="score-card">
                      <div className="score-value">{scorecard.estimated_cost}</div>
                      <div className="score-label">Est. Cost</div>
                    </div>
                  )}
                </div>

                {scorecard.providers && Object.keys(scorecard.providers).length > 0 && (
                  <div style={{ marginTop: '16px', fontSize: '13px', color: '#94a3b8', background: 'rgba(255, 255, 255, 0.05)', padding: '10px 14px', borderRadius: '6px' }}>
                    <span style={{ marginRight: '8px' }}>🤖 Providers:</span>
                    {Object.entries(scorecard.providers).map(([p, count]) => `${p} x${count}`).join(' | ')}
                  </div>
                )}

                {/* Task results */}
                {tasks.length > 0 && (
                  <div>
                    <div className="section-title">📋 Task Results</div>
                    {tasks.map((task, i) => {
                      const score = task.score || 0;
                      const sc = scoreClass(score);
                      return (
                        <div className="task-card" key={task.task_id || i}>
                          <div className="task-status-icon">{statusIcon(task.status)}</div>
                          <div className="task-info">
                            <div className="task-name">{task.task || ''}</div>
                            <div className="task-meta">
                              {task.attempts || 0} attempts · {(task.execution_mode || '').toUpperCase()}
                            </div>
                          </div>
                          <div className={`task-score${sc ? ' ' + sc : ''}`}>{score}/100</div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
            {resultView === 'artifacts' && artifactsContent}
          </>
        )}
      </div>
    </div>
  );
}

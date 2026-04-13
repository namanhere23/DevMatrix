import React, { useState } from 'react';
import { escapeHtml, escapeAttr } from '../utils/helpers';
import { getArtifactUrl } from '../services/api';

export default function ArtifactsView({ artifacts, sessionId }) {
  const filenames = Object.keys(artifacts || {});
  const [activeFile, setActiveFile] = useState(filenames[0] || '');

  if (!filenames.length) {
    return (
      <div className="results-welcome">
        <div className="icon">📭</div>
        <h3>No artifacts</h3>
        <p>No files were generated in this run.</p>
      </div>
    );
  }

  const content = artifacts[activeFile] || '';
  const isHtml = activeFile.endsWith('.html') || activeFile.endsWith('.htm');

  const copyContent = () => {
    navigator.clipboard.writeText(content).catch(() => {});
  };

  const downloadContent = () => {
    const blob = new Blob([content], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = activeFile;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const openInNewTab = () => {
    if (sessionId) {
      window.open(getArtifactUrl(sessionId, activeFile), '_blank');
    } else {
      const blob = new Blob([content], { type: 'text/html' });
      window.open(URL.createObjectURL(blob), '_blank');
    }
  };

  const iframeSrc = sessionId
    ? getArtifactUrl(sessionId, activeFile)
    : undefined;

  return (
    <div className="artifact-section">
      <div className="section-title">📄 Generated Artifacts</div>
      <div className="artifact-tabs">
        {filenames.map(f => (
          <div
            key={f}
            className={`artifact-tab${f === activeFile ? ' active' : ''}`}
            onClick={() => setActiveFile(f)}
          >{f}</div>
        ))}
      </div>

      {/* Toolbar */}
      <div className="artifact-toolbar">
        <button className="artifact-toolbar-btn" onClick={copyContent}>📋 Copy</button>
        <button className="artifact-toolbar-btn" onClick={downloadContent}>⬇️ Download</button>
        {isHtml && (
          <button className="artifact-toolbar-btn" onClick={openInNewTab}>↗ Open</button>
        )}
      </div>

      {/* Preview */}
      {isHtml ? (
        <>
          <div className="artifact-preview">
            {iframeSrc ? (
              <iframe src={iframeSrc} sandbox="allow-scripts allow-same-origin" title="Artifact Preview" />
            ) : (
              <iframe srcDoc={content} sandbox="allow-scripts allow-same-origin" title="Artifact Preview" />
            )}
          </div>
          <details style={{ marginTop: 10 }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: '11px', padding: '7px 0', userSelect: 'none' }}>
              View Source
            </summary>
            <pre className="artifact-code">{content}</pre>
          </details>
        </>
      ) : (
        <pre className="artifact-code">{content}</pre>
      )}
    </div>
  );
}

import React from 'react';

export default function ProgressBar({ running, complete }) {
  let className = 'progress-bar';
  let style = { width: '0%' };

  if (running) {
    className += ' indeterminate';
  } else if (complete) {
    style = { width: '100%' };
  }

  return (
    <div className="progress-bar-wrap">
      <div className={className} style={style} />
    </div>
  );
}

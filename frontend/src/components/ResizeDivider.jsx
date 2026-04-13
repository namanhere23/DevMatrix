import React, { useRef, useCallback, useEffect } from 'react';

export default function ResizeDivider({ terminalPanelRef, outputAreaRef }) {
  const dividerRef = useRef(null);
  const dragging = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  const onMouseDown = useCallback((e) => {
    dragging.current = true;
    startX.current = e.clientX;
    startWidth.current = terminalPanelRef.current?.offsetWidth || 0;
    dividerRef.current?.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [terminalPanelRef]);

  useEffect(() => {
    const onMouseMove = (e) => {
      if (!dragging.current) return;
      const dx = e.clientX - startX.current;
      const total = outputAreaRef.current?.offsetWidth || 800;
      const newW = Math.min(Math.max(startWidth.current + dx, 200), total - 205);
      if (terminalPanelRef.current) {
        terminalPanelRef.current.style.width = newW + 'px';
      }
    };

    const onMouseUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      dividerRef.current?.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    return () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
  }, [terminalPanelRef, outputAreaRef]);

  return (
    <div
      ref={dividerRef}
      className="resize-divider"
      onMouseDown={onMouseDown}
      title="Drag to resize"
    />
  );
}

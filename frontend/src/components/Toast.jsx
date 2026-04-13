import React, { createContext, useContext, useState, useCallback, useRef } from 'react';

const ToastContext = createContext(null);

export function useToast() {
  return useContext(ToastContext);
}

let toastIdCounter = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const toastsRef = useRef([]);

  const dismiss = useCallback((id) => {
    setToasts(prev => prev.map(t => t.id === id ? { ...t, out: true } : t));
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 280);
  }, []);

  const toast = useCallback((type, title, msg = '', duration = 3500) => {
    const id = ++toastIdCounter;
    setToasts(prev => [...prev, { id, type, title, msg, out: false }]);
    if (duration > 0) {
      setTimeout(() => dismiss(id), duration);
    }
  }, [dismiss]);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-container">
        {toasts.map(t => (
          <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

const ICONS = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };

function ToastItem({ toast, onDismiss }) {
  return (
    <div className={`toast ${toast.type}${toast.out ? ' out' : ''}`}>
      <span className="toast-icon">{ICONS[toast.type] || 'ℹ️'}</span>
      <div className="toast-body">
        <div className="toast-title">{toast.title}</div>
        {toast.msg && <div className="toast-msg">{toast.msg}</div>}
      </div>
      <button className="toast-close" onClick={onDismiss}>✕</button>
    </div>
  );
}

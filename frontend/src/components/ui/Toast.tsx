import React, { createContext, useContext, useState, useCallback } from 'react';
import { Check, AlertCircle, Info, X } from 'lucide-react';

export type ToastType = 'success' | 'info' | 'error';

export interface ToastMessage {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastContextType {
  toast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextType>({
  toast: () => {},
});

export const useToast = () => useContext(ToastContext);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const toast = useCallback((message: string, type: ToastType = 'info') => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, message, type }]);

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  }, []);

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}

      {/* TOAST CONTAINER - HIGHEST Z-INDEX OVER ALL OVERLAYS */}
      <div className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-2.5 pointer-events-none select-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-center justify-between gap-3 px-4 py-3 bg-[#181818] border rounded-none shadow-2xl shadow-black/80 text-xs font-sans animate-slide-up transition-all ${
              t.type === 'success'
                ? 'border-emerald-500/50 text-white'
                : t.type === 'error'
                ? 'border-rose-500/50 text-white'
                : 'border-[#ff6b00]/50 text-white'
            }`}
          >
            <div className="flex items-center gap-2.5">
              {t.type === 'success' && <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />}
              {t.type === 'error' && <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />}
              {t.type === 'info' && <Info className="w-4 h-4 text-[#ff6b00] flex-shrink-0" />}
              <span className="font-medium text-[#f4f5f8]">{t.message}</span>
            </div>

            <button
              onClick={() => removeToast(t.id)}
              className="text-[#8a8f9e] hover:text-white transition-colors p-0.5 rounded-none"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

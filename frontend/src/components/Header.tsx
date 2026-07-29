import React, { useState } from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { PixelBrain, PixelKey } from './ui/PixelIcons';
import { getApiKey, setApiKey } from '../api';

interface HeaderProps {
  onRefresh: () => void;
  isAuthenticated: boolean;
  onOpenNewMemoryModal: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onRefresh, isAuthenticated, onOpenNewMemoryModal }) => {
  const [keyInput, setKeyInput] = useState(getApiKey());
  const [showKeyModal, setShowKeyModal] = useState(false);

  const handleConnect = () => {
    if (keyInput.trim()) {
      setApiKey(keyInput.trim());
      setShowKeyModal(false);
      onRefresh();
    }
  };

  const handleLock = () => {
    setApiKey('');
    setKeyInput('');
    setShowKeyModal(false);
    onRefresh();
  };

  return (
    <header className="h-14 border-b border-[#1e2029] bg-[#0a0b0e] px-6 flex items-center justify-between font-sans text-xs select-none">
      {/* BREADCRUMB TITLE - EXACT h-14 ALIGNED WITH SIDEBAR */}
      <div className="flex items-center gap-2 text-white font-medium text-xs">
        <PixelBrain className="w-4 h-4 text-[#ff6b00]" />
        <span>GigaMind</span>
        <span className="text-[#8a8f9e]">/</span>
        <span className="text-[#8a8f9e] font-normal">Console</span>
      </div>

      {/* RIGHT ACTIONS */}
      <div className="flex items-center gap-3">
        {/* + NEW MEMORY BUTTON */}
        <button
          onClick={onOpenNewMemoryModal}
          className="bg-transparent hover:bg-[#181a24] border border-[#262936] text-white px-3 py-1.5 rounded-none flex items-center gap-1.5 font-medium transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>New Memory</span>
        </button>

        {/* MASTER KEY AUTH BUTTON */}
        <button
          onClick={() => setShowKeyModal(!showKeyModal)}
          className={`border px-3 py-1.5 rounded-none flex items-center gap-1.5 font-medium transition-colors ${
            isAuthenticated
              ? 'bg-[#10b981]/15 text-emerald-400 border-emerald-500/30'
              : 'bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white border-transparent hover:opacity-90'
          }`}
        >
          <PixelKey className="w-3.5 h-3.5" />
          <span>{isAuthenticated ? 'Connected' : 'Master Key'}</span>
        </button>

        {/* REFRESH */}
        <button
          onClick={onRefresh}
          className="p-1.5 text-[#8a8f9e] hover:text-white border border-[#262936] bg-[#101216] rounded-none transition-colors"
          title="Refresh telemetry"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* MASTER KEY POPUP MODAL */}
      {showKeyModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-xs z-50 flex items-center justify-center p-4">
          <div className="bg-[#13151c] border border-[#1e2029] max-w-sm w-full p-6 rounded-none shadow-2xl space-y-4">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <PixelKey className="w-4 h-4 text-[#ff6b00]" />
              Master API Key Settings
            </h3>
            <p className="text-xs text-[#8a8f9e]">
              Enter your GigaMind Master Password to authenticate local API access.
            </p>
            <input
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleConnect()}
              placeholder="Enter GIGAMIND_API_KEY..."
              autoFocus
              className="w-full bg-[#0a0b0e] border border-[#1e2029] focus:border-[#ff6b00] p-2.5 text-white font-mono text-xs rounded-none outline-none"
            />
            <div className="flex justify-end gap-2 pt-2">
              {isAuthenticated && (
                <button
                  onClick={handleLock}
                  className="bg-rose-500/20 text-rose-400 border border-rose-500/30 px-3 py-1.5 rounded-none text-xs font-medium"
                >
                  Disconnect
                </button>
              )}
              <button
                onClick={() => setShowKeyModal(false)}
                className="bg-[#181a24] text-[#8a8f9e] hover:text-white px-3 py-1.5 rounded-none text-xs"
              >
                Cancel
              </button>
              <button
                onClick={handleConnect}
                className="bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white px-4 py-1.5 rounded-none text-xs font-medium"
              >
                Save & Connect
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
};

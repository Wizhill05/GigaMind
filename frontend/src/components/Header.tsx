import React, { useState, useEffect } from 'react';
import { Plus, RefreshCw, Search, ExternalLink } from 'lucide-react';
import { PixelKey } from './ui/PixelIcons';
import { getApiKey, setApiKey } from '../api';
import { useToast } from './ui/Toast';

interface HeaderProps {
  onRefresh: () => void;
  isAuthenticated: boolean;
  onOpenNewMemoryModal: () => void;
  onOpenCommandPalette: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  onRefresh,
  isAuthenticated,
  onOpenNewMemoryModal,
  onOpenCommandPalette,
}) => {
  const [keyInput, setKeyInput] = useState(getApiKey());
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [isExiting, setIsExiting] = useState(false);

  const { toast } = useToast();

  // Handle ESC key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showKeyModal && !isExiting) {
        handleAnimatedClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showKeyModal, isExiting]);

  const handleAnimatedClose = () => {
    setIsExiting(true);
    setTimeout(() => {
      setIsExiting(false);
      setShowKeyModal(false);
    }, 180);
  };

  const handleConnect = () => {
    if (keyInput.trim()) {
      setApiKey(keyInput.trim());
      handleAnimatedClose();
      toast('Master Key saved & authenticated', 'success');
      onRefresh();
    }
  };

  const handleLock = () => {
    setApiKey('');
    setKeyInput('');
    handleAnimatedClose();
    toast('Disconnected Master Key', 'info');
    onRefresh();
  };

  return (
    <header className="h-14 border-b border-[#1e2029] bg-[#0a0b0e] px-6 flex items-center justify-between font-sans text-xs select-none">
      {/* BREADCRUMB TITLE */}
      <div className="flex items-center gap-2 text-white font-medium text-xs">
        <span className="font-semibold tracking-tight text-white text-sm">GigaMind</span>
        <span className="text-[#8a8f9e]">/</span>
        <span className="text-[#8a8f9e] font-normal">Console</span>
      </div>

      {/* RIGHT ACTIONS - UNIFORM h-8 (32px) HEIGHT FOR ALL BUTTONS */}
      <div className="flex items-center gap-2.5">
        {/* CMD+K SPOTLIGHT SEARCH BUTTON */}
        <button
          onClick={onOpenCommandPalette}
          className="h-8 bg-[#101216] border border-[#262936] hover:border-[#ff6b00]/40 text-[#8a8f9e] hover:text-white px-3 rounded-none flex items-center gap-2 font-medium transition-all btn-press"
          title="Search (Cmd+K / Ctrl+K)"
        >
          <Search className="w-3.5 h-3.5 text-[#ff6b00]" />
          <span className="text-xs">Search</span>
          <span className="bg-[#181a24] border border-[#262936] text-[10px] font-mono px-1.5 py-0.5 rounded-none text-[#8a8f9e] leading-none">
            ⌘K
          </span>
        </button>

        {/* CONNECT AI DOCS LINK */}
        <a
          href="https://github.com/Wizhill05/GigaMind#connecting-gigamind-to-ai-services--coding-harnesses"
          target="_blank"
          rel="noreferrer"
          className="h-8 bg-[#101216] border border-[#262936] hover:border-[#ff6b00]/40 text-[#8a8f9e] hover:text-white px-3 rounded-none flex items-center gap-1.5 font-medium transition-all btn-press"
          title="Connect AI Harnesses & Services Guide"
        >
          <ExternalLink className="w-3.5 h-3.5 text-[#ff6b00]" />
          <span className="leading-none text-xs">Connect AI</span>
        </a>

        {/* + NEW MEMORY BUTTON */}
        <button
          onClick={onOpenNewMemoryModal}
          className="h-8 bg-transparent hover:bg-[#181a24] border border-[#262936] text-white px-3 rounded-none flex items-center gap-1.5 font-medium transition-all btn-press"
        >
          <Plus className="w-3.5 h-3.5" />
          <span className="leading-none text-xs">New Memory</span>
        </button>

        {/* MASTER KEY AUTH BUTTON - UNIFORM h-8 HEIGHT */}
        <button
          onClick={() => setShowKeyModal(!showKeyModal)}
          className={`h-8 border px-3 rounded-none flex items-center gap-2 font-medium transition-all btn-press ${
            isAuthenticated
              ? 'bg-[#10b981]/15 text-emerald-400 border-emerald-500/30'
              : 'bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white border-transparent hover:opacity-90'
          }`}
        >
          <span className="flex items-center justify-center flex-shrink-0">
            <PixelKey className={`w-3.5 h-3.5 ${isAuthenticated ? 'text-emerald-400' : 'text-white'}`} />
          </span>
          <span className="leading-none text-xs flex items-center">{isAuthenticated ? 'Connected' : 'Master Key'}</span>
        </button>

        {/* REFRESH - UNIFORM h-8 w-8 HEIGHT & WIDTH */}
        <button
          onClick={() => {
            onRefresh();
            toast('Refreshed system telemetry', 'info');
          }}
          className="h-8 w-8 flex items-center justify-center text-[#8a8f9e] hover:text-white border border-[#262936] bg-[#101216] rounded-none transition-all btn-press"
          title="Refresh telemetry"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* MASTER KEY POPUP MODAL WITH SMOOTH FADE & BACKDROP BLUR */}
      {showKeyModal && (
        <div
          onClick={handleAnimatedClose}
          className={`fixed inset-0 bg-black/70 backdrop-blur-md z-50 flex items-center justify-center p-4 transition-all duration-200 ${
            isExiting ? 'animate-fade-out' : 'animate-fade-in'
          }`}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className={`bg-[#13151c] border border-[#1e2029] max-w-sm w-full p-6 rounded-none shadow-2xl space-y-4 ${
              isExiting ? 'animate-scale-out' : 'animate-scale-in'
            }`}
          >
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <PixelKey className="w-4 h-4 text-[#ff6b00]" />
              Master API Key Settings
            </h3>
            <p className="text-xs text-[#8a8f9e] leading-relaxed">
              Enter your GigaMind Master Password to authenticate local API access.
            </p>
            <input
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleConnect()}
              placeholder="Enter GIGAMIND_API_KEY..."
              autoFocus
              className="w-full bg-[#0a0b0e] border border-[#1e2029] focus:border-[#ff6b00] p-2.5 text-white font-mono text-xs rounded-none outline-none transition-colors"
            />
            <div className="flex justify-end gap-2 pt-2">
              {isAuthenticated && (
                <button
                  onClick={handleLock}
                  className="bg-rose-500/20 text-rose-400 border border-rose-500/30 px-3 py-1.5 rounded-none text-xs font-medium btn-press"
                >
                  Disconnect
                </button>
              )}
              <button
                onClick={handleAnimatedClose}
                className="bg-[#181a24] text-[#8a8f9e] hover:text-white px-3 py-1.5 rounded-none text-xs btn-press"
              >
                Cancel
              </button>
              <button
                onClick={handleConnect}
                className="bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] text-white px-4 py-1.5 rounded-none text-xs font-medium btn-press shadow-sm"
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

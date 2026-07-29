import React, { useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { PixelKey } from './ui/PixelIcons';
import { setApiKey } from '../api';

interface AuthGateProps {
  onAuthenticate: () => void;
  errorNotice?: boolean;
}

export const AuthGate: React.FC<AuthGateProps> = ({ onAuthenticate, errorNotice }) => {
  const [keyInput, setKeyInput] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (keyInput.trim()) {
      setApiKey(keyInput.trim());
      onAuthenticate();
    }
  };

  return (
    <div className="fixed inset-0 bg-[#0a0b0e]/90 backdrop-blur-sm z-50 flex items-center justify-center p-4 font-sans select-none">
      <div className="bg-[#13151c] border border-[#1e2029] max-w-md w-full p-8 rounded-none shadow-2xl space-y-6">
        <div className="text-center space-y-2">
          <div className="w-12 h-12 bg-[#ff6b00]/20 border border-[#ff6b00]/40 text-[#ff6b00] mx-auto rounded-none flex items-center justify-center">
            <PixelKey className="w-6 h-6 text-[#ff6b00]" />
          </div>
          <h2 className="text-xl font-bold text-white tracking-tight">
            Authenticate Connection
          </h2>
          <p className="text-xs text-[#8a8f9e] leading-relaxed">
            Enter your GigaMind Master Password to access your personal memory database and telemetry endpoints.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          <div>
            <label className="block text-xs font-medium text-[#c1c5d0] mb-1.5">
              Master API Key
            </label>
            <input
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="Enter GIGAMIND_API_KEY..."
              autoFocus
              className="w-full bg-[#0a0b0e] border border-[#1e2029] focus:border-[#ff6b00] p-3 text-white font-mono text-xs rounded-none outline-none transition-colors"
            />
          </div>

          {errorNotice && (
            <div className="bg-rose-500/10 border border-rose-500/30 p-3 text-xs text-rose-400 rounded-none text-center">
              Invalid Master Password. Please check your key and try again.
            </div>
          )}

          <button
            type="submit"
            className="w-full bg-gradient-to-r from-[#ff6b00] to-[#f59e0b] hover:opacity-90 text-white font-semibold py-3 rounded-none text-xs tracking-wide flex items-center justify-center gap-2 shadow-lg shadow-[#ff6b00]/20 transition-all"
          >
            <span>Authorize Connection</span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </form>
      </div>
    </div>
  );
};
